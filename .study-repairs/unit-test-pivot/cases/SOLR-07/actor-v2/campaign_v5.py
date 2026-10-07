#!/usr/bin/env python3
"""Offline-audited V5 handoff and fair selection of productive fault descendants.

This file does not alter the V2/V4 runner, original JUnit, agent, or calibration.
Only ``activate`` / ``continue`` call the existing V2 campaign.  A passing JUnit
and a post-fault corePresent=true guard are an *active-compatible proxy*: raw
Probe events have no wall-clock stamp with which to prove the JUnit end boundary.
No TARGET_THROW is classified as a bug by this scheduler.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import campaign_v2 as v2
from build_v2 import sha
from calibrate_v2 import detail, rows, selected, target_signature


POLICY = 'passing_core_present_parent_fair_v5'
HANDOFF = v2.HERE / 'handoff-v5'
V4_FILE = v2.HERE / 'campaign_v4.py'
V5_FILE = v2.HERE / 'campaign_v5.py'
RAW_FILES = ('events.jsonl', 'run.json', 'trial.json', 'fault.properties',
             'junit.log', 'jacoco.exec')
PASS_MARKER = re.compile(r'(?m)^SOLR05_JUNIT_RESULT run=1 failures=0 ignored=0\s*$')


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checked_snapshot(state: dict) -> None:
    """Require a naturally ended V4 budget, with no ambiguous next trial."""
    if state.get('case_id') != 'SOLR-07' or not state.get('stopped'):
        raise RuntimeError('V4 has not reached a durable stopped checkpoint')
    if state.get('scheduler_v5'):
        raise RuntimeError('V5 handoff already activated')
    v4 = state.get('scheduler_v4', {})
    if (v4.get('policy') != 'all_stable_actor_roots_v4' or
            v4.get('sha256') != sha(V4_FILE)):
        raise RuntimeError('V4 scheduler identity differs from the checkpoint')
    selected_count = state['selected_count']
    trials = state['trials']
    if selected_count != len(trials) or len(state['seen']) != len(trials):
        raise RuntimeError('completed trials, selected count, and seen plans disagree')
    identities = [v2.identity((row['target'], row['sequence'])) for row in trials]
    if len(set(identities)) != len(identities) or set(identities) != set(state['seen']):
        raise RuntimeError('completed plan identities disagree with seen plans')
    queue_ids = [v2.identity((row['target'], row['sequence'])) for row in state['queue']]
    if len(set(queue_ids)) != len(queue_ids) or set(queue_ids) & set(identities):
        raise RuntimeError('queued plan duplicates a completed or queued plan')
    completed = {key: row for key, row in zip(identities, trials)}
    for row in state['queue']:
        if len(row['sequence']) > 1:
            parent = completed.get(parent_key(row['target'], row['sequence'][:-1]))
            if parent is None or not parent['effective']:
                raise RuntimeError('queued descendant lacks an effective completed parent')
    effective = sum(bool(row['effective']) for row in trials)
    if effective != state.get('effective_count'):
        raise RuntimeError('effective count differs from completed trials')
    budget = state['budget']
    if state.get('stop_reason') == 'effective_budget_met':
        if effective < budget['effective_trials']:
            raise RuntimeError('effective budget stop has an incomplete denominator')
        # V2 saves trial 80 before saving its conditional extension decision.
        # Such a crash-created stop must not be mistaken for a natural V4 end.
        if effective == 80 and not state.get('extension_decided'):
            recent = [row for row in trials if row['effective']][-8:]
            if any(row['new_coverage'] or row['new_families'] for row in recent):
                raise RuntimeError('V2 conditional 80-to-128 extension was not committed')
    elif state.get('stop_reason') == 'selected_trial_cap':
        if selected_count < budget['max_selected']:
            raise RuntimeError('selected cap stop has an incomplete denominator')
    else:
        raise RuntimeError('V5 requires V4 to reach its trial or effective budget cap')
    next_dir = v2.ROOT / f'trial-{selected_count + 1:03d}'
    if next_dir.exists():
        raise RuntimeError(f'unaccounted in-flight trial directory: {next_dir}')


def no_v4_process() -> None:
    """Operator check in addition to the frozen state; V4 cannot honor a lock."""
    listing = subprocess.check_output(['ps', '-eo', 'pid=,args='], text=True)
    own_pid = os.getpid()
    for line in listing.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not fields[0].isdigit() or int(fields[0]) == own_pid:
            continue
        command = fields[1]
        if re.search(r'(^|/)campaign_v4\.py(?:\s|$)', command):
            raise RuntimeError(f'V4 process is still running: pid {fields[0]}')


def immutable_json(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(content, indent=2, sort_keys=True) + '\n').encode()
    with path.open('xb') as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    path.chmod(0o444)


def freeze() -> dict:
    """Copy a stopped checkpoint and pin the complete raw evidence by SHA256."""
    no_v4_process()
    raw = v2.STATE.read_bytes()
    state = json.loads(raw)
    checked_snapshot(state)
    v2.verify_state(state)
    selected_count = state['selected_count']
    label = f'{selected_count}-{digest_bytes(raw)[:16]}'
    snapshot = HANDOFF / f'state-{label}.json'
    manifest_path = HANDOFF / f'raw-{label}.json'
    artifacts = {}
    for number in range(1, selected_count + 1):
        directory = v2.ROOT / f'trial-{number:03d}'
        artifacts[str(number)] = {}
        for name in RAW_FILES:
            file = directory / name
            if not file.is_file():
                raise RuntimeError(f'missing raw evidence: {file}')
            artifacts[str(number)][name] = sha(file)
    if v2.STATE.read_bytes() != raw:
        raise RuntimeError('V4 checkpoint changed while freezing evidence')
    HANDOFF.mkdir(parents=True, exist_ok=True)
    with snapshot.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    snapshot.chmod(0o444)
    immutable_json(manifest_path, {
        'case_id': 'SOLR-07', 'checkpoint_sha256': digest_bytes(raw),
        'selected': selected_count, 'artifacts': artifacts,
    })
    return {'snapshot': str(snapshot), 'manifest': str(manifest_path),
            'checkpoint_sha256': digest_bytes(raw), 'selected': selected_count,
            'audit_command': f'python3 audit_v2_checkpoint.py --state {snapshot} '
                             f'--output {HANDOFF / ("audit-" + label + ".json")}' }


def validate_handoff(snapshot: Path, manifest_path: Path, audit_path: Path,
                     state: dict, *, verify_raw: bool = True) -> dict:
    for artifact in (snapshot, manifest_path, audit_path):
        if artifact.stat().st_mode & 0o222:
            raise RuntimeError(f'handoff artifact has not been sealed read-only: {artifact}')
    frozen = json.loads(snapshot.read_text())
    checked_snapshot(frozen)
    frozen_sha = sha(snapshot)
    manifest = json.loads(manifest_path.read_text())
    audit = json.loads(audit_path.read_text())
    if (manifest.get('checkpoint_sha256') != frozen_sha or
            audit.get('checkpoint_sha256') != frozen_sha or
            manifest.get('selected') != frozen['selected_count'] or
            audit.get('selected') != frozen['selected_count'] or
            audit.get('effective') != frozen['effective_count'] or
            audit.get('errors') != []):
        raise RuntimeError('frozen checkpoint, raw manifest, or raw audit disagree')
    if 'scheduler_v5' not in state and v2.STATE.read_bytes() != snapshot.read_bytes():
        raise RuntimeError('live V4 state changed after the frozen checkpoint')
    if verify_raw:
        for number in range(1, frozen['selected_count'] + 1):
            expected = manifest['artifacts'].get(str(number), {})
            directory = v2.ROOT / f'trial-{number:03d}'
            for name in RAW_FILES:
                file = directory / name
                if not file.is_file() or sha(file) != expected.get(name):
                    raise RuntimeError(f'frozen raw evidence changed: {file}')
            saved = frozen['trials'][number - 1]
            run = json.loads((directory / 'run.json').read_text())
            if run.get('exit_code') != saved['junit_exit']:
                raise RuntimeError(f'trial {number} JUnit exit differs from raw run')
            plan = dict(line.split('=', 1) for line in
                        (directory / 'fault.properties').read_text().splitlines()
                        if '=' in line)
            if (plan.get('count') != str(len(saved['sequence'])) or
                    plan.get('targetActor') != saved['target'][0]):
                raise RuntimeError(f'trial {number} raw fault plan differs from checkpoint')
            for index, step in enumerate(saved['sequence'], 1):
                if any(plan.get(f'step.{index}.{field}') != str(step[field])
                       for field in v2.FIELDS):
                    raise RuntimeError(f'trial {number} raw fault step differs from checkpoint')
            with (directory / 'events.jsonl').open() as trace_file:
                applied = sum(json.loads(line)['event'] == 'IO_APPLIED'
                              for line in trace_file if line.strip())
            if applied != saved['applied_faults']:
                raise RuntimeError(f'trial {number} raw applied count differs from checkpoint')
    return {'snapshot_sha256': frozen_sha, 'manifest_sha256': sha(manifest_path),
            'audit_sha256': sha(audit_path), 'selected': frozen['selected_count'],
            'effective': frozen['effective_count']}


def parent_verdict(result: dict, directory: Path) -> dict:
    """Recheck a completed parent before using its descendants for V5."""
    if not (result.get('exact_injection') and result.get('effective') and
            result.get('target_after_fault') and result.get('junit_exit') == 0 and
            not result.get('target_exception')):
        return {'eligible': False, 'reason': 'not_passing_effective_parent'}
    try:
        run = json.loads((directory / 'run.json').read_text())
        log = (directory / 'junit.log').read_text(errors='replace')
        if run.get('exit_code') != 0 or not PASS_MARKER.search(log):
            return {'eligible': False, 'reason': 'original_junit_not_confirmed_pass'}
        trace = rows(directory)
        v2.audit_trial(trace)
        if not v2.exact(trace, result['sequence']):
            return {'eligible': False, 'reason': 'raw_fault_not_exact'}
        applied = [row for row in trace if row['event'] == 'IO_APPLIED']
        if not applied:
            return {'eligible': False, 'reason': 'no_applied_fault'}
        last = applied[-1]
        client = v2.client_id(last)
        live_guards = [row for row in trace if selected(row)
                       and target_signature(row) == tuple(result['target'])
                       and row['seq'] > last['seq']
                       and row['actorKey'] == last['actorKey']
                       and v2.client_id(row) == client
                       and detail(row['detail']).get('corePresent') == 'true']
        if not client or not live_guards:
            return {'eligible': False, 'reason': 'no_same_client_live_core_guard'}
        direct = any(row['threadId'] == last['threadId'] for row in live_guards)
        return {'eligible': True, 'reason': 'passing_core_present_proxy',
                'direct_thread': direct, 'post_fault_live_guards': len(live_guards),
                'last_fault_seq': last['seq'], 'first_guard_seq': live_guards[0]['seq'],
                'events_sha256': sha(directory / 'events.jsonl'),
                'junit_sha256': sha(directory / 'junit.log')}
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        return {'eligible': False, 'reason': 'raw_parent_audit_failed',
                'detail': str(error)}


def paired_post_fault_throws(trace: list[dict], result: dict) -> list[dict]:
    """Return candidate throws only with a same-thread/controller guard.

    The original V2 ``target_exception`` bit is deliberately broader.  This
    helper is for offline triage, never a bug oracle: a paired throw can still
    occur during CoreContainer shutdown after the JUnit's active work ended.
    """
    if not v2.exact(trace, result['sequence']):
        return []
    applied = [row for row in trace if row['event'] == 'IO_APPLIED']
    if not applied:
        return []
    last = applied[-1]
    client = v2.client_id(last)
    guards: dict[tuple[int, str], dict] = {}
    matches = []
    for row in trace:
        if (row['seq'] <= last['seq'] or row['actorKey'] != last['actorKey'] or
                target_signature(row) != tuple(result['target'])):
            continue
        info = detail(row['detail'])
        controller = info.get('controllerIdentity')
        if row['event'] == 'TARGET_CHECK' and selected(row):
            if controller:
                guards.pop((row['threadId'], controller), None)
            if (v2.client_id(row) == client and client and controller and
                    info.get('corePresent') == 'false'):
                guards[(row['threadId'], controller)] = row
        elif row['event'] == 'TARGET_THROW' and controller:
            guard = guards.pop((row['threadId'], controller), None)
            if guard is not None:
                matches.append({'throw_seq': row['seq'], 'guard_seq': guard['seq'],
                                'thread_id': row['threadId'],
                                'controller_identity': controller,
                                'client_identity': client,
                                'classification': 'paired_target_candidate_only'})
    return matches


def parent_key(target: list[str], sequence: list[dict]) -> str:
    return v2.identity((target, sequence))


def classify_queued_parents(state: dict) -> tuple[dict, dict]:
    trials = {parent_key(row['target'], row['sequence']): row
              for row in state['trials']}
    cache = state['scheduler_v5']['parent_verdicts']
    for entry in state['queue']:
        if len(entry['sequence']) == 1:
            continue
        key = parent_key(entry['target'], entry['sequence'][:-1])
        if key in cache:
            continue
        parent = trials.get(key)
        cache[key] = ({'eligible': False, 'reason': 'parent_not_completed'}
                      if parent is None else
                      {'trial': parent['number'], **parent_verdict(
                          parent, v2.ROOT / f'trial-{parent["number"]:03d}')})
    return trials, cache


def choose(state: dict) -> dict:
    """Four descendant slots and one root slot; balance parents/fault families."""
    queue = state['queue']
    if not queue:
        raise RuntimeError('V5 choose called with an empty queue')
    for entry in queue:
        entry['wait'] = entry.get('wait', 0) + 1
    _, verdicts = classify_queued_parents(state)
    roots = [i for i, entry in enumerate(queue) if len(entry['sequence']) == 1]
    live = [i for i, entry in enumerate(queue) if len(entry['sequence']) > 1 and
            verdicts[parent_key(entry['target'], entry['sequence'][:-1])]['eligible']]
    # Fallback descendants remain possible only after productive candidates and
    # roots are exhausted; a teardown throw never becomes an oracle verdict here.
    if roots and (state['selected_count'] % 5 == 4 or not live):
        candidates = roots
    else:
        candidates = live or roots or list(range(len(queue)))
    waiting = [i for i in candidates if queue[i]['wait'] >= 20]
    if waiting:
        # This explicit aging gate prevents a stream of new high-gain parents
        # from starving a zero-gain but passing/effective older parent.
        return queue.pop(min(waiting, key=lambda i: (-queue[i]['wait'],
                            parent_key(queue[i]['target'], queue[i]['sequence']))))
    tested_first = Counter(v2.family(row['sequence'][0]) for row in state['trials']
                           if len(row['sequence']) > 1)
    tested_parent = Counter(parent_key(row['target'], row['sequence'][:-1])
                            for row in state['trials'] if len(row['sequence']) > 1)
    tested_roots = Counter(v2.family(row['sequence'][0]) for row in state['trials']
                           if len(row['sequence']) == 1)

    def rank(index: int) -> tuple:
        entry = queue[index]
        sequence = entry['sequence']
        family = v2.family(sequence[0])
        key = parent_key(entry['target'], sequence)
        if len(sequence) == 1:
            return (tested_roots[family], -min(entry['wait'], 200), key)
        parent = parent_key(entry['target'], sequence[:-1])
        direct = verdicts[parent].get('direct_thread', False)
        return (tested_first[family], tested_parent[parent],
                0 if direct else 1, len(sequence),
                -min(entry.get('parent_gain', 0), 100), -min(entry['wait'], 200), key)

    return queue.pop(min(candidates, key=rank))


def activate(snapshot: Path, manifest: Path, audit: Path, effective_budget: int,
             max_selected: int, max_faults: int, *, run_campaign: bool = True) -> dict:
    no_v4_process()
    state = json.loads(v2.STATE.read_text())
    checked_snapshot(state)
    v2.verify_state(state)
    evidence = validate_handoff(snapshot, manifest, audit, state)
    if not state['queue']:
        raise RuntimeError('V4 checkpoint has no pending fault sequence for V5')
    if (effective_budget <= state['effective_count'] or
            max_selected <= state['selected_count'] or
            max_faults < state['budget']['max_faults'] or max_faults > 10):
        raise RuntimeError('V5 budgets must extend the checkpoint without reducing fault depth')
    state['scheduler_v5'] = {
        'policy': POLICY, 'sha256': sha(V5_FILE),
        'v4_sha256': sha(V4_FILE), 'frozen_checkpoint': str(snapshot.resolve()),
        'raw_manifest': str(manifest.resolve()), 'raw_audit': str(audit.resolve()),
        'handoff': evidence, 'activated_utc': datetime.now(timezone.utc).isoformat(),
        'parent_verdicts': {},
        'rule': 'four productive descendants and one root per five selections; '
                'balance first-fault family and immediate parent',
        'stage_limit': 'passing JUnit plus corePresent=true is a proxy, not a '
                       'clock-proven active-test boundary',
    }
    state['budget'] = {'effective_trials': effective_budget,
                       'max_selected': max_selected, 'max_faults': max_faults}
    state['extension_decided'] = True  # explicit V5 budget supersedes V2 auto-extension
    state['extension_reason'] = 'audited V5 handoff with explicit budget'
    state.pop('stopped', None)
    state.pop('stop_reason', None)
    state.pop('effective_count', None)
    v2.atomic(v2.STATE, state)
    if run_campaign:
        v2.choose = choose
        v2.campaign()
    return state


def continue_campaign() -> None:
    no_v4_process()
    state = json.loads(v2.STATE.read_text())
    v2.verify_state(state)
    metadata = state.get('scheduler_v5')
    if not metadata or metadata['policy'] != POLICY or metadata['sha256'] != sha(V5_FILE):
        raise RuntimeError('V5 scheduler identity differs from activated checkpoint')
    if metadata['v4_sha256'] != sha(V4_FILE):
        raise RuntimeError('V4 scheduler changed after V5 handoff')
    for name, expected in (('frozen_checkpoint', metadata['handoff']['snapshot_sha256']),
                           ('raw_manifest', metadata['handoff']['manifest_sha256']),
                           ('raw_audit', metadata['handoff']['audit_sha256'])):
        if sha(Path(metadata[name])) != expected:
            raise RuntimeError(f'V5 handoff artifact changed: {name}')
    reviewed = validate_handoff(Path(metadata['frozen_checkpoint']),
                                Path(metadata['raw_manifest']),
                                Path(metadata['raw_audit']), state)
    if reviewed != metadata['handoff']:
        raise RuntimeError('V5 handoff evidence changed after activation')
    if state['selected_count'] != len(state['trials']) or len(state['seen']) != len(state['trials']):
        raise RuntimeError('V5 checkpoint trial count mismatch')
    if (v2.ROOT / f'trial-{state["selected_count"] + 1:03d}').exists():
        raise RuntimeError('unaccounted in-flight V5 trial; reconcile before resuming')
    if state.get('stopped'):
        raise RuntimeError('V5 already reached its configured stop; do not rerun')
    v2.choose = choose
    v2.campaign()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('freeze', help='freeze stopped V4 state and raw SHA manifest only')
    start = sub.add_parser('activate', help='verify offline audit and start V5')
    start.add_argument('--snapshot', type=Path, required=True)
    start.add_argument('--manifest', type=Path, required=True)
    start.add_argument('--audit', type=Path, required=True)
    start.add_argument('--effective-budget', type=int, required=True)
    start.add_argument('--max-selected', type=int, required=True)
    start.add_argument('--max-faults', type=int, required=True)
    sub.add_parser('continue', help='resume an already activated V5 checkpoint')
    args = parser.parse_args()
    if args.action == 'freeze':
        print(json.dumps(freeze(), indent=2, sort_keys=True))
    elif args.action == 'activate':
        activate(args.snapshot, args.manifest, args.audit,
                 args.effective_budget, args.max_selected, args.max_faults)
    else:
        continue_campaign()


if __name__ == '__main__':
    main()
