#!/usr/bin/env python3
"""Re-audit raw actor-V2 trials and write the case ledger and stopping evidence."""

import hashlib
import json
import re
import socket
from pathlib import Path

from build import HERE, EXPECTED_REVISION, EXPECTED_TEST_SHA256, SOURCE
from fuzz_v2 import (ACTOR, GUARD, TARGET, THROW, family, point, point_id,
                     validate_actor_trace)

ROOT = HERE / 'campaign'
JUNIT = re.compile(r'SOLR_COORD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main():
    state = json.loads((ROOT / 'state.json').read_text())
    if state['status'] != 'budget_complete':
        raise RuntimeError(f'campaign incomplete: {state["status"]}')
    agent = json.loads((HERE / 'agent-build.json').read_text())['agent_sha256']
    if sha(HERE / 'solrcoord-actor-v2-agent.jar') != agent:
        raise RuntimeError('agent jar changed')
    test = SOURCE / 'solr/core/src/test/org/apache/solr/search/TestCoordinatorRole.java'
    if sha(test) != EXPECTED_TEST_SHA256:
        raise RuntimeError('original JUnit changed')
    base_families = set()
    for name in ('healthy-01', 'healthy-02', 'node2-healthy-01', 'node2-healthy-02'):
        path = HERE / name / 'events.jsonl'
        if not path.is_file():
            raise RuntimeError(f'missing healthy trace: {name}')
        for row in events(path):
            if row['event'] == 'IO_OBSERVED' and row['actorKey'] == ACTOR:
                base_families.add(family(point(row)))
    observed_families = set(base_families)
    ledger = []
    for row in state['completed']:
        number = row['trial_number']
        out = Path(row['trace']).parent
        run = json.loads((out / 'run.json').read_text())
        raw = events(out / 'events.jsonl')
        binding = validate_actor_trace(raw)
        applied = [event for event in raw if event['event'] == 'IO_OBSERVED' and event['applied']]
        planned = row['fault_sequence']
        strict = len(applied) == len(planned) and all(point_id(point(actual)) == point_id(wanted)
            for actual, wanted in zip(applied, planned))
        summaries = [event for event in raw if event['event'] == 'SUMMARY']
        strict = strict and len(summaries) == 1 and summaries[0]['detail'] == \
            f'applied={len(planned)}/{len(planned)}'
        if strict != row['strict_injection'] or len(planned) > state['budget']['max_faults']:
            raise RuntimeError(f'strict fault mismatch trial {number}')
        last = applied[-1]['seq'] if applied else -1
        guards = [event for event in raw if event['event'] == 'TARGET_CHECK'
                  and event['marker'] == GUARD and event['sourceKey'] == TARGET
                  and event['actorKey'] == ACTOR and event['seq'] > last]
        target_throws = [event for event in raw if event['event'] == 'TARGET_THROW'
                         and event['marker'] == THROW and event['sourceKey'] == TARGET
                         and event['actorKey'] == ACTOR and event['seq'] > last]
        gate = JUNIT.search((out / 'console.log').read_text())
        junit = list(map(int, gate.groups())) if gate else None
        if run['agent_sha256'] != agent or run['classpath_contains_graphchecker'] or \
           run['original_source_revision'] != EXPECTED_REVISION:
            raise RuntimeError(f'original test/agent gate failed trial {number}')
        effective = strict and bool(guards or target_throws)
        if effective != row['effective']:
            raise RuntimeError(f'effective gate mismatch trial {number}')
        host = row.get('execution_host') or 'node2.baseline.silentfailure-pg0.utah.cloudlab.us'
        if number <= 15 and not host.startswith('node0.'):
            raise RuntimeError(f'node0 phase mislabeled trial {number}')
        if number >= 16 and not host.startswith('node2.'):
            raise RuntimeError(f'node2 phase mislabeled trial {number}')
        if target_throws:
            raise RuntimeError(f'exact target candidate requires clean replay: trial {number}')
        trial_families = {family(point(event)) for event in raw if event['event'] == 'IO_OBSERVED'
                          and event['actorKey'] == ACTOR}
        new_families = len(trial_families - observed_families) if effective else 0
        if effective:
            observed_families |= trial_families
        ledger.append({'trial_number': number, 'execution_host': host,
                       'status': row['status'], 'effective': effective,
                       'elapsed_seconds': row['elapsed_seconds'],
                       'elapsed_includes_runner_sigstop': number == 53,
                       'attempts': row['attempts'],
                       'planned_faults': len(planned), 'applied_faults': len(applied),
                       'strict_same_client_injection': strict,
                       'postfinal_exact_guard_count': len(guards),
                       'postfinal_exact_target_throw_count': len(target_throws),
                       'original_junit': junit, 'junit_exit': run['exit_code'],
                       'physical_node': binding['physicalNode'],
                       'client_identity': binding['clientIdentity'],
                       'new_production_probes': row['new_production_probes'],
                       'new_actor_io_families': new_families,
                       'fault_sequence': planned,
                       'trace_sha256': sha(out / 'events.jsonl'),
                       'jacoco_sha256': sha(out / 'jacoco.exec')})
    effective_rows = [row for row in ledger if row['effective']]
    if len(effective_rows) < state['budget']['max_trials']:
        raise RuntimeError('effective trial budget not met')
    last20 = effective_rows[-20:]
    novel_last20 = sum(row['new_production_probes'] + row['new_actor_io_families']
                       for row in last20)
    boundary80 = ROOT / 'state-at-80.json'
    base80_novelty = None
    if boundary80.is_file():
        first_phase = json.loads(boundary80.read_text())
        first_effective = [row for row in first_phase['completed'] if row['effective']]
        if len(first_effective) != 80:
            raise RuntimeError('80-trial boundary does not contain 80 effective trials')
        base80_novelty = sum(row['new_production_probes'] + row['new_io_families']
                             for row in first_effective[-20:])
    report = {'case_id': 'SOLR-34', 'test': 'TestCoordinatorRole.testSimple',
              'source_revision': EXPECTED_REVISION,
              'original_test_sha256': EXPECTED_TEST_SHA256,
              'agent_sha256': agent,
              'budget': state['budget'],
              'selected_trials': len(ledger),
              'effective_trials': len(effective_rows),
              'strict_injections': sum(row['strict_same_client_injection'] for row in ledger),
              'postfinal_guard_trials': sum(row['postfinal_exact_guard_count'] > 0 for row in effective_rows),
              'exact_target_throw_trials': sum(row['postfinal_exact_target_throw_count'] > 0 for row in effective_rows),
              'original_junit_passes': sum(row['original_junit'] == [1, 0, 0] and row['junit_exit'] == 0
                                           for row in ledger),
              'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in ledger), 3),
              'actor_io_family_gain': len(observed_families - base_families),
              'last20_effective_novel_probes_or_io_families': novel_last20,
              'base80_last20_novel_probes_or_io_families': base80_novelty,
              'extend_to_128_max10': novel_last20 > 0,
              'node0_completed_trial_numbers': [row['trial_number'] for row in ledger
                                                 if row['execution_host'].startswith('node0.')],
              'node2_completed_trial_numbers': [row['trial_number'] for row in ledger
                                                 if row['execution_host'].startswith('node2.')],
              'node0_orphan_trial16': 'archived and uncounted; same plan re-executed on node2',
              'node2_trial53_timing_note': 'runner SIGSTOP interval is included in trial 53 elapsed seconds',
              'audit_host': socket.gethostname()}
    (ROOT / 'trial-ledger-v2.json').write_text(json.dumps(ledger, indent=2, sort_keys=True) + '\n')
    (ROOT / 'summary-v2.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
