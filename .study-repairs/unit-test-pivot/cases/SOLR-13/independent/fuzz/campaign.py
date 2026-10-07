#!/usr/bin/env python3
"""Resumable graph-free SOLR-13 I/O and coverage guided exception campaign."""

from collections import Counter
from itertools import combinations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random
import re
import shutil

from coverage import covered_probes
from run_trial import run

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'evidence/campaign'
SEEDS = [HERE / 'evidence/healthy-instrumented-01',
         HERE / 'evidence/healthy-instrumented-02']
STATE = ROOT / 'state.json'
SOURCE_PREFIX = 'SOLR/ROUTED_ALIAS/'
GUARD = 'SOLR13:CREATED_COLLECTION_VISIBLE_GUARD'
THROW = 'SOLR13:CREATED_COLLECTION_MISSING_THROW'
POINT_KEYS = ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal')
LOCKED = ('campaign.py', 'coverage.py', 'run_trial.py')


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temp.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runner_hashes() -> dict:
    return {name: sha256(HERE / name) for name in LOCKED}


def events(path: Path) -> list[dict]:
    if path.is_file():
        with path.open() as input_file:
            return [json.loads(line) for line in input_file if line.strip()]
    archived = Path(str(path) + '.gz')
    with gzip.open(archived, 'rt') as input_file:
        return [json.loads(line) for line in input_file if line.strip()]


def archive_trace(out: Path) -> None:
    """Preserve verified raw evidence while bounding local disk use."""
    raw = out / 'events.jsonl'
    if not raw.is_file():
        return
    archived = Path(str(raw) + '.gz')
    temporary = Path(str(archived) + '.tmp')
    original_digest = sha256(raw)
    with raw.open('rb') as source, gzip.open(temporary, 'wb', compresslevel=6) as sink:
        shutil.copyfileobj(source, sink)
    check = hashlib.sha256()
    with gzip.open(temporary, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            check.update(chunk)
    if check.hexdigest() != original_digest:
        temporary.unlink(missing_ok=True)
        raise RuntimeError('trace compression checksum mismatch')
    temporary.replace(archived)
    atomic(out / 'archive.json', {'raw_sha256': original_digest,
                                  'gzip_sha256': sha256(archived),
                                  'raw_size': raw.stat().st_size,
                                  'gzip_size': archived.stat().st_size})
    raw.unlink()
    scratch = out / 'scratch'
    if scratch.exists():
        shutil.rmtree(scratch)


def point(event: dict) -> dict:
    return {key: event[key] for key in POINT_KEYS}


def point_id(item: dict) -> str:
    return json.dumps(item, sort_keys=True, separators=(',', ':'))


def normalized_resource(resource: str) -> str:
    return re.sub(r'(/overseer/collection-queue-work/(?:qnr|qn)-)\d+$',
                  r'\1{sequence}', resource)


def family(item: dict) -> str:
    return '|'.join((item['marker'], item['siteId'], item['sourceKey'],
                     normalized_resource(item['resource'])))


def relevant(item: dict) -> bool:
    return (item['sourceKey'].startswith(SOURCE_PREFIX) and
            (item['resource'] == '/aliases.json' or
             item['resource'].startswith('/overseer/collection-queue-work/'))
            and not item['siteId'].startswith('UNRESOLVED:'))


def unstable(item: dict) -> bool:
    return bool(re.search(r'/overseer/collection-queue-work/(?:qnr|qn)-\d+$',
                          item['resource']))


def guard_events(rows: list[dict]) -> list[dict]:
    return [e for e in rows if e['event'] == 'TARGET_CHECK'
            and e['marker'] == GUARD and
            e['sourceKey'].startswith(SOURCE_PREFIX)]


def throw_events(rows: list[dict]) -> list[dict]:
    return [e for e in rows if e['event'] == 'TARGET_THROW'
            and e['marker'] == THROW and
            e['sourceKey'].startswith(SOURCE_PREFIX)]


def seed_points() -> list[dict]:
    runs = [events(directory / 'events.jsonl') for directory in SEEDS]
    for directory, rows in zip(SEEDS, runs):
        metadata = json.loads((directory / 'run.json').read_text())
        log = (directory / 'console.log').read_text()
        if (metadata['exit_code'] != 0 or
                'SOLR13_ORIGINAL_JUNIT ran=1 ignored=0 failures=0' not in log or
                len(guard_events(rows)) < 4 or throw_events(rows)):
            raise RuntimeError('instrumented healthy seed failed: ' + str(directory))
    identities_b = {point_id(point(e)) for e in runs[1]
                    if e['event'] == 'IO_OBSERVED' and relevant(point(e))}
    limits = {e['sourceKey']: e['seq'] for e in guard_events(runs[0])}
    unique: dict[str, dict] = {}
    for event in runs[0]:
        if event['event'] != 'IO_OBSERVED':
            continue
        item = point(event)
        identity = point_id(item)
        if (identity in identities_b and relevant(item)
                and event['seq'] < limits.get(item['sourceKey'], -1)):
            unique[identity] = {'point': item, 'seed_seq': event['seq']}
    chosen = list(unique.values())
    chosen.sort(key=lambda row: row['seed_seq'])
    if len(chosen) < 5 or not any(row['point']['resource'] == '/aliases.json'
                                   for row in chosen):
        raise RuntimeError('not enough stable target-context I/O seed points')
    return chosen


def enqueue(state: dict, sequence: list[dict], gain: int = 0) -> None:
    digest = hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:20]
    if digest in state['seen_sequences']:
        return
    state['seen_sequences'].append(digest)
    state['queue'].append({'id': digest, 'sequence': sequence,
                           'parent_gain': gain,
                           'created_after': len(state['completed'])})


def initialize() -> dict:
    stable = seed_points()
    seed_probes = set().union(*(covered_probes(d / 'jacoco.exec') for d in SEEDS))
    seed_families = {family(point(e)) for d in SEEDS
                     for e in events(d / 'events.jsonl')
                     if e['event'] == 'IO_OBSERVED' and relevant(point(e))}
    state = {'schema_version': 1, 'status': 'running',
             'budget': {'max_effective': 80, 'max_faults': 8,
                        'max_attempts': 500,
                        'conditional_max_effective': 128,
                        'conditional_max_faults': 10},
             'agent_sha256': sha256(HERE / 'solr13-agent.jar'),
             'runner_sha256': runner_hashes(),
             'seed_traces': [str(d / 'events.jsonl') for d in SEEDS],
             'seed_probe_count': len(seed_probes),
             'seed_io_family_count': len(seed_families),
             'covered_probes': sorted(seed_probes),
             'io_families': sorted(seed_families),
             'queue': [], 'seen_sequences': [], 'completed': [],
             'active': None}
    for row in stable:
        enqueue(state, [row['point']])
    # Independent, healthy-run ordered combinations give the queue enough
    # different fault histories before post-fault feedback becomes available.
    stable_reliable = [row for row in stable if not unstable(row['point'])]
    for size in (2, 3):
        for combination in combinations(stable_reliable, size):
            if len({row['point']['sourceKey'] for row in combination}) < size:
                continue
            enqueue(state, [row['point'] for row in combination])
    publish(state)
    return state


def select(state: dict) -> dict:
    queue = state['queue']
    round_number = len(state['completed']) + 1
    effective = sum(row['effective'] for row in state['completed'])
    wants_multiple = effective >= 10 and round_number % 4 != 0
    choices = [row for row in queue if (len(row['sequence']) > 1) == wants_multiple]
    if not choices:
        choices = queue
    family_counts = Counter(row['first_family'] for row in state['completed'])
    scored = []
    for row in choices:
        sequence = row['sequence']
        alias_reads = sum(item['resource'] == '/aliases.json' for item in sequence)
        score = (50 * alias_reads / len(sequence)
                 + 20 / (1 + family_counts[family(sequence[0])])
                 + min(25, row['parent_gain'])
                 + min(15, round_number - row['created_after'])
                 + min(16, 4 * len(sequence))
                 - 2 * sum(unstable(item) for item in sequence))
        scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1]['id']))
    top = scored[:min(12, len(scored))]
    rng = random.Random(130000 + round_number)
    chosen = rng.choices([row for _, row in top],
                         weights=[max(1, score) for score, _ in top], k=1)[0]
    queue.remove(chosen)
    return chosen


def write_plan(path: Path, sequence: list[dict]) -> None:
    lines = ['count=' + str(len(sequence))]
    for index, item in enumerate(sequence, 1):
        for key in POINT_KEYS:
            lines.append(f'step.{index}.{key}={item[key]}')
    path.write_text('\n'.join(lines) + '\n')


def analyze(out: Path, sequence: list[dict], state: dict) -> tuple[dict, set, set]:
    rows = events(out / 'events.jsonl')
    applied = [e for e in rows if e['event'] == 'IO_OBSERVED' and e['applied']]
    summaries = [e for e in rows if e['event'] == 'SUMMARY']
    strict = (len(applied) == len(sequence)
              and all(point_id(point(e)) == point_id(p)
                      for e, p in zip(applied, sequence))
              and len(summaries) == 1
              and summaries[0]['detail'] == f'applied={len(sequence)}/{len(sequence)}')
    last = applied[-1] if applied else None
    source = sequence[-1]['sourceKey']
    post_guard = [e for e in guard_events(rows)
                  if strict and e['seq'] > last['seq'] and e['sourceKey'] == source]
    post_throw = [e for e in throw_events(rows)
                  if strict and e['seq'] > last['seq'] and e['sourceKey'] == source]
    probes = covered_probes(out / 'jacoco.exec')
    observed = [e for e in rows if e['event'] == 'IO_OBSERVED' and relevant(point(e))]
    families = {family(point(e)) for e in observed}
    metadata = json.loads((out / 'run.json').read_text())
    log = (out / 'console.log').read_text()
    result = {'junit_exit': metadata['exit_code'],
              'junit_pass': 'SOLR13_ORIGINAL_JUNIT ran=1 ignored=0 failures=0' in log,
              'elapsed_seconds': metadata['elapsed_seconds'],
              'strict_injection': strict,
              'planned_faults': len(sequence), 'applied_faults': len(applied),
              'target_guard_count': len(guard_events(rows)),
              'target_guard_after_last_fault': len(post_guard),
              'target_exception_after_last_fault': len(post_throw),
              'target_source_after_last_fault': source if post_guard else None,
              'effective': bool(post_guard),
              'new_production_probes': len(probes - set(state['covered_probes'])),
              'new_io_families': len(families - set(state['io_families'])),
              'production_probes_covered': len(probes),
              'io_observed_count': len(observed),
              'applied_physical_nodes': [e['physicalNode'] for e in applied],
              'last_applied_sequence': last['seq'] if last else None,
              'trace': str(out / 'events.jsonl.gz'),
              'jacoco': str(out / 'jacoco.exec')}
    return result, probes, families


def mutate(state: dict, parent: list[dict], out: Path, gain: int) -> None:
    if len(parent) >= state['budget']['max_faults']:
        return
    rows = events(out / 'events.jsonl')
    applied = [e for e in rows if e['event'] == 'IO_OBSERVED' and e['applied']]
    if not applied:
        return
    last_seq = applied[-1]['seq']
    last_guard = max((e['seq'] for e in guard_events(rows)), default=-1)
    if last_guard <= last_seq:
        return
    used = {point_id(item) for item in parent}
    candidates: dict[str, dict] = {}
    for e in rows:
        if e['event'] != 'IO_OBSERVED' or not last_seq < e['seq'] < last_guard:
            continue
        item = point(e)
        if not relevant(item) or unstable(item) or point_id(item) in used:
            continue
        candidates.setdefault(family(item), item)
    ranked = sorted(candidates.values(), key=lambda item:
                    (item['resource'] != '/aliases.json', item['sourceKey'],
                     item['siteId']))
    for item in ranked[:20]:
        enqueue(state, parent + [item], gain)


def publish(state: dict) -> None:
    atomic(STATE, state)
    completed = state['completed']
    effective = [row for row in completed if row['effective']]
    progress = {'case_id': 'SOLR-13', 'status': state['status'],
                'budget': state['budget'], 'attempted_plans': len(completed),
                'jvm_attempts': sum(row['attempts'] for row in completed),
                'strict_injections': sum(row['strict_injection'] for row in completed),
                'effective_target_retaining_trials': len(effective),
                'target_exception_candidates': sum(
                    row['effective'] and row['target_exception_after_last_fault'] > 0
                    for row in completed),
                'max_applied_faults': max((row['applied_faults'] for row in completed),
                                          default=0),
                'production_probe_gain': len(state['covered_probes'])
                                         - state['seed_probe_count'],
                'io_family_gain': len(state['io_families'])
                                  - state['seed_io_family_count'],
                'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in completed), 3),
                'queue_size': len(state['queue']),
                'latest': completed[-1] if completed else None}
    atomic(ROOT / 'progress.json', progress)


def campaign() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if STATE.is_file():
        state = json.loads(STATE.read_text())
        if (state['runner_sha256'] != runner_hashes() or
                state['agent_sha256'] != sha256(HERE / 'solr13-agent.jar')):
            raise RuntimeError('runner/agent hash changed; checkpoint migration required')
        if state['status'] in ('budget_complete', 'queue_exhausted',
                               'candidate_target_exception',
                               'attempt_cap_exhausted'):
            return
    else:
        state = initialize()
    while state['queue'] or state['active']:
        effective = sum(row['effective'] for row in state['completed'])
        if effective >= state['budget']['max_effective']:
            recent = [row for row in state['completed'] if row['effective']][-10:]
            novelty = any(row['new_production_probes'] or row['new_io_families']
                          for row in recent)
            if (state['budget']['max_effective'] == 80 and novelty):
                state['budget']['max_effective'] = 128
                state['budget']['max_faults'] = 10
                publish(state)
            else:
                state['status'] = 'budget_complete'
                publish(state)
                return
        if len(state['completed']) >= state['budget']['max_attempts']:
            state['status'] = 'attempt_cap_exhausted'
            publish(state)
            return
        if state['active'] is None:
            state['active'] = select(state)
            state['active']['number'] = len(state['completed']) + 1
            state['active']['attempts'] = 0
            publish(state)
        active = state['active']
        number = active['number']
        trial = ROOT / 'trials' / f'{number:04d}-{active["id"]}'
        trial.mkdir(parents=True, exist_ok=True)
        plan = trial / 'fault.properties'
        if not plan.is_file():
            write_plan(plan, active['sequence'])
        result = None
        for attempt in range(1, 3):
            out = trial / f'attempt-{attempt:02d}'
            if not (out / 'run.json').is_file():
                run(out, plan)
            active['attempts'] = max(active['attempts'], attempt)
            publish(state)
            result, probes, families = analyze(out, active['sequence'], state)
            atomic(out / 'audit.json', result)
            if result['strict_injection']:
                break
        assert result is not None
        result.update({'trial_number': number, 'attempts': active['attempts'],
                       'first_family': family(active['sequence'][0]),
                       'last_family': family(active['sequence'][-1]),
                       'fault_sequence': active['sequence'],
                       'status': ('target_exception_candidate'
                                  if result['effective'] and
                                     result['target_exception_after_last_fault'] else
                                  'checked' if result['effective'] else
                                  'lost_target' if result['strict_injection'] else
                                  'unmatched')})
        result['elapsed_seconds'] = round(sum(
            json.loads((trial / f'attempt-{i:02d}' / 'run.json').read_text())
            ['elapsed_seconds'] for i in range(1, active['attempts'] + 1)), 3)
        atomic(trial / 'result.json', result)
        state['completed'].append(result)
        state['active'] = None
        if result['effective']:
            gain = result['new_production_probes'] + result['new_io_families']
            mutate(state, active['sequence'], out, gain)
            state['covered_probes'] = sorted(set(state['covered_probes']) | probes)
            state['io_families'] = sorted(set(state['io_families']) | families)
        if result['status'] == 'target_exception_candidate':
            state['status'] = 'candidate_target_exception'
            for attempt in range(1, active['attempts'] + 1):
                archive_trace(trial / f'attempt-{attempt:02d}')
            publish(state)
            return
        for attempt in range(1, active['attempts'] + 1):
            archive_trace(trial / f'attempt-{attempt:02d}')
        publish(state)
    state['status'] = 'queue_exhausted'
    publish(state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    campaign()
