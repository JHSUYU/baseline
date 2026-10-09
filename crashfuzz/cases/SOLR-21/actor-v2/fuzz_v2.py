#!/usr/bin/env python3
"""Resumable actor-aware I/O and coverage fuzzing of the original Solr JUnit."""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
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
from run_v2 import run as run_junit


ROOT = HERE / 'campaign'
AGENT = HERE / 'solrreload-actor-v2-agent.jar'
SEEDS = (HERE / 'healthy-01', HERE / 'healthy-02')
TARGET = 'SOLR/RELOAD/c8n_1x1/shard1/core_node2'
CORE = 'c8n_1x1_shard1_replica_n1'
COLLECTION = 'SOLR/COLLECTION/c8n_1x1'
RELOAD = 'SOLR/RELOAD_CORE/' + CORE
FILE = 'SOLR/CORE_PROPERTIES/' + CORE
COLLECTION_PATH = '/collections/c8n_1x1'
GUARD = 'SOLR21:REPLICA_NONNULL_GUARD'
THROW = 'SOLR21:REPLICA_NULL_ASSERTION'
LOCKED_FILES = ('fuzz_v2.py', 'calibrate.py', 'run_healthy.py',
                'build_agent.py', 'build_junit.py', 'run_v2.py')


def runner_hashes() -> dict[str, str]:
    paths = [HERE / name for name in LOCKED_FILES]
    paths.extend((PARENT / 'coverage.py', PARENT / 'build.py',
                  HERE / 'junit-build.json', AGENT))
    return {str(path.relative_to(HERE.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def load_events(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / 'events.jsonl').open()
            if line.strip()]


def validate_actor_trace(events: list[dict]) -> dict:
    bindings: dict[int, tuple[str, str]] = {}
    for event in events:
        if event['event'] != 'CLIENT_BIND':
            continue
        match = re.search(r'clientIdentity=(\d+)', event['detail'])
        if match is None:
            raise RuntimeError('CLIENT_BIND lacks object identity')
        identity = int(match.group(1))
        value = (event['actorKey'], event['physicalNode'])
        if identity in bindings and bindings[identity] != value:
            raise RuntimeError('SolrZkClient object mapped to two nodes')
        bindings[identity] = value
    if not any(actor == 'JETTY/node1' for actor, _ in bindings.values()):
        raise RuntimeError('original test Jetty has no bound SolrZkClient')
    bound_io = 0
    unbound_io = 0
    for event in events:
        if event['event'] not in ('IO_OBSERVED', 'TARGET_CHECK', 'TARGET_THROW'):
            continue
        match = re.search(r'clientIdentity=(\d+)', event['detail'])
        if event['actorKey'] == 'JETTY/node1':
            if match is None or bindings.get(int(match.group(1))) != (
                    event['actorKey'], event['physicalNode']):
                raise RuntimeError('bound I/O or target contradicts raw client registration')
            if event['event'] == 'IO_OBSERVED':
                bound_io += 1
        elif event['event'] == 'IO_OBSERVED':
            if event['applied']:
                raise RuntimeError('unbound I/O consumed a fault')
            unbound_io += 1
    return {'bindings': len(bindings), 'bound_io': bound_io,
            'unbound_io_excluded': unbound_io}


def point(event: dict) -> dict:
    return {name: event[name] for name in
            ('marker', 'siteId', 'sourceKey', 'actorKey', 'resource', 'hitOrdinal')}


def point_id(item: dict) -> str:
    return json.dumps(item, sort_keys=True, separators=(',', ':'))


def family(item: dict) -> str:
    resource = re.sub(r'(/leader_elect/[^/]+/election/)[^/]+$',
                      r'\1{ephemeral-election-node}', item['resource'])
    return '|'.join((item['marker'], item['siteId'], item['sourceKey'],
                     item['actorKey'], resource))


def unstable_resource(item: dict) -> bool:
    return bool(re.search(r'/leader_elect/[^/]+/election/[^/]+$',
                          item['resource']))


def relevant(item: dict) -> bool:
    source = item['sourceKey']
    resource = item['resource']
    belongs = ((source == FILE and resource == CORE + '/core.properties')
               or source == RELOAD
               or (source == COLLECTION and resource.startswith(COLLECTION_PATH)))
    return (belongs and item['actorKey'] == 'JETTY/node1'
            and not source.startswith('UNRESOLVED:')
            and not item['siteId'].startswith('UNRESOLVED:'))


def guard_events(events: list[dict]) -> list[dict]:
    return [event for event in events if event['event'] == 'TARGET_CHECK'
            and event['marker'] == GUARD and event['sourceKey'] == TARGET
            and event['resource'] == CORE and event['actorKey'] == 'JETTY/node1']


def seed_candidates(events_a: list[dict], events_b: list[dict]) -> list[dict]:
    for events in (events_a, events_b):
        guards = guard_events(events)
        if len(guards) != 1:
            raise RuntimeError('healthy original test must reach selected guard exactly once')
        if any(event['event'] == 'TARGET_THROW' and event['marker'] == THROW
               and event['sourceKey'] == TARGET and event['resource'] == CORE
               and event['actorKey'] == 'JETTY/node1' for event in events):
            raise RuntimeError('healthy original test already throws at selected target')
    first_guard = guard_events(events_a)[0]['seq']
    second_guard = guard_events(events_b)[0]['seq']
    exact_b = {point_id(point(event)) for event in events_b
               if event['event'] == 'IO_OBSERVED' and event['seq'] < second_guard
               and relevant(point(event))}
    groups: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for event in events_a:
        if event['event'] != 'IO_OBSERVED' or event['seq'] >= first_guard:
            continue
        item = point(event)
        identity = point_id(item)
        if (not relevant(item) or unstable_resource(item)
                or identity not in exact_b or identity in seen):
            continue
        seen.add(identity)
        groups[family(item)].append(item)
    chosen: list[dict] = []
    for items in groups.values():
        for index in sorted({0, len(items) // 2, len(items) - 1}):
            chosen.append(items[index])
    chosen.sort(key=lambda item: (item['sourceKey'] not in (RELOAD, FILE),
                                  item['marker'], item['siteId'], item['resource'],
                                  item['hitOrdinal']))
    return chosen


def write_plan(path: Path, sequence: list[dict]) -> None:
    lines = ['count=' + str(len(sequence))]
    for number, item in enumerate(sequence, 1):
        for field in ('marker', 'siteId', 'sourceKey', 'actorKey', 'resource', 'hitOrdinal'):
            lines.append(f'step.{number}.{field}={item[field]}')
    path.write_text('\n'.join(lines) + '\n')


def junit_gate(log: str) -> tuple[int, int, int] | None:
    match = re.search(r'SOLR_RELOAD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)', log)
    return tuple(map(int, match.groups())) if match else None


def analyze(directory: Path, sequence: list[dict], prior_probes: set[str],
            prior_families: set[str]) -> tuple[dict, set[str], set[str], list[dict]]:
    events = load_events(directory)
    actor_audit = validate_actor_trace(events)
    applied = [event for event in events if event['event'] == 'IO_OBSERVED'
               and event['applied']]
    strict = len(applied) == len(sequence) and all(
        point_id(point(event)) == point_id(item)
        for event, item in zip(applied, sequence))
    summaries = [event for event in events if event['event'] == 'SUMMARY']
    strict = strict and len(summaries) == 1 and summaries[0]['detail'] == \
        f'applied={len(sequence)}/{len(sequence)}'
    last_fault = applied[-1]['seq'] if applied else -1
    guards = guard_events(events)
    throws = [event for event in events if event['event'] == 'TARGET_THROW'
              and event['marker'] == THROW and event['sourceKey'] == TARGET
              and event['resource'] == CORE and event['actorKey'] == 'JETTY/node1'
              and 'java.lang.AssertionError' in event['detail']]
    post_guard = sum(event['seq'] > last_fault for event in guards) if strict else 0
    post_throw = sum(event['seq'] > last_fault for event in throws) if strict else 0
    metadata = json.loads((directory / 'run.json').read_text())
    gate = junit_gate((directory / 'console.log').read_text())
    probes = (covered_probes(directory / 'jacoco.exec')
              if (directory / 'jacoco.exec').is_file()
              and (directory / 'jacoco.exec').stat().st_size else set())
    observed = [event for event in events if event['event'] == 'IO_OBSERVED'
                and relevant(point(event))]
    families = {family(point(event)) for event in observed}
    result = {
        'junit_exit': metadata['exit_code'],
        'junit_gate': gate,
        'elapsed_seconds': metadata['elapsed_seconds'],
        'strict_injection': strict,
        'planned_faults': len(sequence),
        'applied_faults': len(applied),
        'target_guard_count': len(guards),
        'target_guard_after_last_fault': post_guard,
        'exact_target_throw_count': len(throws),
        'exact_target_throw_after_last_fault': post_throw,
        'target_preserved': strict and post_guard > 0,
        'actor_audit': actor_audit,
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
    # Rotate through the actual target-context ZooKeeper and core-file I/O
    # families. The first ten frozen pilot plans used the earlier schedule;
    # subsequent choices remain deterministic from the saved checkpoint.
    preferred_source = (RELOAD, FILE, COLLECTION)[(round_number - 1) % 3]
    source_choices = [entry for entry in choices
                      if entry['sequence'][0]['sourceKey'] == preferred_source]
    if source_choices:
        choices = source_choices
    first_counts = Counter(row['first_family'] for row in state['completed'])
    last_counts = Counter(row['last_family'] for row in state['completed'])
    scored = []
    for entry in choices:
        first = family(entry['sequence'][0])
        last = family(entry['sequence'][-1])
        score = (80 / (1 + first_counts[first]) + 30 / (1 + last_counts[last])
                 + (30 if entry['sequence'][-1]['sourceKey'] in (RELOAD, FILE) else 0)
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
    guards = guard_events(load_events(Path(state['completed'][-1]['trace']).parent))
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
        if group not in by_family or item['sourceKey'] in (RELOAD, FILE):
            by_family[group] = item
    ranked = sorted(by_family.values(), key=lambda item: (
        item['sourceKey'] not in (RELOAD, FILE), item['siteId'], item['resource']))
    for child in ranked[:12]:
        enqueue(state, parent + [child], parent_gain=gain)


def publish(state: dict) -> None:
    completed = state['completed']
    progress = {
        'case_id': 'SOLR-21',
        'methodology': 'actor_aware_coverage_io_original_cluster_junit_v2',
        'status': state['status'],
        'budget': state['budget'],
        'selected_plans': len(completed),
        'effective_trials': effective_count(state),
        'total_attempts': sum(row['attempts'] for row in completed),
        'strict_injections': sum(row['strict_injection'] for row in completed),
        'post_fault_target_reach_trials': sum(
            row['strict_injection'] and row['target_guard_after_last_fault'] > 0
            for row in completed),
        'target_exception_after_fault_trials': sum(
            row['strict_injection'] and row['exact_target_throw_after_last_fault'] > 0
            for row in completed),
        'target_preserved_trials': sum(row['target_preserved'] for row in completed),
        'production_probe_gain': len(state['covered_probes']) - state['seed_probe_count'],
        'io_family_gain': len(state['io_families']) - state['seed_io_family_count'],
        'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in completed), 3),
        'first_fault_families': dict(Counter(row['first_family'] for row in completed)),
        'latest': completed[-1] if completed else None,
    }
    atomic(ROOT / 'state.json', state)
    atomic(ROOT / 'progress.json', progress)


def initialize(max_trials: int, max_faults: int, max_selected_plans: int) -> dict:
    calibration_path = HERE / 'calibration-receipt.json'
    if not calibration_path.is_file():
        raise RuntimeError('two-run actor calibration receipt required')
    calibration = json.loads(calibration_path.read_text())
    if calibration['agent_sha256'] != hashlib.sha256(AGENT.read_bytes()).hexdigest():
        raise RuntimeError('calibration used different actor-aware agent')
    if len(calibration['healthy_runs']) != 2 or any(
            hashlib.sha256((directory / 'events.jsonl').read_bytes()).hexdigest()
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
                     if event['event'] == 'IO_OBSERVED' and relevant(point(event))}
    agent_meta = json.loads((HERE / 'agent-build.json').read_text())
    state = {
        'schema_version': 2,
        'agent_sha256': agent_meta['agent_sha256'],
        'runner_sha256': runner_hashes(),
        'test': TEST_CLASS + '#' + TEST_METHOD,
        'status': 'running',
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


def effective_count(state: dict) -> int:
    return sum(row['strict_injection'] and row['target_guard_after_last_fault'] > 0
               for row in state['completed'])


def extend_for_late_novelty(state: dict) -> bool:
    if state['budget']['max_effective'] != 80 or effective_count(state) < 80:
        return False
    valuable = [row for row in state['completed'] if row['strict_injection']
                and row['target_guard_after_last_fault'] > 0]
    late = valuable[-8:]
    if len(late) == 8 and any(row['new_production_probes'] > 0
                              or row['new_io_families'] > 0 for row in late):
        state['budget']['max_effective'] = 128
        state['budget']['max_faults'] = 10
        state['extension_reason'] = 'last 8 effective trials contained new production probes or I/O family'
        publish(state)
        return True
    return False


def campaign(max_trials: int, max_faults: int, max_selected_plans: int) -> None:
    ROOT.mkdir(exist_ok=True)
    state_path = ROOT / 'state.json'
    if state_path.is_file():
        state = json.loads(state_path.read_text())
        if state['runner_sha256'] != runner_hashes():
            raise RuntimeError('runner changed; refusing checkpoint resume')
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
        if effective_count(state) >= state['budget']['max_effective']:
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
                    out, active['sequence'], previous_probes, previous_families)
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
                            and result['exact_target_throw_after_last_fault'] > 0 else
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
                       if effective_count(state) >= state['budget']['max_effective']
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
    campaign(args.max_effective, args.max_faults, args.max_selected_plans)
