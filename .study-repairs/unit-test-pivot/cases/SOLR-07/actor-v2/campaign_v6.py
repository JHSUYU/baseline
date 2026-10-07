#!/usr/bin/env python3
"""Offline-audited SOLR-07 V6 continuation after a natural V5 stop.

V6 preserves the original JUnit, Java agent, V2 trial runner, queue, seen plans,
and completed-trial ledger. It discovers shallow fault plans from exact same-
client target windows. Importing this module never starts a cluster or writes a
checkpoint; only explicit ``freeze``, ``activate``, and ``continue`` do so.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from statistics import median
import subprocess
import tempfile

import campaign_v2 as v2
import campaign_v5 as v5
from build_v2 import sha
from calibrate_v2 import detail, rows, selected, target_signature


POLICY = 'v6_shallow_observed_io'
V6_FILE = Path(__file__)
HANDOFF = v2.HERE / 'handoff-v6'
V5_LOCK = v5.HANDOFF / 'controller.lock'
V6_LOCK = HANDOFF / 'controller.lock'
RAW_FILES = v5.RAW_FILES
EXTRA_SELECTED = 256
MAX_PAIR_CHOICES = 12
ORIGIN_ROOT = 'v6_observed_root'
ORIGIN_PAIR = 'v6_observed_pair'


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def plan_id(target: list[str], sequence: list[dict]) -> str:
    return v2.identity((target, sequence))


def effective_count(state: dict) -> int:
    return sum(bool(row['effective']) for row in state['trials'])


def assert_completed_ledger(state: dict) -> None:
    trials = state['trials']
    n = state['selected_count']
    if state.get('case_id') != 'SOLR-07' or n != len(trials) or n != len(state['seen']):
        raise RuntimeError('checkpoint case or completed-trial count differs')
    completed = [plan_id(row['target'], row['sequence']) for row in trials]
    queued = [plan_id(row['target'], row['sequence']) for row in state['queue']]
    if (state['seen'] != completed or len(set(completed)) != n or
            len(set(queued)) != len(queued) or set(queued) & set(completed)):
        raise RuntimeError('completed and queued plan identities differ or duplicate')
    if any(row['number'] != i for i, row in enumerate(trials, 1)):
        raise RuntimeError('completed trial number differs from ledger position')


def assert_natural_v5_stop(state: dict) -> tuple[int, int]:
    """Reject running, partial, successful, or ambiguously stopped V5 states."""
    assert_completed_ledger(state)
    metadata = state.get('scheduler_v5')
    if (not metadata or metadata.get('policy') != v5.POLICY or
            metadata.get('sha256') != sha(v5.V5_FILE) or
            metadata.get('v4_sha256') != sha(v5.V4_FILE) or
            state.get('scheduler_v6')):
        raise RuntimeError('source is not the pinned V5 scheduler')
    if not state.get('stopped'):
        raise RuntimeError('V5 has not naturally stopped')
    n, good = state['selected_count'], effective_count(state)
    if state.get('effective_count') != good or good >= 80:
        raise RuntimeError('V5 count differs or effective target was already met')
    budget = state['budget']
    if (budget.get('effective_trials') != 80 or
            not 1 <= budget.get('max_faults', 0) <= 8 or
            not 1 <= budget.get('max_selected', 0) <= 512):
        raise RuntimeError('V5 budget differs from the pinned V6 handoff policy')
    reason = state.get('stop_reason')
    if reason == 'selected_trial_cap':
        if n < budget['max_selected']:
            raise RuntimeError('selected cap is not reached')
    elif reason == 'plan_exhausted':
        if state['queue'] or not state.get('plan_exhaustion'):
            raise RuntimeError('plan-exhausted state lacks a final empty-queue receipt')
    else:
        # V5 owns a queue_exhausted refill stage, so it is not a final handoff.
        raise RuntimeError(f'V5 stop is not final: {reason}')
    if n != len(state['trials']) or n < metadata['handoff']['selected']:
        raise RuntimeError('V5 selected count predates its audited handoff')
    return n, good


def no_active_junit_or_v5() -> None:
    listing = subprocess.check_output(['ps', '-eo', 'pid=,args='], text=True)
    for line in listing.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not fields[0].isdigit() or int(fields[0]) == os.getpid():
            continue
        command = fields[1]
        if re.search(r'(^|[\s/])campaign_v[245]\.py(?:\s|$)', command):
            raise RuntimeError(f'an older SOLR-07 controller still runs: pid {fields[0]}')
        if ('baseline.solr07.RunSingleJUnit' in command and
                'org.apache.solr.cloud.AddReplicaTest' in command and
                'testAddMultipleReplicas' in command):
            raise RuntimeError(f'SOLR-07 JUnit still runs: pid {fields[0]}')


@contextmanager
def exclusive_controller():
    """V5 and V6 lifetime locks prevent two controllers from taking one ID."""
    HANDOFF.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        for path in (V5_LOCK, V6_LOCK):
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = stack.enter_context(path.open('a+b'))
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(f'controller lock is held: {path}') from error
        yield


def immutable(path: Path, raw: bytes) -> None:
    """Publish a complete sealed artifact or leave the final name untouched.

    A controller interruption before publication leaves only an expendable
    temporary file. Repeating freeze with the same checkpoint is idempotent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,
                                         prefix=f'.{path.name}.',
                                         delete=False) as output:
            temporary = Path(output.name)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o444)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw or path.stat().st_mode & 0o222:
                raise RuntimeError(f'pre-existing immutable artifact differs: {path}')
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def raw_manifest(state: dict) -> dict:
    artifacts: dict[str, dict[str, str]] = {}
    for number in range(1, state['selected_count'] + 1):
        directory = v2.ROOT / f'trial-{number:03d}'
        entries = {}
        for name in RAW_FILES:
            file = directory / name
            if not file.is_file():
                raise RuntimeError(f'completed trial lacks raw artifact: {file}')
            entries[name] = sha(file)
        artifacts[str(number)] = entries
    return {'case_id': 'SOLR-07', 'selected': state['selected_count'],
            'artifacts': artifacts}


def verify_raw_manifest(manifest: dict, state: dict) -> None:
    if (manifest.get('case_id') != 'SOLR-07' or
            manifest.get('selected') != state['selected_count'] or
            len(manifest.get('artifacts', {})) != state['selected_count']):
        raise RuntimeError('raw manifest does not cover the frozen checkpoint')
    for number in range(1, state['selected_count'] + 1):
        expected = manifest['artifacts'].get(str(number), {})
        directory = v2.ROOT / f'trial-{number:03d}'
        for name in RAW_FILES:
            file = directory / name
            if not file.is_file() or sha(file) != expected.get(name):
                raise RuntimeError(f'frozen raw artifact changed: {file}')


def verify_raw_ledger(state: dict) -> None:
    """Cross-check the pinned raw plan and run against every ledger receipt."""
    build = json.loads((v2.HERE / 'build-receipt.json').read_text())
    for number, saved in enumerate(state['trials'], 1):
        directory = v2.ROOT / f'trial-{number:03d}'
        raw_trial = json.loads((directory / 'trial.json').read_text())
        run = json.loads((directory / 'run.json').read_text())
        if raw_trial != saved or saved['number'] != number:
            raise RuntimeError(f'raw trial differs from frozen ledger: {number}')
        if (run.get('exit_code') != saved['junit_exit'] or
                run.get('agent_sha256') != state['agent_sha256'] or
                run.get('source_revision') != build['source_revision'] or
                run.get('test') != build['test'] or
                run.get('assertions_enabled') is not True or
                run.get('instrumented') is not True or
                run.get('plan') != str((directory / 'fault.properties').resolve())):
            raise RuntimeError(f'raw JUnit run differs from pinned build or ledger: {number}')
        properties = dict(line.split('=', 1) for line in
                          (directory / 'fault.properties').read_text().splitlines()
                          if '=' in line)
        if (properties.get('count') != str(len(saved['sequence'])) or
                properties.get('targetActor') != saved['target'][0] or
                any(properties.get(f'step.{index}.{field}') != str(point[field])
                    for index, point in enumerate(saved['sequence'], 1)
                    for field in v2.FIELDS)):
            raise RuntimeError(f'raw fault plan differs from frozen ledger: {number}')
        with (directory / 'events.jsonl').open() as events:
            applied = sum(json.loads(line)['event'] == 'IO_APPLIED'
                          for line in events if line.strip())
        if applied != saved['applied_faults']:
            raise RuntimeError(f'raw applied count differs from frozen ledger: {number}')


def build_inventory(state: dict, manifest: dict) -> dict:
    """Derive root plans from passing, exact, post-fault target windows.

The returned inventory is pure data. It does not enqueue or run anything.
    """
    known = set(state['seen'])
    known.update(plan_id(row['target'], row['sequence']) for row in state['queue'])
    first_v5 = state['scheduler_v5']['handoff']['selected'] + 1
    found: dict[str, dict] = {}
    for result in state['trials'][first_v5 - 1:]:
        if not (result['junit_exit'] == 0 and result['exact_injection'] and
                result['effective'] and result['target_after_fault'] and
                not result['target_exception']):
            continue
        number = result['number']
        directory = v2.ROOT / f'trial-{number:03d}'
        expected = manifest['artifacts'][str(number)]
        for name in ('events.jsonl', 'junit.log', 'run.json', 'trial.json'):
            if sha(directory / name) != expected[name]:
                raise RuntimeError(f'inventory witness raw changed: {directory / name}')
        if json.loads((directory / 'trial.json').read_text()) != result:
            raise RuntimeError(f'inventory witness trial differs: {number}')
        if not v5.PASS_MARKER.search((directory / 'junit.log').read_text(errors='replace')):
            continue
        trace = rows(directory)
        v2.audit_trial(trace)
        if not v2.exact(trace, result['sequence']):
            raise RuntimeError(f'inventory witness is not exact: {number}')
        applied = [row for row in trace if row['event'] == 'IO_APPLIED']
        last = applied[-1]
        client = v2.client_id(last)
        target = tuple(result['target'])
        guards = [row for row in trace if selected(row) and
                  target_signature(row) == target and row['seq'] > last['seq'] and
                  row['actorKey'] == last['actorKey'] and
                  v2.client_id(row) == client and
                  detail(row['detail']).get('corePresent') == 'true']
        if not guards:
            continue
        guard = min(guards, key=lambda row: row['seq'])
        for row in trace:
            if not (v2.relevant(row) and row['seq'] < guard['seq'] and
                    row['actorKey'] == target[0] and v2.client_id(row) == client):
                continue
            point = v2.point(row)
            key = plan_id(result['target'], [point])
            if key in known:
                continue
            phase = ('post_last_fault_pre_guard' if row['seq'] > last['seq']
                     else 'pre_fault_pre_guard')
            info = detail(row['detail'])
            witness = {'trial': number, 'io_seq': row['seq'],
                       'last_fault_seq': last['seq'], 'guard_seq': guard['seq'],
                       'phase': phase, 'thread_id': row['threadId'],
                       'client_identity': client, 'physical_node': info.get('nodeName'),
                       'events_sha256': expected['events.jsonl'],
                       'junit_sha256': expected['junit.log'],
                       'elapsed_seconds': result['elapsed_seconds']}
            entry = found.setdefault(key, {'identity': key, 'target': result['target'],
                                            'sequence': [point], 'witnesses': []})
            if not any(saved['trial'] == number and saved['phase'] == phase
                       for saved in entry['witnesses']):
                entry['witnesses'].append(witness)
    for entry in found.values():
        entry['witnesses'].sort(key=lambda item: (item['trial'], item['phase']))
        post = {w['trial'] for w in entry['witnesses']
                if w['phase'] == 'post_last_fault_pre_guard'}
        distinct = {w['trial'] for w in entry['witnesses']}
        entry['post_witness_trials'] = len(post)
        entry['witness_trials'] = len(distinct)
        entry['tier'] = (0 if len(post) >= 2 else 1 if post else
                         2 if len(distinct) >= 2 else 3)
        entry['median_elapsed_seconds'] = median(
            {w['trial']: w['elapsed_seconds'] for w in entry['witnesses']}.values())
    candidates = sorted(found.values(), key=lambda entry: (entry['tier'],
                        v2.family(entry['sequence'][0]), entry['identity']))
    return {'case_id': 'SOLR-07', 'source_checkpoint_sha256': state['_frozen_sha256'],
            'selected': state['selected_count'], 'candidate_count': len(candidates),
            'tiers': {str(key): value for key, value in
                      sorted(Counter(row['tier'] for row in candidates).items())},
            'candidates': candidates}


def freeze() -> dict:
    with exclusive_controller():
        no_active_junit_or_v5()
        raw = v2.STATE.read_bytes()
        state = json.loads(raw)
        number, good = assert_natural_v5_stop(state)
        v2.verify_state(state)
        if (v2.ROOT / f'trial-{number + 1:03d}').exists():
            raise RuntimeError('unaccounted in-flight trial directory; reconcile first')
        state_sha = digest(raw)
        manifest = raw_manifest(state)
        manifest['checkpoint_sha256'] = state_sha
        working = {**state, '_frozen_sha256': state_sha}
        inventory = build_inventory(working, manifest)
        if v2.STATE.read_bytes() != raw:
            raise RuntimeError('V5 checkpoint changed while freezing')
        no_active_junit_or_v5()
        label = f'{number}-{state_sha[:16]}'
        snapshot_path = HANDOFF / f'state-{label}.json'
        manifest_path = HANDOFF / f'raw-{label}.json'
        inventory_path = HANDOFF / f'inventory-{label}.json'
        immutable(snapshot_path, raw)
        immutable(manifest_path, canonical(manifest))
        immutable(inventory_path, canonical(inventory))
        return {'selected': number, 'effective': good,
                'snapshot': str(snapshot_path), 'snapshot_sha256': state_sha,
                'manifest': str(manifest_path), 'manifest_sha256': sha(manifest_path),
                'inventory': str(inventory_path), 'inventory_sha256': sha(inventory_path),
                'candidate_count': inventory['candidate_count'], 'tiers': inventory['tiers'],
                'audit_command': (f'python3 audit_v2_checkpoint.py --state {snapshot_path} '
                                  f'--output {HANDOFF / ("audit-" + label + ".json")}')}


def validate_handoff(snapshot: Path, manifest_path: Path, inventory_path: Path,
                     audit_path: Path, *, current_raw: bytes | None = None,
                     require_no_next: bool = True) -> dict:
    for path in (snapshot, manifest_path, inventory_path, audit_path):
        if not path.is_file() or path.stat().st_mode & 0o222:
            raise RuntimeError(f'handoff artifact missing or writable: {path}')
    raw = snapshot.read_bytes()
    if current_raw is not None and current_raw != raw:
        raise RuntimeError('live V5 state changed after freeze')
    state = json.loads(raw)
    number, good = assert_natural_v5_stop(state)
    v2.verify_state(state)
    manifest = json.loads(manifest_path.read_text())
    audit = json.loads(audit_path.read_text())
    inventory = json.loads(inventory_path.read_text())
    state_sha = digest(raw)
    if (manifest.get('checkpoint_sha256') != state_sha or
            audit.get('checkpoint_sha256') != state_sha or
            audit.get('selected') != number or audit.get('effective') != good or
            audit.get('errors') != [] or audit.get('case_id') != 'SOLR-07'):
        raise RuntimeError('independent audit or frozen manifest disagrees')
    verify_raw_manifest(manifest, state)
    verify_raw_ledger(state)
    regenerated = build_inventory({**state, '_frozen_sha256': state_sha}, manifest)
    if inventory != regenerated or inventory.get('candidate_count') == 0:
        raise RuntimeError('inventory differs or has no untested root')
    if require_no_next and (v2.ROOT / f'trial-{number + 1:03d}').exists():
        raise RuntimeError('unaccounted in-flight trial directory')
    return {'selected': number, 'effective': good,
            'snapshot_sha256': state_sha, 'manifest_sha256': sha(manifest_path),
            'inventory_sha256': sha(inventory_path), 'audit_sha256': sha(audit_path),
            'candidate_count': inventory['candidate_count'], 'tiers': inventory['tiers']}


def verify_handoff(snapshot: Path, manifest: Path, inventory: Path,
                   audit: Path) -> dict:
    """Read-only readiness check; never starts the original JUnit."""
    with exclusive_controller():
        no_active_junit_or_v5()
        live_raw = v2.STATE.read_bytes()
        receipt = validate_handoff(snapshot, manifest, inventory, audit,
                                   current_raw=live_raw)
        if v2.STATE.read_bytes() != live_raw:
            raise RuntimeError('live V5 checkpoint changed during handoff validation')
        no_active_junit_or_v5()
        return receipt


def parent_for(state: dict, entry: dict,
               completed: dict[str, dict] | None = None) -> dict | None:
    if len(entry['sequence']) < 2:
        return None
    key = plan_id(entry['target'], entry['sequence'][:-1])
    if completed is None:
        completed = {plan_id(row['target'], row['sequence']): row
                     for row in state['trials']}
    return completed.get(key)


def old_entry_eligible(state: dict, entry: dict,
                       completed: dict[str, dict] | None = None) -> bool:
    if len(entry['sequence']) == 1:
        return True
    source = state['scheduler_v6']['source_scheduler_v5']
    key = plan_id(entry['target'], entry['sequence'][:-1])
    verdict = source['parent_verdicts'].get(key)
    if verdict is None:
        parent = parent_for(state, entry, completed)
        verdict = ({'eligible': False, 'reason': 'missing_parent'} if parent is None else
                   {'trial': parent['number'], **v5.parent_verdict(
                       parent, v2.ROOT / f'trial-{parent["number"]:03d}')})
        source['parent_verdicts'][key] = verdict
    return bool(verdict.get('eligible'))


def choose(state: dict) -> dict:
    queue = state['queue']
    if not queue:
        raise RuntimeError('V6 choose called with empty queue')
    for row in queue:
        row['wait'] = row.get('wait', 0) + 1
    completed = {plan_id(row['target'], row['sequence']): row
                 for row in state['trials']}
    fresh = [i for i, row in enumerate(queue)
             if row.get('origin') in (ORIGIN_ROOT, ORIGIN_PAIR)]
    fresh_set = set(fresh)
    legacy = [i for i, row in enumerate(queue) if i not in fresh_set and
              old_entry_eligible(state, row, completed)]
    if not legacy and not fresh:
        raise RuntimeError('V6 queue has only ineligible legacy descendants; '
                           'preserve them for explicit review rather than inject')
    selected_since_handoff = state['selected_count'] - state['scheduler_v6']['handoff']['selected']
    lane = (legacy if selected_since_handoff % 5 == 4 and legacy else
            fresh or legacy)
    if not lane:
        lane = fresh
    recent = state['trials'][-4:]
    last_family = (v2.family(recent[-1]['sequence'][-1]) if recent else None)
    same_family = 0
    for row in reversed(recent):
        if v2.family(row['sequence'][-1]) != last_family:
            break
        same_family += 1
    if same_family >= 4 and any(v2.family(queue[i]['sequence'][-1]) != last_family
                                for i in lane):
        lane = [i for i in lane if v2.family(queue[i]['sequence'][-1]) != last_family]
    last_parent = (plan_id(recent[-1]['target'], recent[-1]['sequence'][:-1])
                   if recent and len(recent[-1]['sequence']) > 1 else None)
    same_parent = 0
    if last_parent:
        for row in reversed(recent):
            if (len(row['sequence']) < 2 or
                    plan_id(row['target'], row['sequence'][:-1]) != last_parent):
                break
            same_parent += 1
    if same_parent >= 2 and any(len(queue[i]['sequence']) < 2 or
                                plan_id(queue[i]['target'], queue[i]['sequence'][:-1]) !=
                                last_parent for i in lane):
        lane = [i for i in lane if len(queue[i]['sequence']) < 2 or
                plan_id(queue[i]['target'], queue[i]['sequence'][:-1]) != last_parent]
    tested_family = Counter(v2.family(row['sequence'][-1]) for row in state['trials'])
    tested_parent = Counter(plan_id(row['target'], row['sequence'][:-1])
                            for row in state['trials'] if len(row['sequence']) > 1)

    def rank(index: int) -> tuple:
        entry = queue[index]
        family = v2.family(entry['sequence'][-1])
        parent = parent_for(state, entry, completed)
        parent_id = (plan_id(entry['target'], entry['sequence'][:-1])
                     if len(entry['sequence']) > 1 else '')
        gain = 0 if parent is None else parent['new_coverage'] + parent['new_families']
        cost = entry.get('cost_seconds', 60 if parent is None else
                         parent.get('elapsed_seconds', 60))
        return (entry.get('tier', 9), tested_family[family],
                tested_parent[parent_id] if parent_id else 0,
                -min(gain, 100), cost, -min(entry['wait'], 20),
                plan_id(entry['target'], entry['sequence']))

    return queue.pop(min(lane, key=rank))


def mutate(state: dict, target: list[str], sequence: list[dict],
           trace: list[dict], result: dict) -> None:
    """Add only witnessed pairs from a passing, strict one-fault parent."""
    if (len(sequence) != 1 or not result['effective'] or
            not result['exact_injection'] or result['junit_exit'] != 0 or
            result['target_exception']):
        return
    directory = v2.ROOT / f'trial-{result["number"]:03d}'
    verdict = v5.parent_verdict(result, directory)
    if not verdict['eligible']:
        return
    last = next(row for row in reversed(trace) if row['event'] == 'IO_APPLIED')
    client = v2.client_id(last)
    finish = verdict['first_guard_seq']
    choices = []
    seen_points = set()
    for row in trace:
        if (not v2.relevant(row) or not last['seq'] < row['seq'] < finish or
                row['actorKey'] != target[0] or v2.client_id(row) != client):
            continue
        point = v2.point(row)
        key = v2.identity(point)
        if key not in seen_points:
            seen_points.add(key)
            choices.append(point)
    # Favor points nearest the guard, with a few early points for breadth.
    selected_points = list(reversed(choices[-8:])) + choices[:4]
    known = set(state['seen'])
    known.update(plan_id(row['target'], row['sequence']) for row in state['queue'])
    for point in selected_points[:MAX_PAIR_CHOICES]:
        child = sequence + [point]
        key = plan_id(target, child)
        if key in known:
            continue
        known.add(key)
        state['queue'].append({'target': target, 'sequence': child,
                               'origin': ORIGIN_PAIR, 'tier': 1,
                               'parent_trial': result['number'],
                               'cost_seconds': result['elapsed_seconds'],
                               'parent_gain': result['new_coverage'] +
                                              result['new_families'], 'wait': 0})


def verify_new_trials(state: dict, first: int) -> None:
    assert_completed_ledger(state)
    for number in range(first + 1, state['selected_count'] + 1):
        directory = v2.ROOT / f'trial-{number:03d}'
        if any(not (directory / name).is_file() for name in RAW_FILES):
            raise RuntimeError(f'completed V6 trial lacks raw evidence: {directory}')
        saved = state['trials'][number - 1]
        if (json.loads((directory / 'trial.json').read_text()) != saved or
                json.loads((directory / 'run.json').read_text()).get('exit_code') !=
                saved['junit_exit']):
            raise RuntimeError(f'completed V6 receipt changed: {number}')
        plan = dict(line.split('=', 1) for line in
                    (directory / 'fault.properties').read_text().splitlines()
                    if '=' in line)
        if (plan.get('count') != str(len(saved['sequence'])) or
                plan.get('targetActor') != saved['target'][0] or
                any(plan.get(f'step.{i}.{field}') != str(step[field])
                    for i, step in enumerate(saved['sequence'], 1)
                    for field in v2.FIELDS)):
            raise RuntimeError(f'completed V6 fault plan changed: {number}')
        v2.audit_trial(rows(directory))
    if (v2.ROOT / f'trial-{state["selected_count"] + 1:03d}').exists():
        raise RuntimeError('unaccounted in-flight V6 trial; reconcile before continue')


def activate(snapshot: Path, manifest: Path, inventory_path: Path,
             audit: Path, *, run_campaign: bool = True) -> dict:
    with exclusive_controller():
        no_active_junit_or_v5()
        live_raw = v2.STATE.read_bytes()
        receipt = validate_handoff(snapshot, manifest, inventory_path, audit,
                                   current_raw=live_raw)
        state = json.loads(live_raw)
        candidates = json.loads(inventory_path.read_text())['candidates']
        known = set(state['seen'])
        known.update(plan_id(row['target'], row['sequence']) for row in state['queue'])
        additions = []
        for candidate in candidates:
            key = candidate['identity']
            if key in known:
                raise RuntimeError(f'frozen inventory duplicate: {key}')
            known.add(key)
            additions.append({'target': candidate['target'],
                              'sequence': candidate['sequence'],
                              'origin': ORIGIN_ROOT, 'tier': candidate['tier'],
                              'witness_trials': candidate['witness_trials'],
                              'post_witness_trials': candidate['post_witness_trials'],
                              'cost_seconds': candidate['median_elapsed_seconds'],
                              'parent_gain': 0, 'wait': 0})
        if not additions:
            raise RuntimeError('V6 has no distinct shallow root plan')
        number = receipt['selected']
        source_scheduler = state.pop('scheduler_v5')
        state['scheduler_v6'] = {
            'policy': POLICY, 'sha256': sha(V6_FILE),
            'source_scheduler_v5': source_scheduler,
            'frozen_checkpoint': str(snapshot.resolve()),
            'raw_manifest': str(manifest.resolve()),
            'raw_audit': str(audit.resolve()),
            'inventory': str(inventory_path.resolve()),
            'handoff': receipt,
            'activated_utc': datetime.now(timezone.utc).isoformat(),
            'budget': {'effective_trials': 80, 'max_selected': number + EXTRA_SELECTED,
                       'max_faults': 8, 'new_generation_max_depth': 2},
            'deficit_at_handoff': 80 - receipt['effective'],
            'added_roots': len(additions),
        }
        state['budget'] = {'effective_trials': 80,
                           'max_selected': number + EXTRA_SELECTED,
                           'max_faults': 8}
        state['extension_decided'] = True
        state['extension_reason'] = 'audited V6 shallow continuation; explicit 256 selected'
        state['queue'].extend(additions)
        state.pop('stopped', None)
        state.pop('stop_reason', None)
        state.pop('effective_count', None)
        state.pop('plan_exhaustion', None)
        if v2.STATE.read_bytes() != live_raw:
            raise RuntimeError('live V5 state changed before V6 commit')
        no_active_junit_or_v5()
        v2.atomic(v2.STATE, state)
        if run_campaign:
            v2.choose, v2.mutate = choose, mutate
            v2.campaign()
        return state


def continue_campaign() -> None:
    with exclusive_controller():
        no_active_junit_or_v5()
        state = json.loads(v2.STATE.read_text())
        v2.verify_state(state)
        metadata = state.get('scheduler_v6')
        if not metadata or metadata.get('policy') != POLICY or metadata.get('sha256') != sha(V6_FILE):
            raise RuntimeError('V6 scheduler identity differs from checkpoint')
        if state.get('scheduler_v5'):
            raise RuntimeError('older V5 controller metadata was not retired')
        handoff = metadata['handoff']
        paths = (Path(metadata['frozen_checkpoint']), Path(metadata['raw_manifest']),
                 Path(metadata['inventory']), Path(metadata['raw_audit']))
        for path, expected in zip(paths, (handoff['snapshot_sha256'],
                                          handoff['manifest_sha256'],
                                          handoff['inventory_sha256'],
                                          handoff['audit_sha256'])):
            if sha(path) != expected:
                raise RuntimeError(f'V6 handoff artifact changed: {path}')
        # The frozen N+1 directory becomes a normal completed V6 trial. The
        # current live N+1 gate is checked by verify_new_trials below.
        reviewed = validate_handoff(*paths, require_no_next=False)
        if reviewed != handoff:
            raise RuntimeError('V6 frozen handoff receipt changed after activation')
        if {key: state['budget'].get(key) for key in
                ('effective_trials', 'max_selected', 'max_faults')} != {
                key: metadata['budget'][key] for key in
                ('effective_trials', 'max_selected', 'max_faults')}:
            raise RuntimeError('V6 live budget differs from the audited activation')
        verify_new_trials(state, handoff['selected'])
        if state.get('stopped'):
            raise RuntimeError(f'V6 already reached natural stop: {state.get("stop_reason")}')
        v2.choose, v2.mutate = choose, mutate
        v2.campaign()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('freeze', help='freeze only a naturally stopped V5 with <80 effective')
    start = sub.add_parser('activate', help='validate immutable audit and start V6')
    start.add_argument('--snapshot', type=Path, required=True)
    start.add_argument('--manifest', type=Path, required=True)
    start.add_argument('--inventory', type=Path, required=True)
    start.add_argument('--audit', type=Path, required=True)
    check = sub.add_parser('verify', help='validate sealed handoff without JUnit')
    check.add_argument('--snapshot', type=Path, required=True)
    check.add_argument('--manifest', type=Path, required=True)
    check.add_argument('--inventory', type=Path, required=True)
    check.add_argument('--audit', type=Path, required=True)
    sub.add_parser('continue', help='resume a previously activated V6 checkpoint')
    args = parser.parse_args()
    if args.action == 'freeze':
        print(json.dumps(freeze(), indent=2, sort_keys=True))
    elif args.action == 'verify':
        print(json.dumps(verify_handoff(args.snapshot, args.manifest,
                                        args.inventory, args.audit),
                         indent=2, sort_keys=True))
    elif args.action == 'activate':
        activate(args.snapshot, args.manifest, args.inventory, args.audit)
    else:
        continue_campaign()


if __name__ == '__main__':
    main()
