#!/usr/bin/env python3
"""Independently recheck completed node0 trials before moving the checkpoint."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from build import HERE
from fuzz_v2 import ACTOR, GUARD, TARGET, THROW, point, point_id, validate_actor_trace

JUNIT = re.compile(r'SOLR_COORD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)')
ROOT = HERE / 'campaign'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    state = json.loads((ROOT / 'state.json').read_text())
    expected_agent = json.loads((HERE / 'agent-build.json').read_text())['agent_sha256']
    rows = []
    for trial in state['completed']:
        number = trial['trial_number']
        out = Path(trial['trace']).parent
        raw = [json.loads(line) for line in (out / 'events.jsonl').read_text().splitlines()]
        binding = validate_actor_trace(raw)
        applied = [event for event in raw if event['event'] == 'IO_OBSERVED' and event['applied']]
        planned = trial['fault_sequence']
        if len(applied) != len(planned) or any(point_id(point(row)) != point_id(plan)
                                                   for row, plan in zip(applied, planned)):
            raise RuntimeError(f'planned/applied mismatch trial {number}')
        if not all(event['actorKey'] == ACTOR and event['physicalNode'] == binding['physicalNode']
                   for event in applied):
            raise RuntimeError(f'actor mismatch trial {number}')
        guard = [event for event in raw if event['event'] == 'TARGET_CHECK'
                 and event['marker'] == GUARD and event['sourceKey'] == TARGET
                 and event['actorKey'] == ACTOR and event['seq'] > applied[-1]['seq']]
        throws = [event for event in raw if event['event'] == 'TARGET_THROW'
                  and event['marker'] == THROW]
        run = json.loads((out / 'run.json').read_text())
        match = JUNIT.search((out / 'console.log').read_text())
        if (not guard or throws or run['exit_code'] != 0 or
            run['agent_sha256'] != expected_agent or
            run['classpath_contains_graphchecker'] or match is None or
            tuple(map(int, match.groups())) != (1, 0, 0)):
            raise RuntimeError(f'postfault/JUnit gate failed trial {number}')
        if not trial['effective'] or not trial['strict_injection']:
            raise RuntimeError(f'checkpoint non-effective trial {number}')
        ended = (out / 'run.json').stat().st_mtime
        rows.append({'trial_number': number, 'host': 'node0',
                     'ended_utc': datetime.fromtimestamp(ended, timezone.utc).isoformat(),
                     'elapsed_seconds': run['elapsed_seconds'],
                     'planned_faults': len(planned), 'applied_faults': len(applied),
                     'target_guard_after_last_fault': len(guard),
                     'exact_target_throws': len(throws),
                     'original_junit': [1, 0, 0],
                     'physical_node': binding['physicalNode'],
                     'trace_sha256': sha(out / 'events.jsonl'),
                     'jacoco_sha256': sha(out / 'jacoco.exec'),
                     'run_receipt_sha256': sha(out / 'run.json')})
    orphan = ROOT / 'trials' / '0016-ba50e228e0eaabf515d1' / 'attempt-01'
    orphan_meta = {'trial_number': 16, 'host': 'node0',
                   'status': 'orphan_raw_uncounted',
                   'reason': 'node0 runner stopped after child JUnit exit before run.json/audit',
                   'console_junit': JUNIT.search((orphan / 'console.log').read_text()).groups()
                      if (orphan / 'console.log').exists() and
                         JUNIT.search((orphan / 'console.log').read_text()) else None,
                   'run_receipt_present': (orphan / 'run.json').exists(),
                   'trace_sha256': sha(orphan / 'events.jsonl') if
                       (orphan / 'events.jsonl').exists() else None}
    report = {'case_id': 'SOLR-34', 'host': 'node0',
              'completed_effective_count': len(rows), 'trials': rows,
              'orphan': orphan_meta,
              'resource_overlap': {
                  'workload': 'HBASE-32 upstream s101 on node0',
                  'evidence': '/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32/work-upstream/logs/s101.thread-dump-200s.txt',
                  'observation': 's101 200-second thread dump was written at 2026-10-07 06:01:02 UTC, within SOLR-34 node0 trials 1–15 (approximately 05:58–06:03 UTC).'
              }}
    (HERE / 'node0-phase-audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'completed_effective_count': len(rows),
                      'orphan_run_receipt_present': orphan_meta['run_receipt_present']},
                     sort_keys=True))


if __name__ == '__main__':
    main()
