#!/usr/bin/env python3
"""Independent raw-receipt audit of the SOLR-36/37 ZK actor-V2 campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import tarfile

from fuzz_v2 import (AGENT, GUARDS, HERE, ROOT, SEEDS, runner_hashes)
from run_healthy import source_provenance

FIELDS = ('marker', 'siteId', 'sourceKey', 'actorKey', 'resource',
          'hitOrdinal', 'sessionGeneration')
THROWS = {'SOLR-36': 'SOLR36:ACTIVE_SUBSHARD_THROW',
          'SOLR-37': 'SOLR37:CHILD_RANGE_THROW'}


def load_events(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()
            if line.strip()]


def junit_gate(log: str) -> tuple[int, int, int] | None:
    match = re.search(r'SOLR_SUBSHARD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)', log)
    return tuple(map(int, match.groups())) if match else None


def raw_point(event: dict) -> dict:
    return {field: event[field] for field in FIELDS}


def raw_binding_check(events: list[dict]) -> dict:
    bindings = {}
    for event in events:
        if event['event'] != 'CLIENT_BIND' or not event['actorKey'].startswith('JETTY/'):
            continue
        match = re.search(r'clientIdentity=(\d+)', event['detail'])
        require(match is not None, 'CLIENT_BIND missing raw SolrZkClient identity')
        identity = int(match.group(1))
        role = (event['actorKey'], event['physicalNode'])
        require(identity not in bindings or bindings[identity] == role,
                'one SolrZkClient maps to two server actors')
        bindings[identity] = role
    require(bool(bindings), 'no bound SolrZkClient')
    handles = {}
    applied = target = 0
    for event in events:
        selected = event['event'] == 'IO_OBSERVED' and event['applied']
        guard = event['event'] in ('TARGET_ENTER', 'TARGET_CHECK', 'TARGET_THROW')
        if not (selected or guard):
            continue
        client = event.get('zkClientIdentity', 0)
        require(bindings.get(client) == (event['actorKey'], event['physicalNode']),
                'fault or target reached a different server actor')
        generation = event.get('sessionGeneration', 0)
        handle = event.get('zkHandleIdentity', 0)
        session = event.get('zkSessionId', 0)
        require(generation > 0 and handle > 0 and session > 0,
                'fault or target lacks physical ZooKeeper session')
        require(not selected or event.get('sessionEligible') is True,
                'fault selected a disconnected ZooKeeper session')
        key = (client, generation)
        require(key not in handles or handles[key] == (handle, session),
                'one connection generation has inconsistent raw handle/session')
        handles[key] = (handle, session)
        applied += selected
        target += guard
    return {'bindings': len(bindings), 'applied_io_checked': applied,
            'target_events_checked': target, 'client_generations': len(handles)}


def guard_events(events: list[dict], case_id: str) -> list[dict]:
    return [event for event in events if event['event'] == 'TARGET_CHECK'
            and event['marker'] == GUARDS[case_id]
            and event['actorKey'].startswith('JETTY/')
            and event['sourceKey'].startswith('SOLR/SUBSHARD/collection1/shard1_')]


def throw_events(events: list[dict], case_id: str) -> list[dict]:
    return [event for event in events if event['event'] == 'TARGET_THROW'
            and event['marker'] == THROWS[case_id]
            and event['actorKey'].startswith('JETTY/')
            and event['sourceKey'].startswith('SOLR/SUBSHARD/collection1/shard1_')
            and 'org.apache.solr.common.SolrException' in event['detail']]


def target_actor_map(events: list[dict]) -> dict[str, str]:
    mapping = {}
    for case_id in GUARDS:
        for event in guard_events(events, case_id):
            child = event['sourceKey']
            require(child not in mapping or mapping[child] == event['actorKey'],
                    'healthy child moved between server actors')
            mapping[child] = event['actorKey']
    require(bool(mapping), 'no healthy target guard')
    return mapping


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def audit_attempt(directory: Path, sequence: list[dict], target_map: dict) -> dict:
    meta = json.loads((directory / 'run.json').read_text())
    events = load_events(directory)
    identity = raw_binding_check(events)
    require(meta['agent_sha256'] == sha(AGENT), f'agent mismatch {directory}')
    require(meta['original_source_revision'] == source_provenance()['revision'],
            f'original source mismatch {directory}')
    require(meta['test'] == 'org.apache.solr.cloud.api.collections.ShardSplitTest#test',
            f'wrong original test {directory}')
    require(not meta['classpath_contains_graphchecker'], f'nonbaseline classpath {directory}')
    require([event['seq'] for event in events] == list(range(1, len(events) + 1)),
            f'nonmonotone event sequence {directory}')
    applied = [event for event in events if event['event'] == 'IO_OBSERVED' and event['applied']]
    require(len(applied) <= len(sequence), f'excess applied faults {directory}')
    require(all(raw_point(event) == item
                for event, item in zip(applied, sequence)),
            f'wrong actor/session fault step {directory}')
    summaries = [event for event in events if event['event'] == 'SUMMARY']
    require(len(summaries) == 1 and summaries[0]['detail'] ==
            f'applied={len(applied)}/{len(sequence)}', f'summary mismatch {directory}')
    last = applied[-1]['seq'] if applied else -1
    strict = len(applied) == len(sequence)
    per_case = {}
    for case_id in GUARDS:
        guards = [event for event in guard_events(events, case_id)
                  if target_map.get(event['sourceKey']) == event['actorKey']]
        throws = [event for event in throw_events(events, case_id)
                  if target_map.get(event['sourceKey']) == event['actorKey']]
        per_case[case_id] = {
            'guard_count': len(guards),
            'post_fault_guard_count': sum(event['seq'] > last for event in guards) if strict else 0,
            'exact_throw_count': len(throws),
            'post_fault_exact_throw_count': sum(event['seq'] > last for event in throws)
            if strict else 0,
        }
    return {
        'attempt_dir': str(directory),
        'trace_sha256': sha(directory / 'events.jsonl'),
        'console_sha256': sha(directory / 'console.log'),
        'jacoco_sha256': sha(directory / 'jacoco.exec') if (directory / 'jacoco.exec').is_file() else '',
        'elapsed_seconds': meta['elapsed_seconds'],
        'junit_exit': meta['exit_code'],
        'junit_gate': junit_gate((directory / 'console.log').read_text()),
        'applied_faults': len(applied),
        'strict_injection': strict,
        'raw_actor_session_audit': identity,
        'cases': per_case,
    }


def audit() -> tuple[dict, list[dict]]:
    state = json.loads((ROOT / 'state.json').read_text())
    require(state['schema_version'] == 3, 'wrong V2 checkpoint schema')
    require(state['agent_sha256'] == sha(AGENT), 'checkpoint agent SHA mismatch')
    require(state['runner_sha256'] == runner_hashes(), 'checkpoint runner SHA mismatch')
    receipt = HERE / 'source-provenance.json'
    require(state['source_provenance_sha256'] == sha(receipt), 'source receipt SHA mismatch')
    require(json.loads(receipt.read_text()) == source_provenance(),
            'live original source/JAR differs from healthy seeds')
    require(state['active'] is None, 'audit requires a completed trial boundary')
    seeds = []
    for directory in SEEDS:
        meta = json.loads((directory / 'run.json').read_text())
        events = load_events(directory)
        require(meta['exit_code'] == 0 and
                junit_gate((directory / 'console.log').read_text()) == (1, 0, 0),
                f'unhealthy original JUnit seed {directory}')
        require(meta['agent_sha256'] == sha(AGENT), f'healthy agent mismatch {directory}')
        raw_binding_check(events)
        seeds.append({'directory': str(directory), 'trace_sha256': sha(directory / 'events.jsonl'),
                      'target_actor_map': target_actor_map(events)})
    require(seeds[0]['target_actor_map'] == seeds[1]['target_actor_map'] ==
            state['target_actor_map'], 'healthy/fault target actor mismatch')
    require(state['seed_traces'] == [str(directory / 'events.jsonl') for directory in SEEDS],
            'checkpoint healthy trace paths mismatch')
    require(len(state['completed']) <= state['budget']['max_selected_plans'],
            'completed plans exceed selected cap')
    rows = []
    counts = {case_id: 0 for case_id in GUARDS}
    for number, ledger in enumerate(state['completed'], 1):
        require(ledger['trial_number'] == number, f'ledger number gap at {number}')
        sequence = ledger['fault_sequence']
        require(1 <= len(sequence) <= state['budget']['max_faults'],
                f'fault length exceeds budget at {number}')
        trial_dir = Path(ledger['trace']).parent.parent
        require(trial_dir.name.startswith(f'{number:04d}-'),
                f'trial directory mismatch at {number}')
        plan = (trial_dir / 'fault.properties').read_text()
        require(plan.startswith(f'count={len(sequence)}\n'), f'fault plan count mismatch {number}')
        for index, item in enumerate(sequence, 1):
            for field, value in item.items():
                require(f'step.{index}.{field}={value}\n' in plan,
                        f'fault plan {number} step {index} {field} mismatch')
        attempts = [audit_attempt(trial_dir / f'attempt-{attempt:02d}', sequence,
                                  state['target_actor_map'])
                    for attempt in range(1, ledger['attempts'] + 1)]
        final = attempts[-1]
        require(final['strict_injection'] == ledger['strict_injection'] and
                final['applied_faults'] == ledger['applied_faults'],
                f'fault receipt/ledger mismatch {number}')
        require(abs(sum(item['elapsed_seconds'] for item in attempts) -
                    ledger['elapsed_seconds']) < 0.01, f'elapsed time mismatch {number}')
        require(ledger['raw_actor_session_audit'] == final['raw_actor_session_audit'],
                f'raw identity receipt mismatch {number}')
        require(ledger['target_preserved'] ==
                (final['strict_injection'] and all(
                    final['cases'][case_id]['post_fault_guard_count'] > 0
                    for case_id in GUARDS)), f'joint target feedback mismatch {number}')
        for case_id in GUARDS:
            case = final['cases'][case_id]
            require(ledger['target_guard_after_last_fault'][case_id] ==
                    case['post_fault_guard_count'], f'post-fault guard mismatch {number} {case_id}')
            require(ledger['exact_target_throw_after_last_fault'][case_id] ==
                    case['post_fault_exact_throw_count'], f'target throw mismatch {number} {case_id}')
            effective = final['strict_injection'] and case['post_fault_guard_count'] > 0
            counts[case_id] += effective
            rows.append({'case_id': case_id, 'trial_number': number,
                         'attempts': len(attempts),
                         'elapsed_seconds': ledger['elapsed_seconds'],
                         'planned_faults': len(sequence),
                         'applied_faults': final['applied_faults'],
                         'strict_injection': final['strict_injection'],
                         'target_guard_after_last_fault': case['post_fault_guard_count'],
                         'exact_target_throw_after_last_fault': case['post_fault_exact_throw_count'],
                         'effective': effective, 'new_production_probes': ledger['new_production_probes']
                         if ledger['target_preserved'] else 0,
                         'new_io_families': ledger['new_io_families']
                         if ledger['target_preserved'] else 0,
                         'status': ledger['status'],
                         'trace_sha256': final['trace_sha256']})
    require(all(counts[case_id] == sum(row['effective'] for row in rows
                                      if row['case_id'] == case_id) for case_id in GUARDS),
            'effective count mismatch')
    return {
        'method': 'independent raw event, plan, original JUnit and checkpoint audit',
        'agent_sha256': sha(AGENT), 'source_provenance_sha256': sha(receipt),
        'status': state['status'], 'budget': state['budget'],
        'selected_plans': len(state['completed']),
        'total_attempts': sum(row['attempts'] for row in state['completed']),
        'effective_trials': counts,
        'target_exception_candidate_trials': {
            case_id: sum(row['effective'] and row['exact_target_throw_after_last_fault'] > 0
                         for row in rows if row['case_id'] == case_id)
            for case_id in GUARDS},
        'healthy_runs': seeds,
        'raw_trial_trace_sha256': {str(row['trial_number']): row['trace_sha256']
                                   for row in rows if row['case_id'] == 'SOLR-36'},
    }, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', action='store_true', help='archive raw files after terminal audit')
    args = parser.parse_args()
    report, rows = audit()
    evidence = HERE / 'evidence'
    evidence.mkdir(exist_ok=True)
    csv_path = evidence / 'trial-times.csv'
    with csv_path.open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else
                                ['case_id', 'trial_number'])
        writer.writeheader()
        writer.writerows(rows)
    report['trial_table_sha256'] = sha(csv_path)
    if args.archive:
        require(report['status'] != 'running', 'raw archive requires terminal campaign')
        archive = evidence / 'raw-runs.tar.gz'
        files = [HERE / 'source-provenance.json', HERE / 'calibration-receipt.json',
                 HERE / 'agent-build.json', AGENT, ROOT / 'state.json']
        for directory in (*SEEDS, ROOT / 'trials'):
            files.extend(path for path in directory.rglob('*') if path.is_file())
        with tarfile.open(archive, 'w:gz') as tar:
            for path in sorted(set(files)):
                tar.add(path, arcname=str(path.relative_to(HERE)))
        report['raw_archive'] = str(archive)
        report['raw_archive_sha256'] = sha(archive)
    (evidence / 'terminal-audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({name: report[name] for name in
                      ('status', 'selected_plans', 'total_attempts', 'effective_trials')},
                     sort_keys=True))


if __name__ == '__main__':
    main()
