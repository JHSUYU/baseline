#!/usr/bin/env python3
"""Checkpointed coverage/I-O guided parent-forward HTTP fault campaign."""

from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import random
import sys
import time


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
sys.path.insert(0, str(PARENT))
from coverage import covered_probes  # noqa: E402
from fuzz import junit_gate, load_events, point, point_id  # noqa: E402
from run import run as run_junit  # noqa: E402


AGENT = HERE / 'solrsubshard-rpc-agent.jar'
ROOT = HERE / 'campaign'
SEEDS = (HERE / 'healthy-01', HERE / 'healthy-02')
MARKERS = frozenset(('FAULT:HTTP:parentForwardAdd',
                     'FAULT:HTTP:parentForwardDeleteById'))
SOURCE_PREFIX = 'SOLR/SUBSHARD/collection1/shard1_'
WOVEN_COVERAGE = ':org/apache/solr/update/SolrCmdDistributor:'
CHECKS = {'SOLR-36': ('SOLR36:ACTIVE_SUBSHARD_GUARD',
                      'SOLR36:ACTIVE_SUBSHARD_THROW'),
          'SOLR-37': ('SOLR37:CHILD_RANGE_SUBSET_GUARD',
                      'SOLR37:CHILD_RANGE_THROW')}


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locks() -> dict[str, str]:
    return {str(path.relative_to(PARENT)): sha(path)
            for path in (AGENT, HERE / 'fuzz_rpc.py', PARENT / 'run.py',
                         PARENT / 'coverage.py')}


def production_probes(directory: Path) -> set[str]:
    executable = directory / 'jacoco.exec'
    if not executable.is_file() or executable.stat().st_size == 0:
        return set()
    return {probe for probe in covered_probes(executable)
            if WOVEN_COVERAGE not in probe}


def rpc_events(directory: Path) -> list[dict]:
    return [event for event in load_events(directory)
            if event['event'] == 'IO_OBSERVED'
            and event['marker'] in MARKERS
            and event['sourceKey'].startswith(SOURCE_PREFIX)]


def entry_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:20]


def enqueue(state: dict, sequence: list[dict], parent_gain: int = 0) -> None:
    digest = entry_id(sequence)
    if digest in state['seen_sequences']:
        return
    if len(sequence) > state['budget']['max_faults']:
        return
    state['seen_sequences'].append(digest)
    state['queue'].append({'id': digest, 'sequence': sequence,
                           'parent_gain': parent_gain,
                           'created_after': len(state['completed'])})


def step(selected: dict, mode: str, delay_ms: int = 0) -> dict:
    return {'point': selected, 'fault_mode': mode, 'delay_ms': delay_ms}


def initialize(max_trials: int, max_faults: int) -> dict:
    if max_trials < 1 or max_faults < 1 or max_faults > 10:
        raise ValueError('invalid budget')
    records = [rpc_events(directory) for directory in SEEDS]
    if any(not entries for entries in records):
        raise RuntimeError('healthy original JUnit did not observe parent HTTP send')
    intersection = {point_id(point(event)) for event in records[0]} & {
        point_id(point(event)) for event in records[1]}
    by_family: dict[tuple[str, str], list[dict]] = {}
    for event in records[0]:
        selected = point(event)
        if point_id(selected) in intersection:
            by_family.setdefault((selected['sourceKey'], selected['marker']),
                                 []).append(selected)
    state = {
        'status': 'running',
        'budget': {'max_trials': max_trials, 'max_faults': max_faults},
        'locks': locks(),
        'healthy_trace_sha256': {directory.name: sha(directory / 'events.jsonl')
                                 for directory in SEEDS},
        'queue': [], 'seen_sequences': [], 'completed': [], 'active': None,
        'covered_probes': sorted(set().union(
            *(production_probes(directory) for directory in SEEDS))),
        'observed_rpc_selectors': sorted(set().union(
            *({point_id(point(event)) for event in entries}
              for entries in records))),
    }
    for family, entries in sorted(by_family.items()):
        unique = {point_id(item): item for item in entries}
        ordered = sorted(unique.values(), key=lambda item: item['hitOrdinal'])
        count = len(ordered)
        indices = {0, 1, 2, count // 4, count // 2, (3 * count) // 4,
                   count - 12, count - 8, count - 5, count - 3,
                   count - 2, count - 1}
        for index in sorted(index for index in indices if 0 <= index < count):
            selected = ordered[index]
            for delay in (5000, 15000, 30000):
                enqueue(state, [step(selected, 'DELAY', delay)])
            enqueue(state, [step(selected, 'TIMEOUT')])
    if not state['queue']:
        raise RuntimeError('no stable exact parent-forward HTTP selector')
    atomic(ROOT / 'state.json', state)
    return state


def choose(state: dict) -> dict:
    rows = state['completed']
    source_counts = Counter(row['last_fault_source'] for row in rows)
    marker_counts = Counter(row['last_fault_marker'] for row in rows)
    mode_counts = Counter(row['last_fault_mode'] for row in rows)
    point_counts = Counter(row['last_fault_point_id'] for row in rows)
    queue = state['queue']
    available_markers = {item['sequence'][-1]['point']['marker']
                         for item in queue}
    smallest_family = min(marker_counts[marker]
                          for marker in available_markers)
    candidates = [item for item in queue
                  if marker_counts[item['sequence'][-1]['point']['marker']]
                  == smallest_family]
    max_ordinal = max(item['sequence'][-1]['point']['hitOrdinal']
                      for item in candidates)
    ranked = []
    for item in candidates:
        last = item['sequence'][-1]
        selected = last['point']
        score = (35.0 * selected['hitOrdinal'] / max(1, max_ordinal)
                 + 30.0 / (1 + source_counts[selected['sourceKey']])
                 + 30.0 / (1 + marker_counts[selected['marker']])
                 + 18.0 / (1 + mode_counts[last['fault_mode']])
                 + 12.0 / (1 + point_counts[point_id(selected)])
                 + min(25.0, item['parent_gain'] / 4.0)
                 + min(12.0, (len(rows) - item['created_after']) / 3.0)
                 + (7.0 if len(item['sequence']) > 1 else 0.0))
        ranked.append((score, item))
    ranked.sort(key=lambda row: (-row[0], row[1]['id']))
    top = ranked[:min(10, len(ranked))]
    rng = random.Random(360000 + len(rows) + 1)
    selected = rng.choices([row[1] for row in top],
                           weights=[row[0] for row in top], k=1)[0]
    queue.remove(selected)
    return selected


def write_plan(path: Path, sequence: list[dict]) -> None:
    lines = [f'count={len(sequence)}']
    for number, item in enumerate(sequence, 1):
        prefix = f'step.{number}.'
        for field in ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal'):
            lines.append(f'{prefix}{field}={item["point"][field]}')
        lines.append(f'{prefix}faultMode={item["fault_mode"]}')
        if item['fault_mode'] == 'DELAY':
            lines.append(f'{prefix}delayMs={item["delay_ms"]}')
    path.write_text('\n'.join(lines) + '\n')


def analyze(directory: Path, sequence: list[dict], state: dict) -> tuple[dict, set[str], set[str]]:
    events = load_events(directory)
    observed = [event for event in events if event['event'] == 'IO_OBSERVED'
                and event['marker'] in MARKERS
                and event['sourceKey'].startswith(SOURCE_PREFIX)]
    applied = [event for event in observed if event['applied']]
    summaries = [event for event in events if event['event'] == 'SUMMARY']
    strict = (len(applied) == len(sequence)
              and all(point(event) == item['point']
                      for event, item in zip(applied, sequence))
              and len(summaries) == 1
              and summaries[0]['detail'] == f'applied={len(sequence)}/{len(sequence)}')
    last_fault_seq = applied[-1]['seq'] if applied else -1
    last_source = sequence[-1]['point']['sourceKey']
    post_guards = {}
    post_throws = {}
    operands = {}
    for case_id, (guard_marker, throw_marker) in CHECKS.items():
        guard = [event for event in events
                 if event['event'] == 'TARGET_CHECK'
                 and event['marker'] == guard_marker
                 and event['sourceKey'] == last_source
                 and event['seq'] > last_fault_seq]
        thrown = [event for event in events
                  if event['event'] == 'TARGET_THROW'
                  and event['marker'] == throw_marker
                  and event['sourceKey'] == last_source
                  and event['seq'] > last_fault_seq]
        post_guards[case_id] = len(guard) if strict else 0
        post_throws[case_id] = len(thrown) if strict else 0
        operands[case_id] = dict(Counter(event['detail'] for event in guard))
    probes = production_probes(directory)
    selectors = {point_id(point(event)) for event in observed}
    metadata = json.loads((directory / 'run.json').read_text())
    gate = junit_gate((directory / 'console.log').read_text())
    result = {
        'elapsed_seconds': metadata['elapsed_seconds'],
        'junit_exit': metadata['exit_code'], 'junit_gate': gate,
        'strict_injection': strict, 'planned_faults': len(sequence),
        'applied_faults': len(applied),
        'last_fault_source': last_source,
        'last_fault_marker': sequence[-1]['point']['marker'],
        'last_fault_mode': sequence[-1]['fault_mode'],
        'last_fault_point_id': point_id(sequence[-1]['point']),
        'postfault_same_child_guards': post_guards,
        'postfault_same_child_throws': post_throws,
        'postfault_guard_operands': operands,
        'new_production_probes': len(probes - set(state['covered_probes'])),
        'new_exact_rpc_selectors': len(selectors - set(state['observed_rpc_selectors'])),
        'trace': str(directory / 'events.jsonl'),
        'jacoco': str(directory / 'jacoco.exec'),
    }
    return result, probes, selectors


def mutate(state: dict, parent: list[dict], directory: Path, result: dict,
           gain: int, newly_observed: set[str]) -> None:
    if not result['strict_injection'] or len(parent) >= state['budget']['max_faults']:
        return
    if not any(result['postfault_same_child_guards'].values()):
        return
    events = load_events(directory)
    applied = [event for event in events
               if event['event'] == 'IO_OBSERVED' and event['applied']]
    last = applied[-1]
    source = parent[-1]['point']['sourceKey']
    available = []
    used = {point_id(item['point']) for item in parent}
    for event in events:
        if (event['event'] == 'IO_OBSERVED' and event['marker'] in MARKERS
            and event['sourceKey'] == source and event['seq'] > last['seq']
            and point_id(point(event)) not in used):
            available.append(point(event))
    unique = {point_id(item): item for item in available}
    ordered = sorted(unique.values(), key=lambda item: item['hitOrdinal'])
    if not ordered:
        return
    indices = sorted({0, len(ordered) // 2, len(ordered) - 1})
    for index in indices:
        selected = ordered[index]
        enqueue(state, parent + [step(selected, 'DELAY', 15000)], gain)
    for selected in (ordered[0], ordered[-1]):
        if point_id(selected) in newly_observed:
            enqueue(state, [step(selected, 'DELAY', 15000)], gain)


def publish(state: dict) -> None:
    rows = state['completed']
    report = {
        'status': state['status'], 'budget': state['budget'],
        'fault_trials': len(rows),
        'total_attempts': sum(row['attempts'] for row in rows),
        'strict_injections': sum(row['strict_injection'] for row in rows),
        'same_child_post_target_trials': {
            case_id: sum(row['strict_injection']
                         and row['postfault_same_child_guards'][case_id] > 0
                         for row in rows)
            for case_id in CHECKS},
        'exact_target_throw_trials': {
            case_id: sum(row['strict_injection']
                         and row['postfault_same_child_throws'][case_id] > 0
                         for row in rows)
            for case_id in CHECKS},
        'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in rows), 3),
        'production_probe_gain': sum(row['new_production_probes'] for row in rows),
        'new_rpc_selectors': sum(row['new_exact_rpc_selectors'] for row in rows),
        'distinct_first_rpc_fault_sites': len({
            point_id(row['sequence'][0]['point']) for row in rows}),
        'fault_depths': dict(Counter(str(row['planned_faults']) for row in rows)),
        'fault_modes': dict(Counter(row['last_fault_mode'] for row in rows)),
        'fault_command_families': dict(Counter(
            row['sequence'][-1]['point']['marker'] for row in rows)),
        'latest': rows[-1] if rows else None,
    }
    atomic(ROOT / 'progress.json', report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-trials', type=int, default=24)
    parser.add_argument('--max-faults', type=int, default=2)
    args = parser.parse_args()
    state_file = ROOT / 'state.json'
    if state_file.is_file():
        state = json.loads(state_file.read_text())
        if state['locks'] != locks():
            raise RuntimeError('RPC campaign source/agent changed across checkpoint')
        previous = state['budget']
        if (args.max_trials < previous['max_trials']
                or args.max_trials < len(state['completed'])
                or args.max_faults < previous['max_faults']):
            raise RuntimeError('RPC budget cannot shrink across checkpoint')
        state['budget'] = {'max_trials': args.max_trials,
                           'max_faults': args.max_faults}
        if (state['status'] == 'budget_complete'
                and len(state['completed']) < args.max_trials and state['queue']):
            state['status'] = 'running'
        atomic(state_file, state)
    else:
        state = initialize(args.max_trials, args.max_faults)
    publish(state)
    while state['status'] == 'running':
        if len(state['completed']) >= args.max_trials:
            state['status'] = 'budget_complete'
            break
        if state['active'] is None and not state['queue']:
            state['status'] = 'queue_exhausted'
            break
        if state['active'] is None:
            state['active'] = choose(state)
            atomic(state_file, state)
        chosen = state['active']
        number = len(state['completed']) + 1
        sequence = chosen['sequence']
        directory = ROOT / 'trials' / f'{number:04d}-{chosen["id"]}'
        directory.mkdir(parents=True, exist_ok=True)
        plan = directory / 'fault.properties'
        write_plan(plan, sequence)
        attempts = []
        for attempt in (1, 2):
            out = directory / f'attempt-{attempt:02d}'
            if not (out / 'run.json').is_file():
                run_junit(out, agent_path=AGENT, fault_plan=plan)
            result, probes, selectors = analyze(out, sequence, state)
            result['attempt'] = attempt
            atomic(out / 'audit.json', result)
            attempts.append((result, probes, selectors))
            if result['strict_injection']:
                break
        result, probes, selectors = attempts[-1]
        row = dict(result, trial_number=number, attempts=len(attempts),
                   sequence=sequence, selected_queue_id=chosen['id'],
                   selected_parent_gain=chosen['parent_gain'])
        row['elapsed_seconds'] = round(sum(
            json.loads((directory / f'attempt-{attempt:02d}' / 'run.json')
                       .read_text())['elapsed_seconds']
            for attempt in range(1, len(attempts) + 1)), 3)
        state['completed'].append(row)
        state['active'] = None
        if result['strict_injection']:
            newly_observed = selectors - set(state['observed_rpc_selectors'])
            state['covered_probes'] = sorted(set(state['covered_probes']) | probes)
            state['observed_rpc_selectors'] = sorted(
                set(state['observed_rpc_selectors']) | selectors)
            mutate(state, sequence, out, result,
                   result['new_production_probes'] +
                   result['new_exact_rpc_selectors'], newly_observed)
        if any(result['postfault_same_child_throws'].values()):
            state['status'] = 'candidate_target_exception'
        atomic(state_file, state)
        publish(state)
        print(json.dumps({'trial': number, 'strict': result['strict_injection'],
                          'post_target': result['postfault_same_child_guards'],
                          'target_throw': result['postfault_same_child_throws'],
                          'new_production_probes': result['new_production_probes'],
                          'elapsed_seconds': result['elapsed_seconds']},
                         sort_keys=True), flush=True)
    atomic(state_file, state)
    publish(state)


if __name__ == '__main__':
    main()
