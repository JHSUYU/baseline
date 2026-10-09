#!/usr/bin/env python3
"""Resumable receiver/destination-aware LISTALIASES exception fuzzing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import subprocess

from build_v2 import DIST, HERE, JAVA8, sha
from calibrate_v2 import ACTOR, RESOURCE, SEEDS, SITE, audit, calibrate, detail, events, locked_hashes
from run_v2 import run, verify_build

ROOT = HERE / 'campaign'
STATE = ROOT / 'state.json'
KINDS = ('IO_EXCEPTION', 'SOLR_SERVER_EXCEPTION')
FIELDS = ('actorKey', 'destinationKey', 'siteId', 'resource',
          'callOrdinal', 'attemptOrdinal', 'kind')


def atomic(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n')
    temp.replace(path)


def point(row: dict, kind: str) -> dict:
    item = {name: row[name] for name in FIELDS[:-1]}
    if row['destinationKey'].startswith('JETTY/node'):
        item['destinationKey'] = 'JETTY/attempt' + str(row['attemptOrdinal'])
    return {**item, 'kind': kind}


def plan_matches_io(item: dict, row: dict) -> bool:
    for field in FIELDS[:-1]:
        if field == 'destinationKey' and item[field].startswith('JETTY/attempt'):
            if (item[field] != 'JETTY/attempt' + str(row['attemptOrdinal']) or
                    not row[field].startswith('JETTY/node')):
                return False
        elif row[field] != item[field]:
            return False
    return True


def identity(item: dict) -> str:
    return json.dumps(item, sort_keys=True, separators=(',', ':'))


def family(item: dict) -> str:
    return '|'.join((item['actorKey'], item['destinationKey'], item['siteId'],
                     item['resource'], item['kind']))


def write_plan(path: Path, sequence: list[dict]) -> None:
    lines = ['count=' + str(len(sequence))]
    for index, item in enumerate(sequence, 1):
        lines.extend(f'step.{index}.{field}={item[field]}' for field in FIELDS)
    path.write_text('\n'.join(lines) + '\n')


def coverage(directory: Path) -> set[str]:
    execution = directory / 'jacoco.exec'
    if not execution.is_file() or not execution.stat().st_size:
        return set()
    cp = ':'.join((str(HERE / 'classes'),
                   str(HERE.parent / 'independent/lib/jacoco-core.jar')))
    result = subprocess.check_output([str(JAVA8 / 'java'), '-cp', cp,
                                      'baseline.solr01.CoverageProbes',
                                      str(execution), str(DIST)], text=True)
    return set(result.splitlines())


def target_after(rows: list[dict], applied: list[dict]) -> tuple[bool, bool]:
    if not applied:
        return False, False
    last = applied[-1]
    provider = detail(last['detail']).get('providerIdentity')
    client = detail(last['detail']).get('clientIdentity')
    checks = [row for row in rows if row['event'] == 'TARGET_CHECK'
              and row['seq'] > last['seq'] and row['actorKey'] == ACTOR
              and row['callOrdinal'] == last['callOrdinal']
              and detail(row['detail']).get('providerIdentity') == provider
              and detail(row['detail']).get('clientIdentity') == client]
    throws = [row for row in rows if row['event'] == 'TARGET_THROW'
              and row['actorKey'] == ACTOR and
              any(row['seq'] == check['seq'] + 1 for check in checks)]
    return bool(checks), bool(throws)


def strict(rows: list[dict], sequence: list[dict]) -> bool:
    applied = [row for row in rows if row['event'] == 'IO_APPLIED']
    if len(applied) != len(sequence):
        return False
    providers = {detail(row['detail']).get('providerIdentity') for row in applied}
    clients = {detail(row['detail']).get('clientIdentity') for row in applied}
    threads = {row['threadId'] for row in applied}
    calls = {row['callOrdinal'] for row in applied}
    if (len(providers) != 1 or None in providers or len(clients) != 1 or
            None in clients or len(threads) != 1 or len(calls) != 1):
        return False
    if len({detail(row['detail']).get('nodeName') for row in applied}) != len(applied):
        return False
    for index, (row, item) in enumerate(zip(applied, sequence), 1):
        if not plan_matches_io(item, row):
            return False
        metadata = detail(row['detail'])
        if metadata.get('planStep') != str(index) or metadata.get('kind') != item['kind']:
            return False
        previous = [e for e in rows if e['event'] == 'IO_OBSERVED'
                    and e['seq'] + 1 == row['seq']]
        if len(previous) != 1 or not plan_matches_io(item, previous[0]):
            return False
    summaries = [row for row in rows if row['event'] == 'SUMMARY']
    return len(summaries) == 1 and summaries[0]['detail'] == (
        f'applied={len(sequence)}/{len(sequence)}')


def seed_points(first: list[dict], second: list[dict]) -> list[dict]:
    in_second = {identity(point(row, kind)) for row in second
                 if row['event'] == 'IO_OBSERVED'
                 for kind in KINDS}
    chosen: list[dict] = []
    seen: set[str] = set()
    for row in first:
        if (row['event'] != 'IO_OBSERVED' or row['actorKey'] != ACTOR or
                row['destinationKey'].startswith('UNBOUND:')):
            continue
        if not any(check['event'] == 'TARGET_CHECK' and check['seq'] > row['seq']
                   and check['callOrdinal'] == row['callOrdinal']
                   and check['actorKey'] == ACTOR for check in first):
            continue
        for kind in KINDS:
            item = point(row, kind)
            key = identity(item)
            if key in in_second and key not in seen:
                chosen.append(item)
                seen.add(key)
    return chosen


def initialize() -> dict:
    verify_build()
    receipt = calibrate()
    a, b = (events(seed / 'events.jsonl') for seed in SEEDS)
    roots = seed_points(a, b)
    if not roots:
        raise RuntimeError('two healthy runs share no exact actor-bound target IO point')
    base_coverage = coverage(SEEDS[0]) | coverage(SEEDS[1])
    families = {family(point(row, kind)) for rows in (a, b) for row in rows
                if row['event'] == 'IO_OBSERVED' and row['actorKey'] == ACTOR
                for kind in KINDS}
    state = {
        'case_id': 'SOLR-01', 'methodology': 'actor_aware_http_io_coverage_v2',
        'calibration_sha256': sha(HERE / 'calibration-receipt.json'),
        'agent_sha256': receipt['agent_sha256'],
        'runner_hashes': receipt['runner_hashes'],
        'budget': {'effective_trials': 80, 'max_faults': 8, 'max_selected': 320},
        'queue': [{'sequence': [item], 'parent_gain': 0, 'wait': 0} for item in roots],
        'seen': [], 'trials': [], 'baseline_coverage': sorted(base_coverage),
        'seen_coverage': sorted(base_coverage), 'baseline_families': sorted(families),
        'seen_families': sorted(families), 'selected_count': 0,
    }
    atomic(STATE, state)
    return state


def verify_state(state: dict) -> None:
    verify_build()
    if state['calibration_sha256'] != sha(HERE / 'calibration-receipt.json'):
        raise RuntimeError('healthy calibration changed after campaign started')
    if state['runner_hashes'] != locked_hashes():
        raise RuntimeError('V2 runner/controller changed after calibration')


def choose(state: dict) -> dict:
    queue = state['queue']
    round_no = state['selected_count'] + 1
    rng = random.Random(101000 + round_no)
    for entry in queue:
        entry['wait'] += 1
    scored = []
    for entry in queue:
        count = len(entry['sequence'])
        score = 4 * entry['parent_gain'] + min(entry['wait'], 40) / 10
        score += 2 * min(count, 6) if count > 1 else 0
        score += rng.random() / 8
        scored.append(score)
    return queue.pop(max(range(len(queue)), key=lambda index: scored[index]))


def enqueue(state: dict, sequence: list[dict], gain: int) -> None:
    digest = identity(sequence)
    if digest in state['seen'] or any(identity(e['sequence']) == digest
                                       for e in state['queue']):
        return
    state['queue'].append({'sequence': sequence, 'parent_gain': gain, 'wait': 0})


def mutate(state: dict, sequence: list[dict], rows: list[dict], trial: dict) -> None:
    if not trial['effective'] or len(sequence) >= state['budget']['max_faults']:
        return
    applied = [row for row in rows if row['event'] == 'IO_APPLIED']
    last = applied[-1]
    provider = detail(last['detail']).get('providerIdentity')
    later = [row for row in rows if row['event'] == 'TARGET_CHECK'
             and row['seq'] > last['seq'] and row['actorKey'] == ACTOR
             and row['callOrdinal'] == last['callOrdinal']
             and detail(row['detail']).get('providerIdentity') == provider]
    if not later:
        return
    target_seq = min(row['seq'] for row in later)
    choices = [row for row in rows if row['event'] == 'IO_OBSERVED'
               and last['seq'] < row['seq'] < target_seq
               and row['actorKey'] == ACTOR
               and row['callOrdinal'] == last['callOrdinal']
               and detail(row['detail']).get('providerIdentity') == provider
               and row['destinationKey'].startswith('JETTY/')]
    gain = trial['new_coverage'] + trial['new_families']
    for row in choices[:4 if gain else 2]:
        for kind in KINDS:
            enqueue(state, sequence + [point(row, kind)], gain)


def analyze(directory: Path, sequence: list[dict], state: dict) -> tuple[dict, set[str], set[str], list[dict]]:
    rows = events(directory / 'events.jsonl')
    actor_audit = audit_trial(rows)
    applied = [row for row in rows if row['event'] == 'IO_APPLIED']
    exact = strict(rows, sequence)
    after, thrown = target_after(rows, applied) if exact else (False, False)
    effective = exact and after
    probes = coverage(directory) if effective else set()
    families = {family(point(row, kind)) for row in rows
                if row['event'] == 'IO_OBSERVED' and row['actorKey'] == ACTOR
                and row['destinationKey'].startswith('JETTY/') for kind in KINDS}
    previous_probes = set(state['seen_coverage'])
    previous_families = set(state['seen_families'])
    metadata = json.loads((directory / 'run.json').read_text())
    trial = {
        'number': state['selected_count'], 'sequence': sequence,
        'elapsed_seconds': metadata['elapsed_seconds'], 'junit_exit': metadata['exit_code'],
        'exact_injection': exact, 'applied_faults': len(applied),
        'target_after_fault': after, 'target_exception': thrown, 'effective': effective,
        'new_coverage': len(probes - previous_probes) if effective else 0,
        'new_families': len(families - previous_families) if effective else 0,
        'actor_audit': actor_audit, 'evidence': str(directory.relative_to(HERE)),
    }
    return trial, probes, families, rows


def audit_trial(rows: list[dict]) -> dict:
    bindings: dict[str, str] = {}
    clients: dict[str, str] = {}
    for row in rows:
        if row['event'] == 'NODE_AMBIGUOUS':
            raise RuntimeError('ambiguous node binding in fault run')
        if row['event'] == 'NODE_BIND':
            fields = detail(row['detail'])
            node = fields.get('nodeName')
            if node in bindings and bindings[node] != row['destinationKey']:
                raise RuntimeError('live node changed role in fault run')
            bindings[node] = row['destinationKey']
        if row['event'] == 'CLIENT_BIND':
            fields = detail(row['detail'])
            provider = fields.get('providerIdentity')
            client = fields.get('clientIdentity')
            if provider in clients and clients[provider] != client:
                raise RuntimeError('provider changed client in fault run')
            clients[provider] = client
    active: dict[int, str] = {}
    for row in rows:
        if row['event'] not in ('TARGET_ENTER', 'IO_OBSERVED', 'IO_APPLIED',
                                'TARGET_CHECK', 'REQUEST_ENTER'):
            continue
        fields = detail(row['detail'])
        provider = fields.get('providerIdentity')
        if row['actorKey'] == ACTOR and provider not in clients:
            raise RuntimeError('V2 actor contradicts selected provider binding')
        if row['actorKey'] == ACTOR and row['event'] != 'TARGET_ENTER' and (
                clients[provider] != fields.get('clientIdentity')):
            raise RuntimeError('V2 actor contradicts selected client identity')
        if row['event'] == 'TARGET_ENTER' and row['actorKey'] == ACTOR:
            active[row['threadId']] = provider
        elif row['event'] in ('IO_OBSERVED', 'TARGET_CHECK') and row['actorKey'] == ACTOR:
            if active.get(row['threadId']) != provider:
                raise RuntimeError('selected alias IO/check outside bound provider call')
            if row['event'] == 'TARGET_CHECK':
                active.pop(row['threadId'], None)
        if row['event'].startswith('IO_'):
            if row['applied'] and (row['actorKey'] != ACTOR or
                                   not row['destinationKey'].startswith('JETTY/')):
                raise RuntimeError('unbound IO applied a fault')
            node = fields.get('nodeName')
            if row['destinationKey'].startswith('JETTY/') and bindings.get(node) != row['destinationKey']:
                raise RuntimeError('V2 destination contradicts raw Jetty node')
    return {'bound_nodes': len(bindings), 'selected_clients': len(clients),
            'selected_provider_enters': sum(row['event'] == 'TARGET_ENTER' and
                                            row['actorKey'] == ACTOR for row in rows)}


def run_campaign() -> None:
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    verify_state(state)
    while (sum(row['effective'] for row in state['trials']) < state['budget']['effective_trials']
           and state['selected_count'] < state['budget']['max_selected']
           and state['queue']):
        entry = choose(state)
        sequence = entry['sequence']
        digest = identity(sequence)
        if digest in state['seen']:
            continue
        number = state['selected_count'] + 1
        directory = ROOT / f'trial-{number:03d}'
        directory.mkdir(parents=True, exist_ok=True)
        plan = directory / 'fault.properties'
        write_plan(plan, sequence)
        run(directory, plan)
        state['selected_count'] = number
        trial, probes, families, rows = analyze(directory, sequence, state)
        state['seen'].append(digest)
        if trial['effective']:
            state['seen_coverage'] = sorted(set(state['seen_coverage']) | probes)
            state['seen_families'] = sorted(set(state['seen_families']) | families)
        state['trials'].append(trial)
        mutate(state, sequence, rows, trial)
        atomic(directory / 'trial.json', trial)
        atomic(STATE, state)
        count = sum(row['effective'] for row in state['trials'])
        print(f'SOLR-01 V2 selected={number} effective={count}/{state["budget"]["effective_trials"]} '
              f'applied={trial["applied_faults"]}/{len(sequence)} '
              f'target={trial["target_after_fault"]} throw={trial["target_exception"]} '
              f'coverage+={trial["new_coverage"]} io+={trial["new_families"]}', flush=True)
        if count == 80 and not state.get('extension_decided'):
            last = [row for row in state['trials'] if row['effective']][-8:]
            state['extension_decided'] = True
            if any(row['new_coverage'] or row['new_families'] for row in last):
                state['budget'] = {'effective_trials': 128, 'max_faults': 10,
                                   'max_selected': 512}
                state['extension_reason'] = 'coverage or actor-bound IO novelty in last 8 effective trials'
            atomic(STATE, state)
    state['stopped'] = True
    atomic(STATE, state)


if __name__ == '__main__':
    run_campaign()
