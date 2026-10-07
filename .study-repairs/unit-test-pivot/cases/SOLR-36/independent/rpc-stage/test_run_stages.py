#!/usr/bin/env python3
"""No-JVM checkpoint tests for HTTP pilot, extension, and replay guards."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import fuzz_rpc
import run_stages as stages


def row(number: int, *, strict: bool = True, reached: bool = True) -> dict:
    return {
        'trial_number': number, 'selected_queue_id': f'unique-{number}',
        'attempts': 1 if strict else 2, 'strict_injection': strict,
        'postfault_same_child_guards': {
            case_id: int(strict and reached) for case_id in stages.CHECKS},
        'elapsed_seconds': 1.25, 'planned_faults': 1,
        'new_production_probes': 0, 'new_exact_rpc_selectors': 0,
        'trace': f'/synthetic/trial-{number}/events.jsonl',
    }


def checkpoint(root: Path, rows: list[dict], *, status: str,
               cap: int, faults: int, active: dict | None = None,
               queue: list | None = None) -> dict:
    state = {'status': status,
             'budget': {'max_trials': cap, 'max_faults': faults},
             'completed': rows, 'active': active,
             'queue': ['remaining'] if queue is None else queue}
    (root / 'state.json').write_text(json.dumps(state))
    return state


NO_NOVELTY = lambda state: {'extend': False,
                            'last_effective_trial_numbers': [],
                            'production_probe_gain_trial_numbers': [],
                            'stable_new_rpc_selector_count': 0,
                            'stable_new_rpc_selector_ids': []}


class StageCheckpointTest(unittest.TestCase):
    def test_parent_sender_is_part_of_exact_http_plan(self) -> None:
        event = {'marker': 'FAULT:HTTP:parentForwardAdd',
                 'siteId': 'SolrCmdDistributor.submit#L309',
                 'senderKey': 'SOLR/PARENT/collection1/shard1/core_node3',
                 'sourceKey': 'SOLR/SUBSHARD/collection1/shard1_0/core_node11',
                 'resource': '/update/Add/collection1/shard1_0/core_node11',
                 'hitOrdinal': 1}
        selected = fuzz_rpc.point(event)
        migrated = dict(event, senderKey='SOLR/PARENT/collection1/shard1/core_node4')
        self.assertNotEqual(fuzz_rpc.point_id(selected),
                            fuzz_rpc.point_id(fuzz_rpc.point(migrated)))
        with tempfile.TemporaryDirectory(prefix='solr-http-sender-') as scratch:
            plan = Path(scratch) / 'fault.properties'
            fuzz_rpc.write_plan(plan, [fuzz_rpc.step(selected, 'TIMEOUT')])
            self.assertIn('step.1.senderKey=' + selected['senderKey'],
                          plan.read_text())

    def test_pilot_monotonically_reaches_80_effective(self) -> None:
        with tempfile.TemporaryDirectory(prefix='solr-http-stage-') as scratch:
            root = Path(scratch)
            calls = []
            def fake_runner(cap: int, faults: int) -> None:
                calls.append((cap, faults))
                state = (json.loads((root / 'state.json').read_text())
                         if (root / 'state.json').exists() else None)
                rows = [] if state is None else state['completed']
                before = [item['selected_queue_id'] for item in rows]
                for number in range(len(rows) + 1, cap + 1):
                    rows.append(row(number,
                                    strict=number not in (3, 4, 30, 31),
                                    reached=number not in (5, 6, 32, 33, 34)))
                self.assertEqual(before, [item['selected_queue_id']
                                          for item in rows[:len(before)]])
                checkpoint(root, rows, status='budget_complete',
                           cap=cap, faults=faults)
            report = stages.campaign(root, runner=fake_runner,
                                     novelty_fn=NO_NOVELTY)
            self.assertEqual(calls, [(24, 2), (80, 8), (97, 8)])
            self.assertEqual(report['status'], 'complete')
            self.assertEqual(report['counts']['selected_plans'], 97)
            self.assertEqual(report['counts']['attempted_junits'], 101)
            self.assertEqual(report['counts']['strict_injections'], 93)
            self.assertEqual(report['counts']['effective_by_case'],
                             {'SOLR-36': 88, 'SOLR-37': 88})
            self.assertEqual(len({item['selected_queue_id'] for item in
                                  json.loads((root / 'state.json').read_text())['completed']}), 97)

    def test_exact_target_candidate_stops_at_pilot(self) -> None:
        with tempfile.TemporaryDirectory(prefix='solr-http-candidate-') as scratch:
            root = Path(scratch)
            calls = []
            def fake_runner(cap: int, faults: int) -> None:
                calls.append((cap, faults))
                checkpoint(root, [row(i) for i in range(1, 25)],
                           status='candidate_target_exception',
                           cap=cap, faults=faults)
            report = stages.campaign(root, runner=fake_runner,
                                     novelty_fn=NO_NOVELTY)
            self.assertEqual(calls, [(24, 2)])
            self.assertEqual(report['status'], 'candidate')

    def test_restart_keeps_active_plan_and_completed_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix='solr-http-resume-') as scratch:
            root = Path(scratch)
            old = [row(i) for i in range(1, 25)]
            checkpoint(root, old, status='running', cap=80, faults=8,
                       active={'id': 'plan-25'})
            calls = []
            def fake_runner(cap: int, faults: int) -> None:
                state = json.loads((root / 'state.json').read_text())
                calls.append((cap, faults, state['active']['id']))
                rows = state['completed']
                rows.extend(row(i) for i in range(25, 81))
                checkpoint(root, rows, status='budget_complete',
                           cap=cap, faults=faults, active=None)
            report = stages.campaign(root, runner=fake_runner,
                                     novelty_fn=NO_NOVELTY)
            self.assertEqual(calls, [(80, 8, 'plan-25')])
            self.assertEqual(report['status'], 'complete')
            self.assertEqual([item['selected_queue_id'] for item in old],
                             [f'unique-{i}' for i in range(1, 25)])

    def test_late_novelty_and_real_exhaustion(self) -> None:
        rows = [row(i) for i in range(1, 81)]
        state = {'status': 'budget_complete', 'completed': rows,
                 'budget': {'max_trials': 80, 'max_faults': 8},
                 'queue': ['remaining'], 'active': None}
        self.assertEqual(stages.decide(state, novel=True)[:3],
                         ('run', 128, 10))
        state['queue'] = []
        self.assertEqual(stages.decide(state, novel=True)[0], 'complete')
        state['completed'] = rows[:40]
        self.assertEqual(stages.decide(state)[0], 'queue_exhausted')


if __name__ == '__main__':
    unittest.main()
