#!/usr/bin/env python3
"""Resumable PULL-assertion fuzzing with ZK actor and target identity."""

from __future__ import annotations

import json
from pathlib import Path
import random
import re
import subprocess

from build_v2 import DIST, HERE, JAVA8, sha
from calibrate_v2 import (SEEDS, SOURCE, audit, calibrate, detail, locked_hashes,
                          rows, selected, target_signature)
from run_v2 import run, verify_build

ROOT = HERE / 'campaign'
STATE = ROOT / 'state.json'
KIND = 'CONNECTION_LOSS'
FIELDS = ('actorKey', 'sourceKey', 'operation', 'siteId', 'resource',
          'hitOrdinal', 'kind')


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def point(row: dict) -> dict:
    return {**{field: row[field] for field in FIELDS[:-1]}, 'kind': KIND}


def identity(item: object) -> str:
    return json.dumps(item, sort_keys=True, separators=(',', ':'))


def family(item: dict) -> str:
    resource = re.sub(r'(/election/)[^/]+$', r'\1{ephemeral}', item['resource'])
    resource = re.sub(r'core_node\d+', 'core_node*', resource)
    return '|'.join((item['actorKey'], item['sourceKey'], item['operation'],
                     item['siteId'], resource))


def relevant(row: dict) -> bool:
    return (row['event'] == 'IO_OBSERVED' and row['sourceKey'] == SOURCE
            and row['actorKey'] in ('JETTY/node1', 'JETTY/node2')
            and not row['siteId'].startswith('UNBOUND:')
            and not re.search(r'/election/[^/]+$', row['resource']))


def write_plan(path: Path, sequence: list[dict]) -> None:
    content = ['count=' + str(len(sequence))]
    for index, item in enumerate(sequence, 1):
        content.extend(f'step.{index}.{field}={item[field]}' for field in FIELDS)
    path.write_text('\n'.join(content) + '\n')


def coverage(directory: Path) -> set[str]:
    file = directory / 'jacoco.exec'
    if not file.is_file() or not file.stat().st_size:
        return set()
    cp = ':'.join((str(HERE / 'classes'),
                   str(HERE.parent / 'independent/lib/jacoco-core.jar')))
    output = subprocess.check_output([str(JAVA8 / 'java'), '-cp', cp,
                                      'baseline.solr06.CoverageProbes', str(file),
                                      str(DIST)], text=True)
    return set(output.splitlines())


def seed_candidates(first: list[dict], second: list[dict], common: set[tuple]) -> list[dict]:
    candidates = []
    seen = set()
    for target in sorted(common):
        a_guards = [row for row in first if selected(row)
                    and target_signature(row) == target]
        b_guards = [row for row in second if selected(row)
                    and target_signature(row) == target]
        if not a_guards or not b_guards:
            continue
        cutoff_a = min(row['seq'] for row in a_guards)
        cutoff_b = min(row['seq'] for row in b_guards)
        second_points = {identity(point(row)) for row in second
                         if relevant(row) and row['actorKey'] == target[0]
                         and row['seq'] < cutoff_b}
        matching = [point(row) for row in first
                    if relevant(row) and row['actorKey'] == target[0]
                    and row['seq'] < cutoff_a
                    and identity(point(row)) in second_points]
        # Favor I/O nearest the assertion; retain a few earlier paths for breadth.
        chosen = list(reversed(matching[-20:])) + matching[:8]
        for item in chosen:
            key = identity((target, item))
            if key in seen:
                continue
            seen.add(key)
            candidates.append({'target': list(target), 'sequence': [item],
                               'parent_gain': 0, 'wait': 0})
    return candidates


def initialize() -> dict:
    verify_build()
    receipt = calibrate()
    first, second = (rows(seed) for seed in SEEDS)
    common = set(map(tuple, receipt['common_target_signatures']))
    queue = seed_candidates(first, second, common)
    if not queue:
        raise RuntimeError('two healthy runs share no actor-bound I/O before an exact PULL target')
    base = coverage(SEEDS[0]) | coverage(SEEDS[1])
    families = {family(point(row)) for trace in (first, second)
                for row in trace if relevant(row)}
    state = {
        'case_id': 'SOLR-06', 'methodology': 'actor_aware_zk_io_coverage_v2',
        'agent_sha256': receipt['agent_sha256'],
        'calibration_sha256': sha(HERE / 'calibration-receipt.json'),
        'runner_hashes': receipt['runner_hashes'],
        'budget': {'effective_trials': 80, 'max_faults': 8, 'max_selected': 320},
        'queue': queue, 'seen': [], 'trials': [], 'selected_count': 0,
        'baseline_coverage': sorted(base), 'seen_coverage': sorted(base),
        'baseline_families': sorted(families), 'seen_families': sorted(families),
    }
    atomic(STATE, state)
    return state


def verify_state(state: dict) -> None:
    verify_build()
    if state['calibration_sha256'] != sha(HERE / 'calibration-receipt.json'):
        raise RuntimeError('healthy calibration changed during V2 campaign')
    if state['runner_hashes'] != locked_hashes():
        raise RuntimeError('runner/controller changed after V2 calibration')


def choose(state: dict) -> dict:
    queue = state['queue']
    randomizer = random.Random(606000 + state['selected_count'])
    for entry in queue:
        entry['wait'] += 1
    scored = []
    for entry in queue:
        depth = len(entry['sequence'])
        score = 4 * entry['parent_gain'] + min(entry['wait'], 40) / 10
        score += 2 * min(depth, 6) if depth > 1 else 0
        score += randomizer.random() / 8
        scored.append(score)
    return queue.pop(max(range(len(queue)), key=lambda index: scored[index]))


def enqueue(state: dict, target: list[str], sequence: list[dict], gain: int) -> None:
    digest = identity((target, sequence))
    if digest in state['seen'] or any(identity((row['target'], row['sequence'])) == digest
                                       for row in state['queue']):
        return
    state['queue'].append({'target': target, 'sequence': sequence,
                           'parent_gain': gain, 'wait': 0})


def audit_trial(trace: list[dict]) -> dict:
    bindings: dict[str, tuple[str, str, str]] = {}
    controllers: dict[str, str] = {}
    for row in trace:
        if row['event'] != 'CLIENT_BIND':
            continue
        info = detail(row['detail'])
        client = info.get('clientIdentity')
        value = (row['actorKey'], info.get('nodeName'), info.get('controllerIdentity'))
        if client in bindings and bindings[client] != value:
            raise RuntimeError('fault run rebound a SolrZkClient')
        bindings[client] = value
        controllers[info.get('controllerIdentity')] = row['actorKey']
    for row in trace:
        if row['event'] in ('IO_OBSERVED', 'IO_APPLIED'):
            info = detail(row['detail'])
            binding = bindings.get(info.get('clientIdentity'))
            if row['actorKey'].startswith('JETTY/') and (
                    binding is None or binding[0] != row['actorKey'] or
                    binding[1] != info.get('nodeName')):
                raise RuntimeError('I/O actor contradicts raw SolrZkClient')
            if row['event'] == 'IO_APPLIED' and not row['actorKey'].startswith('JETTY/'):
                raise RuntimeError('unbound SolrZkClient consumed a fault')
        elif row['event'] == 'TARGET_CHECK' and selected(row):
            info = detail(row['detail'])
            binding = bindings.get(info.get('clientIdentity'))
            if (binding is None or binding[0] != row['actorKey'] or
                    binding[1] != info.get('nodeName') or
                    controllers.get(info.get('controllerIdentity')) != row['actorKey']):
                raise RuntimeError('target guard contradicts raw actor binding')
    return {'bindings': len(bindings), 'bound_roles': sorted({v[0] for v in bindings.values()})}


def exact(trace: list[dict], sequence: list[dict]) -> bool:
    applied = [row for row in trace if row['event'] == 'IO_APPLIED']
    if len(applied) != len(sequence):
        return False
    for number, (row, item) in enumerate(zip(applied, sequence), 1):
        if any(row[field] != item[field] for field in FIELDS[:-1]):
            return False
        info = detail(row['detail'])
        if info.get('planStep') != str(number) or info.get('kind') != item['kind']:
            return False
        prior = [e for e in trace if e['event'] == 'IO_OBSERVED'
                 and e['seq'] + 1 == row['seq']]
        if len(prior) != 1 or any(prior[0][field] != item[field]
                                 for field in FIELDS[:-1]):
            return False
    summary = [row for row in trace if row['event'] == 'SUMMARY']
    return len(summary) == 1 and summary[0]['detail'] == (
        f'applied={len(sequence)}/{len(sequence)}')


def analyze(directory: Path, target: list[str], sequence: list[dict],
            state: dict) -> tuple[dict, set[str], set[str], list[dict]]:
    trace = rows(directory)
    actor_audit = audit_trial(trace)
    applied = [row for row in trace if row['event'] == 'IO_APPLIED']
    strict = exact(trace, sequence)
    last = applied[-1]['seq'] if applied else -1
    guards = [row for row in trace if selected(row) and
              target_signature(row) == tuple(target) and row['seq'] > last]
    throws = [row for row in trace if row['event'] == 'TARGET_THROW'
              and target_signature(row) == tuple(target) and row['seq'] > last]
    effective = strict and bool(guards)
    probes = coverage(directory) if effective else set()
    families = {family(point(row)) for row in trace if relevant(row)}
    old_probes = set(state['seen_coverage'])
    old_families = set(state['seen_families'])
    metadata = json.loads((directory / 'run.json').read_text())
    result = {
        'number': state['selected_count'], 'target': target, 'sequence': sequence,
        'elapsed_seconds': metadata['elapsed_seconds'], 'junit_exit': metadata['exit_code'],
        'exact_injection': strict, 'applied_faults': len(applied),
        'target_after_fault': bool(guards) if strict else False,
        'target_exception': bool(throws) if strict else False,
        'effective': effective,
        'new_coverage': len(probes - old_probes) if effective else 0,
        'new_families': len(families - old_families) if effective else 0,
        'actor_audit': actor_audit, 'evidence': str(directory.relative_to(HERE)),
    }
    return result, probes, families, trace


def mutate(state: dict, target: list[str], sequence: list[dict],
           trace: list[dict], result: dict) -> None:
    if not result['effective'] or len(sequence) >= state['budget']['max_faults']:
        return
    applied = [row for row in trace if row['event'] == 'IO_APPLIED']
    last = applied[-1]
    later = [row for row in trace if selected(row) and
             target_signature(row) == tuple(target) and row['seq'] > last['seq']]
    if not later:
        return
    finish = min(row['seq'] for row in later)
    choices = [point(row) for row in trace if relevant(row)
               and row['actorKey'] == target[0]
               and last['seq'] < row['seq'] < finish]
    gain = result['new_coverage'] + result['new_families']
    for item in choices[:6 if gain else 3]:
        enqueue(state, target, sequence + [item], gain)


def campaign() -> None:
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    verify_state(state)
    while (sum(row['effective'] for row in state['trials']) < state['budget']['effective_trials']
           and state['selected_count'] < state['budget']['max_selected']
           and state['queue']):
        entry = choose(state)
        target, sequence = entry['target'], entry['sequence']
        digest = identity((target, sequence))
        if digest in state['seen']:
            continue
        number = state['selected_count'] + 1
        directory = ROOT / f'trial-{number:03d}'
        directory.mkdir(parents=True, exist_ok=True)
        plan = directory / 'fault.properties'
        write_plan(plan, sequence)
        run(directory, plan)
        state['selected_count'] = number
        result, probes, families, trace = analyze(directory, target, sequence, state)
        state['seen'].append(digest)
        if result['effective']:
            state['seen_coverage'] = sorted(set(state['seen_coverage']) | probes)
            state['seen_families'] = sorted(set(state['seen_families']) | families)
        state['trials'].append(result)
        mutate(state, target, sequence, trace, result)
        atomic(directory / 'trial.json', result)
        atomic(STATE, state)
        count = sum(row['effective'] for row in state['trials'])
        print(f'SOLR-06 V2 selected={number} effective={count}/{state["budget"]["effective_trials"]} '
              f'applied={result["applied_faults"]}/{len(sequence)} '
              f'target={result["target_after_fault"]} assertion={result["target_exception"]} '
              f'coverage+={result["new_coverage"]} io+={result["new_families"]}', flush=True)
        if count == 80 and not state.get('extension_decided'):
            recent = [row for row in state['trials'] if row['effective']][-8:]
            state['extension_decided'] = True
            if any(row['new_coverage'] or row['new_families'] for row in recent):
                state['budget'] = {'effective_trials': 128, 'max_faults': 10,
                                   'max_selected': 512}
                state['extension_reason'] = 'coverage or actor-bound IO novelty in last 8 effective trials'
            atomic(STATE, state)
    state['stopped'] = True
    atomic(STATE, state)


if __name__ == '__main__':
    campaign()
