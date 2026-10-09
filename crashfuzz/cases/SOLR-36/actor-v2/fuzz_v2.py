#!/usr/bin/env python3
"""Resumable actor-aware ZK fault fuzzing of the original ShardSplitTest JUnit."""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
import time

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / 'independent'
sys.path.insert(0, str(PARENT))
from build import TEST_CLASS, TEST_METHOD
from coverage import covered_probes
from run import run as run_junit


ROOT = HERE / 'campaign'
AGENT = HERE / 'solrsubshard-actor-v2-agent.jar'
SEEDS = (HERE / 'healthy-01', HERE / 'healthy-02')
TARGET_PREFIX = 'SOLR/SUBSHARD/collection1/shard1_'
COLLECTION_SOURCE = 'SOLR/COLLECTION/collection1'
REPLICA_PREFIX = 'SOLR/REPLICA/collection1/shard1_'
GUARDS = {'SOLR-36': 'SOLR36:ACTIVE_SUBSHARD_GUARD',
          'SOLR-37': 'SOLR37:CHILD_RANGE_SUBSET_GUARD'}
THROWS = {'SOLR-36': 'SOLR36:ACTIVE_SUBSHARD_THROW',
          'SOLR-37': 'SOLR37:CHILD_RANGE_THROW'}
LOCKED_FILES = ('fuzz_v2.py', 'build_agent.py', 'run_healthy.py', 'calibrate.py')


def runner_hashes() -> dict[str, str]:
    paths = [HERE / name for name in LOCKED_FILES]
    paths.extend((PARENT / 'run.py', PARENT / 'coverage.py',
                  PARENT / 'build.py', AGENT))
    return {str(path.relative_to(HERE.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def load_events(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / 'events.jsonl').open()
            if line.strip()]


def point(event: dict) -> dict:
    return {name: event[name] for name in
            ('marker', 'siteId', 'sourceKey', 'actorKey', 'resource',
             'hitOrdinal', 'sessionGeneration')}


def point_id(item: dict) -> str:
    return json.dumps(item, sort_keys=True, separators=(',', ':'))


def family(item: dict) -> str:
    resource = re.sub(r'(/overseer/collection-queue-work/(?:qnr|qn)-)\d+$',
                      r'\1{queue-sequence}', item['resource'])
    resource = re.sub(r'(/leader_elect/[^/]+/election/)[^/]+$',
                      r'\1{ephemeral-election-node}', resource)
    return '|'.join((item['marker'], item['siteId'], item['sourceKey'],
                     item['actorKey'], str(item['sessionGeneration']), resource))


def unstable_resource(item: dict) -> bool:
    return bool(re.search(r'/leader_elect/[^/]+/election/[^/]+$',
                          item['resource']) or
                re.search(r'/overseer/collection-queue-work/(?:qnr|qn)-\d+$',
                          item['resource']))


def relevant(item: dict) -> bool:
    source = item['sourceKey']
    resource = item['resource']
    belongs = ((source == COLLECTION_SOURCE and
                resource.startswith('/collections/collection1')) or
               (source.startswith(REPLICA_PREFIX) and
                (resource.startswith('/collections/collection1') or
                 resource.startswith('/overseer/queue/'))))
    return (belongs and item['actorKey'].startswith('JETTY/')
            and item['sessionGeneration'] > 0
            and not source.startswith('UNRESOLVED:')
            and not item['siteId'].startswith('UNRESOLVED:'))


def audit_event_identities(events: list[dict]) -> dict:
    """Fail closed on a fault or target guard without the registered client and handle."""
    bindings = {}
    for event in events:
        if event['event'] != 'CLIENT_BIND':
            continue
        match = re.search(r'clientIdentity=(\d+)', event['detail'])
        if not match or not event['actorKey'].startswith('JETTY/'):
            continue
        identity = int(match.group(1))
        binding = (event['actorKey'], event['physicalNode'])
        if identity in bindings and bindings[identity] != binding:
            raise RuntimeError('one SolrZkClient maps to multiple physical actors')
        bindings[identity] = binding
    if not bindings:
        raise RuntimeError('no registered SolrZkClient')
    checked_io = checked_target = 0
    handles = {}
    for event in events:
        selected = event['event'] == 'IO_OBSERVED' and event['applied']
        target = event['event'] in ('TARGET_ENTER', 'TARGET_CHECK', 'TARGET_THROW')
        if not selected and not target:
            continue
        identity = event.get('zkClientIdentity', 0)
        binding = bindings.get(identity)
        if binding != (event['actorKey'], event['physicalNode']):
            raise RuntimeError('selected I/O or target guard has wrong SolrZkClient actor')
        if (event.get('zkHandleIdentity', 0) <= 0 or
                event.get('zkSessionId', 0) <= 0 or
                event.get('sessionGeneration', 0) <= 0):
            raise RuntimeError('selected I/O or target guard has no raw ZK session')
        if selected and not event.get('sessionEligible', False):
            raise RuntimeError('selected I/O has disconnected ZK handle')
        key = (identity, event['sessionGeneration'])
        raw = (event['zkHandleIdentity'], event['zkSessionId'])
        if key in handles and handles[key] != raw:
            raise RuntimeError('one client generation has inconsistent raw ZK handle/session')
        handles[key] = raw
        checked_io += selected
        checked_target += target
    return {'bindings': len(bindings), 'applied_io_checked': checked_io,
            'target_events_checked': checked_target, 'client_generations': len(handles)}


def guard_events(events: list[dict], case_id: str) -> list[dict]:
    return [event for event in events if event['event'] == 'TARGET_CHECK'
            and event['marker'] == GUARDS[case_id]
            and event['actorKey'].startswith('JETTY/')
            and event['sourceKey'].startswith(TARGET_PREFIX)]


def throw_events(events: list[dict], case_id: str) -> list[dict]:
    return [event for event in events if event['event'] == 'TARGET_THROW'
            and event['marker'] == THROWS[case_id]
            and event['actorKey'].startswith('JETTY/')
            and event['sourceKey'].startswith(TARGET_PREFIX)
            and 'org.apache.solr.common.SolrException' in event['detail']]


def target_actor_map(events: list[dict]) -> dict[str, str]:
    actors: dict[str, set[str]] = defaultdict(set)
    for case_id in GUARDS:
        for event in guard_events(events, case_id):
            actors[event['sourceKey']].add(event['actorKey'])
    if not actors or any(len(roles) != 1 for roles in actors.values()):
        raise RuntimeError('target child has no stable unique server actor')
    return {child: next(iter(roles)) for child, roles in sorted(actors.items())}


def matching_target_actor(event: dict, expected: dict[str, str]) -> bool:
    return event['actorKey'] == expected.get(event['sourceKey'])


def seed_candidates(events_a: list[dict], events_b: list[dict]) -> list[dict]:
    for events in (events_a, events_b):
        for case_id in GUARDS:
            if not guard_events(events, case_id):
                raise RuntimeError(f'healthy original test did not reach {case_id}')
            if throw_events(events, case_id):
                raise RuntimeError(f'healthy original test already throws at {case_id}')
    if target_actor_map(events_a) != target_actor_map(events_b):
        raise RuntimeError('target child-to-actor mapping differs across healthy seeds')
    first_guard = max(event['seq'] for case_id in GUARDS
                      for event in guard_events(events_a, case_id))
    second_guard = max(event['seq'] for case_id in GUARDS
                       for event in guard_events(events_b, case_id))
    exact_b = {point_id(point(event)) for event in events_b
               if event['event'] == 'IO_OBSERVED' and event['seq'] < second_guard
               and event.get('sessionEligible') and relevant(point(event))}
    groups: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for event in events_a:
        if event['event'] != 'IO_OBSERVED' or event['seq'] >= first_guard:
            continue
        item = point(event)
        identity = point_id(item)
        if (not event.get('sessionEligible') or not relevant(item)
                or identity not in exact_b or identity in seen):
            continue
        seen.add(identity)
        groups[family(item)].append(item)
    chosen: list[dict] = []
    for items in groups.values():
        for index in sorted({0, len(items) // 2, len(items) - 1}):
            chosen.append(items[index])
    chosen.sort(key=lambda item: (not item['sourceKey'].startswith(REPLICA_PREFIX),
                                  item['marker'], item['siteId'], item['resource'],
                                  item['hitOrdinal']))
    return chosen


def write_plan(path: Path, sequence: list[dict]) -> None:
    lines = ['count=' + str(len(sequence))]
    for number, item in enumerate(sequence, 1):
        for field in ('marker', 'siteId', 'sourceKey', 'actorKey', 'resource',
                      'hitOrdinal', 'sessionGeneration'):
            lines.append(f'step.{number}.{field}={item[field]}')
    path.write_text('\n'.join(lines) + '\n')


def junit_gate(log: str) -> tuple[int, int, int] | None:
    match = re.search(r'SOLR_SUBSHARD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)', log)
    return tuple(map(int, match.groups())) if match else None


def analyze(directory: Path, sequence: list[dict], prior_probes: set[str],
            prior_families: set[str], expected_target_actors: dict[str, str]
            ) -> tuple[dict, set[str], set[str], list[dict]]:
    events = load_events(directory)
    identity_audit = audit_event_identities(events)
    applied = [event for event in events if event['event'] == 'IO_OBSERVED'
               and event['applied']]
    strict = len(applied) == len(sequence) and all(
        point_id(point(event)) == point_id(item)
        for event, item in zip(applied, sequence))
    summaries = [event for event in events if event['event'] == 'SUMMARY']
    strict = strict and len(summaries) == 1 and summaries[0]['detail'] == \
        f'applied={len(sequence)}/{len(sequence)}'
    last_fault = applied[-1]['seq'] if applied else -1
    guards = {case_id: [event for event in guard_events(events, case_id)
                        if matching_target_actor(event, expected_target_actors)]
              for case_id in GUARDS}
    throws = {case_id: [event for event in throw_events(events, case_id)
                        if matching_target_actor(event, expected_target_actors)]
              for case_id in GUARDS}
    post_guard = {case_id: sum(event['seq'] > last_fault for event in rows)
                  if strict else 0 for case_id, rows in guards.items()}
    post_throw = {case_id: sum(event['seq'] > last_fault for event in rows)
                  if strict else 0 for case_id, rows in throws.items()}
    metadata = json.loads((directory / 'run.json').read_text())
    if metadata['agent_sha256'] != hashlib.sha256(AGENT.read_bytes()).hexdigest():
        raise RuntimeError('fault attempt used a different V2 agent')
    if metadata['original_source_revision'] != json.loads(
            (HERE / 'source-provenance.json').read_text())['revision']:
        raise RuntimeError('fault attempt used a different original Solr revision')
    if metadata['classpath_contains_graphchecker']:
        raise RuntimeError('fault attempt included GraphChecker classes')
    gate = junit_gate((directory / 'console.log').read_text())
    probes = (covered_probes(directory / 'jacoco.exec')
              if (directory / 'jacoco.exec').is_file()
              and (directory / 'jacoco.exec').stat().st_size else set())
    observed = [event for event in events if event['event'] == 'IO_OBSERVED'
                and event.get('sessionEligible') and relevant(point(event))]
    families = {family(point(event)) for event in observed}
    result = {
        'junit_exit': metadata['exit_code'],
        'junit_gate': gate,
        'elapsed_seconds': metadata['elapsed_seconds'],
        'strict_injection': strict,
        'planned_faults': len(sequence),
        'applied_faults': len(applied),
        'target_guard_count': {case_id: len(rows) for case_id, rows in guards.items()},
        'target_guard_after_last_fault': post_guard,
        'exact_target_throw_count': {case_id: len(rows) for case_id, rows in throws.items()},
        'exact_target_throw_after_last_fault': post_throw,
        'target_preserved': strict and all(post_guard.values()),
        'expected_target_actors': expected_target_actors,
        'raw_actor_session_audit': identity_audit,
        'io_observed_count': sum(event['event'] == 'IO_OBSERVED' for event in events),
        'production_probes_covered': len(probes),
        'new_production_probes': len(probes - prior_probes),
        'new_io_families': len(families - prior_families),
        'trace': str(directory / 'events.jsonl'),
        'jacoco': str(directory / 'jacoco.exec'),
    }
    return result, probes, families, observed


def enqueue(state: dict, sequence: list[dict], parent_gain: int = 0) -> None:
    digest = hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:20]
    if digest in state['seen_sequences']:
        return
    state['seen_sequences'].append(digest)
    state['queue'].append({'id': digest, 'sequence': sequence,
                           'parent_gain': parent_gain,
                           'created_after': len(state['completed'])})


def select(state: dict) -> dict:
    round_number = len(state['completed']) + 1
    rng = random.Random(310000 + round_number)
    queue = state['queue']
    prefer_multiple = round_number >= 16 and round_number % 3 != 0
    choices = [entry for entry in queue if len(entry['sequence']) > 1] if prefer_multiple else []
    if not choices:
        choices = [entry for entry in queue if len(entry['sequence']) == 1]
    if not choices:
        choices = queue
    preferred_source = REPLICA_PREFIX if round_number % 3 else COLLECTION_SOURCE
    source_choices = [entry for entry in choices
                      if entry['sequence'][0]['sourceKey'].startswith(preferred_source)]
    if source_choices:
        choices = source_choices
    first_counts = Counter(row['first_family'] for row in state['completed'])
    last_counts = Counter(row['last_family'] for row in state['completed'])
    scored = []
    for entry in choices:
        first = family(entry['sequence'][0])
        last = family(entry['sequence'][-1])
        score = (80 / (1 + first_counts[first]) + 30 / (1 + last_counts[last])
                 + (30 if entry['sequence'][-1]['sourceKey'].startswith(REPLICA_PREFIX)
                    else 0)
                 + min(20, entry['parent_gain'] / 5)
                 + min(16, 4 * len(entry['sequence']))
                 + min(10, round_number - entry['created_after']))
        scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1]['id']))
    top = scored[:min(12, len(scored))]
    chosen = rng.choices([entry for _, entry in top],
                         weights=[score for score, _ in top], k=1)[0]
    queue.remove(chosen)
    return chosen


def mutate(state: dict, parent: list[dict], observed: list[dict],
           applied_seq: int, gain: int, max_faults: int) -> None:
    if len(parent) >= max_faults:
        return
    used = {point_id(item) for item in parent}
    events = load_events(Path(state['completed'][-1]['trace']).parent)
    guards = [event for case_id in GUARDS for event in guard_events(events, case_id)
              if matching_target_actor(event, state['target_actor_map'])]
    later_guard = min((event['seq'] for event in guards if event['seq'] > applied_seq),
                      default=None)
    if later_guard is None:
        return
    by_family: dict[str, dict] = {}
    for event in observed:
        if not (applied_seq < event['seq'] < later_guard):
            continue
        item = point(event)
        if point_id(item) in used or unstable_resource(item):
            continue
        group = family(item)
        if group not in by_family or item['sourceKey'].startswith(REPLICA_PREFIX):
            by_family[group] = item
    ranked = sorted(by_family.values(), key=lambda item: (
        not item['sourceKey'].startswith(REPLICA_PREFIX), item['siteId'], item['resource']))
    for child in ranked[:12]:
        enqueue(state, parent + [child], parent_gain=gain)


def publish(state: dict) -> None:
    completed = state['completed']
    atomic(ROOT / 'state.json', state)
    for case_id in GUARDS:
        progress = {
            'case_id': case_id,
            'methodology': 'coverage_io_independent_asm_jacoco',
            'status': state['status'],
            'budget': state['budget'],
            'selected_plans': len(completed),
            'effective_trials': effective_count(state, case_id),
            'total_attempts': sum(row['attempts'] for row in completed),
            'strict_injections': sum(row['strict_injection'] for row in completed),
            'post_fault_target_reach_trials': sum(
                row['strict_injection'] and row['target_guard_after_last_fault'][case_id] > 0
                for row in completed),
            'target_exception_after_fault_trials': sum(
                row['strict_injection'] and row['exact_target_throw_after_last_fault'][case_id] > 0
                for row in completed),
            'target_preserved_trials': sum(
                row['strict_injection'] and row['target_guard_after_last_fault'][case_id] > 0
                for row in completed),
            'production_probe_gain': len(state['covered_probes']) - state['seed_probe_count'],
            'io_family_gain': len(state['io_families']) - state['seed_io_family_count'],
            'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in completed), 3),
            'first_fault_families': dict(Counter(row['first_family'] for row in completed)),
            'latest': completed[-1] if completed else None,
        }
        atomic(ROOT / ('progress-' + case_id + '.json'), progress)


def initialize(max_trials: int, max_faults: int, max_selected_plans: int) -> dict:
    calibration_path = HERE / 'calibration-receipt.json'
    if not calibration_path.is_file():
        raise RuntimeError('two-run actor calibration receipt required')
    calibration = json.loads(calibration_path.read_text())
    if calibration['agent_sha256'] != hashlib.sha256(AGENT.read_bytes()).hexdigest():
        raise RuntimeError('calibration used a different V2 agent')
    if calibration['source_provenance_sha256'] != hashlib.sha256(
            (HERE / 'source-provenance.json').read_bytes()).hexdigest():
        raise RuntimeError('calibration used different original source/JAR')
    if any(hashlib.sha256((directory / 'events.jsonl').read_bytes()).hexdigest()
           != receipt['trace_sha256']
           for directory, receipt in zip(SEEDS, calibration['healthy_runs'])):
        raise RuntimeError('healthy trace changed since actor calibration')
    seeds = [load_events(directory) for directory in SEEDS]
    for directory in SEEDS:
        metadata = json.loads((directory / 'run.json').read_text())
        if metadata['exit_code'] != 0 or junit_gate((directory / 'console.log').read_text()) != (1, 0, 0):
            raise RuntimeError(f'original healthy JUnit did not pass: {directory}')
    points = seed_candidates(*seeds)
    if not points:
        raise RuntimeError('no stable exact I/O selector before target')
    seed_probes = (covered_probes(SEEDS[0] / 'jacoco.exec')
                   | covered_probes(SEEDS[1] / 'jacoco.exec'))
    seed_families = {family(point(event)) for events in seeds for event in events
                     if event['event'] == 'IO_OBSERVED'
                     and event.get('sessionEligible') and relevant(point(event))}
    agent_meta = json.loads((HERE / 'agent-build.json').read_text())
    state = {
        'schema_version': 3,
        'agent_sha256': agent_meta['agent_sha256'],
        'source_provenance_sha256': hashlib.sha256(
            (HERE / 'source-provenance.json').read_bytes()).hexdigest(),
        'runner_sha256': runner_hashes(),
        'test': TEST_CLASS + '#' + TEST_METHOD,
        'status': 'running',
        'target_actor_map': target_actor_map(seeds[0]),
        'budget': {'max_effective': max_trials, 'max_faults': max_faults,
                   'max_selected_plans': max_selected_plans},
        'seed_traces': [str(directory / 'events.jsonl') for directory in SEEDS],
        'seed_probe_count': len(seed_probes),
        'seed_io_family_count': len(seed_families),
        'covered_probes': sorted(seed_probes),
        'io_families': sorted(seed_families),
        'queue': [], 'seen_sequences': [], 'completed': [], 'active': None,
    }
    for item in points:
        enqueue(state, [item])
    publish(state)
    return state


def effective_count(state: dict, case_id: str) -> int:
    return sum(row['strict_injection']
               and row['target_guard_after_last_fault'][case_id] > 0
               for row in state['completed'])


def minimum_effective(state: dict) -> int:
    return min(effective_count(state, case_id) for case_id in GUARDS)


def extend_for_late_novelty(state: dict) -> bool:
    if state['budget']['max_effective'] != 80 or minimum_effective(state) < 80:
        return False
    valuable = [row for row in state['completed'] if row['strict_injection']
                and all(row['target_guard_after_last_fault'][case_id] > 0
                        for case_id in GUARDS)]
    late = valuable[-8:]
    if len(late) == 8 and any(row['new_production_probes'] > 0
                              or row['new_io_families'] > 0 for row in late):
        state['budget']['max_effective'] = 128
        state['budget']['max_faults'] = 10
        state['extension_reason'] = 'novel production probes or I/O family in last 8 joint-effective trials'
        publish(state)
        return True
    return False


def campaign(max_trials: int, max_faults: int, max_selected_plans: int) -> None:
    from run_healthy import source_provenance
    source_receipt = HERE / 'source-provenance.json'
    if not source_receipt.is_file() or json.loads(source_receipt.read_text()) != source_provenance():
        raise RuntimeError('original source/JAR provenance does not match healthy seeds')
    ROOT.mkdir(exist_ok=True)
    state_path = ROOT / 'state.json'
    if state_path.is_file():
        state = json.loads(state_path.read_text())
        if state['runner_sha256'] != runner_hashes():
            raise RuntimeError('runner changed; refusing checkpoint resume')
        if state['source_provenance_sha256'] != hashlib.sha256(source_receipt.read_bytes()).hexdigest():
            raise RuntimeError('original source/JAR changed; refusing checkpoint resume')
        expected_agent = json.loads((HERE / 'agent-build.json').read_text())['agent_sha256']
        actual_agent = hashlib.sha256(AGENT.read_bytes()).hexdigest()
        if state['agent_sha256'] != expected_agent or actual_agent != expected_agent:
            raise RuntimeError('agent changed; refusing checkpoint resume')
        state['budget']['max_effective'] = max(max_trials, state['budget']['max_effective'])
        state['budget']['max_faults'] = max(max_faults, state['budget']['max_faults'])
        state['budget']['max_selected_plans'] = max(
            max_selected_plans, state['budget']['max_selected_plans'])
        state['status'] = 'running'
        publish(state)
    else:
        state = initialize(max_trials, max_faults, max_selected_plans)
    while state['queue'] and len(state['completed']) < state['budget']['max_selected_plans']:
        if minimum_effective(state) >= state['budget']['max_effective']:
            if not extend_for_late_novelty(state):
                break
        if state['active'] is None:
            state['active'] = select(state)
            state['active']['number'] = len(state['completed']) + 1
            state['active']['attempts'] = 0
            publish(state)
        active = state['active']
        number = active['number']
        trial_dir = ROOT / 'trials' / f'{number:04d}-{active["id"]}'
        trial_dir.mkdir(parents=True, exist_ok=True)
        plan = trial_dir / 'fault.properties'
        if not plan.is_file():
            write_plan(plan, active['sequence'])
        final = None
        # Re-audit any completed attempt on resume. The checkpoint may have
        # been written between its JVM exit and final trial publication.
        for attempt in range(1, 3):
            out = trial_dir / f'attempt-{attempt:02d}'
            if not (out / 'run.json').is_file():
                run_junit(out, agent_path=AGENT, fault_plan=plan)
            active['attempts'] = max(active['attempts'], attempt)
            publish(state)
            previous_probes = set(state['covered_probes'])
            previous_families = set(state['io_families'])
            try:
                result, probes, families, observed = analyze(
                    out, active['sequence'], previous_probes, previous_families,
                    state['target_actor_map'])
            except Exception as failure:
                raise RuntimeError(f'cannot audit trial {number} attempt {attempt}: {out}') from failure
            atomic(out / 'audit.json', result)
            final = (result, probes, families, observed, out)
            if result['strict_injection']:
                break
        assert final is not None
        result, probes, families, observed, out = final
        result['trial_number'] = number
        result['attempts'] = active['attempts']
        result['first_family'] = family(active['sequence'][0])
        result['last_family'] = family(active['sequence'][-1])
        result['fault_sequence'] = active['sequence']
        result['status'] = ('target_exception_candidate' if result['strict_injection']
                            and any(result['exact_target_throw_after_last_fault'].values()) else
                            'checked' if result['target_preserved'] else
                            'lost_target' if result['strict_injection'] else 'unmatched')
        result['elapsed_seconds'] = round(sum(
            json.loads((trial_dir / f'attempt-{attempt:02d}' / 'run.json').read_text())
            ['elapsed_seconds'] for attempt in range(1, active['attempts'] + 1)), 3)
        atomic(trial_dir / 'result.json', result)
        state['completed'].append(result)
        state['active'] = None
        if result['target_preserved']:
            last_applied = max(event['seq'] for event in load_events(out)
                               if event['event'] == 'IO_OBSERVED' and event['applied'])
            mutate(state, active['sequence'], observed, last_applied,
                   result['new_production_probes'] + result['new_io_families'],
                   state['budget']['max_faults'])
            state['covered_probes'] = sorted(set(state['covered_probes']) | probes)
            state['io_families'] = sorted(set(state['io_families']) | families)
        if result['status'] == 'target_exception_candidate':
            state['status'] = 'candidate_target_exception'
            publish(state)
            return
        publish(state)
    state['status'] = ('budget_complete'
                       if minimum_effective(state) >= state['budget']['max_effective']
                       else 'queue_exhausted' if not state['queue']
                       else 'selected_plan_cap')
    publish(state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-effective', type=int, default=80)
    parser.add_argument('--max-faults', type=int, default=8)
    parser.add_argument('--max-selected-plans', type=int, default=256)
    args = parser.parse_args()
    if not (1 <= args.max_effective <= 1000 and 1 <= args.max_faults <= 10
            and args.max_selected_plans >= args.max_effective):
        raise SystemExit('invalid budget')
    ROOT.mkdir(exist_ok=True)
    with (ROOT / '.single-worker.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        campaign(args.max_effective, args.max_faults, args.max_selected_plans)
