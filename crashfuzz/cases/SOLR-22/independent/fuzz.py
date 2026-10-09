#!/usr/bin/env python3
"""Resumable CrashFuzz-style Directory I/O and JaCoCo probe campaign."""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import random
import time

from build import HERE
from coverage import branch_totals, covered_probes
from run import run as run_junit


ROOT = HERE / 'campaign'
SEEDS = (HERE / 'healthy-7', HERE / 'healthy-8')
METHOD_HINTS = ('org.apache.solr.handler.', 'org.apache.solr.core.SolrCore.',
                'org.apache.lucene.index.IndexFileDeleter.',
                'org.apache.lucene.index.IndexWriter.',
                'org.apache.lucene.index.SegmentInfos.')


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def load_events(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / 'events.jsonl').open()
            if line.strip()]


def point(event: dict) -> dict:
    return {name: event[name] for name in
            ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal')}


def point_id(item: dict) -> str:
    return json.dumps(item, sort_keys=True, separators=(',', ':'))


def family(item: dict) -> str:
    return '|'.join((item['marker'], item['siteId'], item['sourceKey']))


def relevant(item: dict) -> bool:
    return (not item['sourceKey'].startswith('UNRESOLVED')
            and any(item['siteId'].startswith(prefix) for prefix in METHOD_HINTS))


def target_sources(events: list[dict]) -> set[str]:
    return {event['sourceKey'] for event in events
            if event['event'] == 'TARGET_CHECK'
            and not event['sourceKey'].startswith('UNRESOLVED')}


def is_target_core(item: dict, sources: set[str]) -> bool:
    return any(item['sourceKey'].startswith(source + '/') for source in sources)


def seed_candidates(events_a: list[dict], events_b: list[dict]) -> tuple[list[dict], set[str]]:
    exact_b = {point_id(point(e)) for e in events_b
               if e['event'] == 'FAULT_POINT_OBSERVED' and relevant(point(e))}
    sources = target_sources(events_a) | target_sources(events_b)
    groups: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for event in events_a:
        if event['event'] != 'FAULT_POINT_OBSERVED':
            continue
        item = point(event)
        identity = point_id(item)
        if not relevant(item) or identity not in exact_b or identity in seen:
            continue
        seen.add(identity)
        groups[family(item)].append(item)
    chosen: list[dict] = []
    for items in groups.values():
        # One early, one middle, and one late occurrence per stable I/O family.
        for index in sorted({0, len(items) // 2, len(items) - 1}):
            chosen.append(items[index])
    chosen.sort(key=lambda item: (not is_target_core(item, sources),
                                  item['marker'], item['siteId'], item['sourceKey'],
                                  item['hitOrdinal']))
    return chosen, sources


def write_plan(path: Path, sequence: list[dict]) -> None:
    rows = ['count=' + str(len(sequence))]
    for index, item in enumerate(sequence, 1):
        for key in ('siteId', 'sourceKey', 'resource', 'hitOrdinal'):
            rows.append('step.' + str(index) + '.' + key + '=' + str(item[key]))
    path.write_text('\n'.join(rows) + '\n')


def analyze(directory: Path, sequence: list[dict], prior_probes: set[str],
            prior_families: set[str], source_roots: set[str],
            calculate_branches: bool) -> tuple[dict, set[str], set[str], list[dict]]:
    events = load_events(directory)
    applied = [e for e in events if e['event'] == 'FAULT_POINT_OBSERVED' and e['applied']]
    strict = len(applied) == len(sequence) and all(
        point_id(point(event)) == point_id(item)
        and event.get('detail') == 'step=' + str(step)
        for step, (event, item) in enumerate(zip(applied, sequence), 1))
    last_fault = applied[-1]['seq'] if applied else -1
    target_after = [e for e in events if e['event'] == 'TARGET_CHECK'
                    and e['seq'] > last_fault] if strict else []
    throws_after = [e for e in events if e['event'] == 'TARGET_THROW'
                    and e['seq'] > last_fault] if strict else []
    same_core_after = [e for e in target_after if any(
        item['sourceKey'].startswith(e['sourceKey'] + '/') for item in sequence)]
    active_windows: set[tuple[int, str]] = set()
    io_in_window = applied_in_window = check_in_window = 0
    for event in events:
        key = (event['threadId'], event.get('policyId'))
        if event['event'] == 'ONCOMMIT_WINDOW_START':
            active_windows.add(key)
        elif event['event'] == 'ONCOMMIT_WINDOW_END':
            active_windows.discard(key)
        elif active_windows:
            if event['event'] == 'FAULT_POINT_OBSERVED':
                io_in_window += 1
                applied_in_window += int(event['applied'])
            elif event['event'] == 'TARGET_CHECK':
                check_in_window += 1
    probes = covered_probes(directory / 'jacoco.exec')
    observed = [e for e in events if e['event'] == 'FAULT_POINT_OBSERVED'
                and relevant(point(e))]
    families = {family(point(e)) for e in observed}
    metadata = json.loads((directory / 'run.json').read_text())
    result = {
        'junit_exit': metadata['exit_code'],
        'elapsed_seconds': metadata['elapsed_seconds'],
        'strict_injection': strict,
        'planned_faults': len(sequence),
        'applied_faults': len(applied),
        'target_check_count': sum(e['event'] == 'TARGET_CHECK' for e in events),
        'target_check_after_last_fault': len(target_after),
        'target_check_same_faulted_core_after_last_fault': len(same_core_after),
        'exact_target_exception_after_last_fault': len(throws_after),
        'target_exception_count': sum(e['event'] == 'TARGET_THROW' for e in events),
        'directory_io_count': sum(e['event'] == 'FAULT_POINT_OBSERVED' for e in events),
        'directory_io_during_onCommit_window': io_in_window,
        'applied_faults_during_onCommit_window': applied_in_window,
        'target_checks_during_onCommit_window': check_in_window,
        'production_probes_covered': len(probes),
        'new_production_probes': len(probes - prior_probes),
        'new_io_families': len(families - prior_families),
        'source_roots': sorted(source_roots),
        'trace': str(directory / 'events.jsonl'),
        'jacoco': str(directory / 'jacoco.exec'),
    }
    if calculate_branches:
        result.update(branch_totals(directory / 'jacoco.exec'))
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
    rng = random.Random(220000 + round_number)
    queue = state['queue']
    prefer_multiple = round_number >= 16 and round_number % 3 != 0
    choices = [entry for entry in queue if len(entry['sequence']) > 1] if prefer_multiple else []
    if not choices:
        choices = [entry for entry in queue if len(entry['sequence']) == 1]
    if not choices:
        choices = queue
    first_counts = Counter(record['first_family'] for record in state['completed'])
    last_counts = Counter(record['last_family'] for record in state['completed'])
    sources = set(state['target_sources'])
    scored = []
    for entry in choices:
        first = family(entry['sequence'][0]); last = family(entry['sequence'][-1])
        score = (80 / (1 + first_counts[first]) + 30 / (1 + last_counts[last])
                 + (30 if is_target_core(entry['sequence'][-1], sources) else 0)
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
    by_family: dict[str, dict] = {}
    sources = set(state['target_sources'])
    for event in observed:
        if event['seq'] <= applied_seq:
            continue
        item = point(event)
        if point_id(item) in used:
            continue
        key = family(item)
        if key not in by_family or is_target_core(item, sources):
            by_family[key] = item
    ranked = sorted(by_family.values(), key=lambda item: (
        not is_target_core(item, sources),
        -int('IndexFileDeleter' in item['siteId'] or 'ReplicationHandler' in item['siteId']),
        item['siteId'], item['sourceKey']))
    for child in ranked[:12]:
        enqueue(state, parent + [child], parent_gain=gain)


def publish(state: dict) -> None:
    completed = state['completed']
    summary = {
        'case_id': 'SOLR-22', 'methodology': 'coverage_io_independent_asm_jacoco',
        'status': state['status'], 'fault_trials': len(completed),
        'total_attempts': sum(row['attempts'] for row in completed),
        'strict_injections': sum(row['strict_injection'] for row in completed),
        'post_fault_target_reach_trials': sum(row['strict_injection']
            and row['target_check_after_last_fault'] > 0 for row in completed),
        'same_faulted_core_post_target_trials': sum(row['strict_injection']
            and row['target_check_same_faulted_core_after_last_fault'] > 0
            for row in completed),
        'target_exception_after_fault_trials': sum(row['strict_injection']
            and row['exact_target_exception_after_last_fault'] > 0 for row in completed),
        'production_probe_gain': len(state['covered_probes']) - state['seed_probe_count'],
        'io_family_gain': len(state['io_families']) - state['seed_io_family_count'],
        'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in completed), 3),
        'first_fault_families': dict(Counter(row['first_family'] for row in completed)),
        'applied_faults_in_onCommit_window': sum(row['applied_faults_during_onCommit_window']
            for row in completed),
        'target_checks_in_onCommit_window': sum(row['target_checks_during_onCommit_window']
            for row in completed),
        'latest': completed[-1] if completed else None,
        'budget': state['budget'],
    }
    atomic(ROOT / 'progress.json', summary)
    atomic(ROOT / 'state.json', state)


def initialize(max_trials: int, max_faults: int) -> dict:
    events_a, events_b = [load_events(path) for path in SEEDS]
    if any(json.loads((path / 'run.json').read_text())['exit_code'] != 0 for path in SEEDS):
        raise RuntimeError('both original healthy JUnit seeds must pass')
    if any(not target_sources(events) for events in (events_a, events_b)):
        raise RuntimeError('healthy target source is unresolved')
    points, sources = seed_candidates(events_a, events_b)
    if not points:
        raise RuntimeError('no stable Directory selector across healthy seeds')
    seed_probes = covered_probes(SEEDS[0] / 'jacoco.exec') | covered_probes(SEEDS[1] / 'jacoco.exec')
    seed_families = {family(point(e)) for events in (events_a, events_b)
                     for e in events if e['event'] == 'FAULT_POINT_OBSERVED'
                     and relevant(point(e))}
    build = json.loads((HERE / 'build.json').read_text())
    state = {
        'schema_version': 1,
        'agent_sha256': build['agent_sha256'],
        'test': 'org.apache.solr.cloud.TestPullReplica#testAddDocs',
        'status': 'running', 'budget': {'max_trials': max_trials, 'max_faults': max_faults},
        'target_sources': sorted(sources),
        'seed_traces': [str(path / 'events.jsonl') for path in SEEDS],
        'seed_probe_count': len(seed_probes),
        'seed_io_family_count': len(seed_families),
        'covered_probes': sorted(seed_probes),
        'io_families': sorted(seed_families),
        'queue': [], 'seen_sequences': [], 'completed': [], 'active': None,
    }
    for item in points:
        enqueue(state, [item])
    calibration = HERE / 'calibration-02'
    if (calibration / 'run.json').is_file():
        calibrated_events = load_events(calibration)
        applied = [event for event in calibrated_events
                   if event['event'] == 'FAULT_POINT_OBSERVED' and event['applied']]
        if len(applied) != 1:
            raise RuntimeError('calibration-02 must apply exactly one fault')
        sequence = [point(applied[0])]
        report, probes, families, observed = analyze(
            calibration, sequence, seed_probes, seed_families, sources, False)
        if not report['strict_injection'] or report['target_check_after_last_fault'] == 0:
            raise RuntimeError('calibration-02 lacks strict post-fault target check')
        report.update({'trial_number': 1, 'attempts': 1,
                       'first_family': family(sequence[0]),
                       'last_family': family(sequence[0]),
                       'fault_sequence': sequence, 'status': 'checked',
                       'preflight_calibration': True})
        state['completed'].append(report)
        state['covered_probes'] = sorted(seed_probes | probes)
        state['io_families'] = sorted(seed_families | families)
        digest = hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:20]
        state['queue'] = [entry for entry in state['queue'] if entry['id'] != digest]
        if digest not in state['seen_sequences']:
            state['seen_sequences'].append(digest)
        mutate(state, sequence, observed, applied[0]['seq'],
               report['new_production_probes'] + report['new_io_families'],
               max_faults)
    publish(state)
    return state


def campaign(max_trials: int, max_faults: int) -> None:
    ROOT.mkdir(exist_ok=True)
    state_path = ROOT / 'state.json'
    if state_path.is_file():
        state = json.loads(state_path.read_text())
        build = json.loads((HERE / 'build.json').read_text())
        if state['agent_sha256'] != build['agent_sha256']:
            raise RuntimeError('agent changed; refusing to resume old checkpoint')
        if max_trials < len(state['completed']) or max_faults < state['budget']['max_faults']:
            raise RuntimeError('budget cannot shrink')
        state['budget'] = {'max_trials': max_trials, 'max_faults': max_faults}
        state['status'] = 'running'
        publish(state)
    else:
        state = initialize(max_trials, max_faults)
    while len(state['completed']) < max_trials and state['queue']:
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
        final_result = None
        for attempt in range(active['attempts'] + 1, 3):
            out = trial_dir / f'attempt-{attempt:02d}'
            if not (out / 'run.json').is_file():
                run_junit(out, plan)
            active['attempts'] = attempt
            publish(state)
            previous_probes = set(state['covered_probes'])
            previous_families = set(state['io_families'])
            try:
                result, probes, families, observed = analyze(
                    out, active['sequence'], previous_probes, previous_families,
                    set(state['target_sources']), calculate_branches=number % 10 == 0)
            except Exception as failure:
                raise RuntimeError(f'cannot audit trial {number} attempt {attempt}: {out}') from failure
            atomic(out / 'audit.json', result)
            final_result = (result, probes, families, observed, out)
            if result['strict_injection']:
                break
        assert final_result is not None
        result, probes, families, observed, out = final_result
        result['trial_number'] = number
        result['attempts'] = active['attempts']
        result['first_family'] = family(active['sequence'][0])
        result['last_family'] = family(active['sequence'][-1])
        result['fault_sequence'] = active['sequence']
        result['status'] = ('target_exception_candidate' if result['strict_injection']
            and result['exact_target_exception_after_last_fault'] else
            'checked' if result['strict_injection']
            and result['target_check_after_last_fault'] else
            'lost_target' if result['strict_injection'] else 'unmatched')
        result['elapsed_seconds'] = round(sum(
            json.loads((trial_dir / f'attempt-{attempt:02d}' / 'run.json').read_text())
            ['elapsed_seconds'] for attempt in range(1, active['attempts'] + 1)), 3)
        atomic(trial_dir / 'result.json', result)
        if result['strict_injection'] and result['target_check_after_last_fault']:
            applied_seq = max(e['seq'] for e in load_events(out)
                              if e['event'] == 'FAULT_POINT_OBSERVED' and e['applied'])
            mutate(state, active['sequence'], observed, applied_seq,
                   result['new_production_probes'] + result['new_io_families'],
                   max_faults)
            state['covered_probes'] = sorted(set(state['covered_probes']) | probes)
            state['io_families'] = sorted(set(state['io_families']) | families)
        state['completed'].append(result)
        state['active'] = None
        if result['status'] == 'target_exception_candidate':
            state['status'] = 'candidate_target_exception'
            publish(state)
            return
        publish(state)
    state['status'] = 'budget_complete' if len(state['completed']) >= max_trials else 'queue_exhausted'
    publish(state)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-trials', type=int, default=80)
    parser.add_argument('--max-faults', type=int, default=8)
    args = parser.parse_args()
    if not (1 <= args.max_trials <= 1000 and 1 <= args.max_faults <= 10):
        raise SystemExit('invalid budget')
    campaign(args.max_trials, args.max_faults)


if __name__ == '__main__':
    main()
