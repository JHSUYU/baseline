"""Offline admission-gate falsification tests; no HBase/JVM process."""

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from verify_healthy import CHECK, DOOR, EXCEPTION, HANDOFF, REGION, review


class HealthyGateTest(unittest.TestCase):
    def make_campaign(self, root, *, wrong_thread=False, wrong_token=False):
        campaign = Path(root)
        trial = campaign / 'trials/r0000'
        trial.mkdir(parents=True)
        node = 'zk-coordinator:unit'
        occurrence = f'{node}:0:{REGION}:task-token:1'
        events = [
            {'id': 'e1', 'seq': 1, 'type': 'TASK_SUBMIT', 'site': HANDOFF,
             'correlation': 'task-token', 'node': node, 'thread_id': 10},
            {'id': 'e2', 'seq': 2, 'type': 'TASK_CLAIM', 'site': HANDOFF,
             'correlation': 'task-token', 'node': node, 'thread_id': 11},
            {'id': 'e3', 'seq': 3, 'type': 'REGION_ENTER', 'site': REGION,
             'parent_id': 'wrong-token' if wrong_token else 'task-token',
             'occurrence': occurrence, 'node': node, 'thread_id': 11},
            {'id': 'e4', 'seq': 4, 'type': 'DOOR_OBSERVED', 'site': DOOR,
             'exception_class': EXCEPTION, 'occurrence': occurrence,
             'node': node, 'thread_id': 12 if wrong_thread else 11},
            {'id': 'e5', 'seq': 5, 'type': 'TARGET_CHECK', 'site': CHECK,
             'occurrence': occurrence, 'node': node, 'thread_id': 11},
        ]
        (campaign / 'result.json').write_text(json.dumps({
            'case_id': 'HBASE-23', 'status': 'calibration_complete',
            'fault_trials_completed': 0}))
        (trial / 'result.json').write_text(json.dumps({
            'junit_validation': {'status': 'passed'},
            'site_catalog_validation': {'valid': True},
            'feedback': {'target_reached': True, 'target_threw': False,
                         'trace_truncated': False,
                         'doors': [{'site': DOOR, 'exception_class': EXCEPTION,
                                    'in_closure': True, 'event_id': 'e4',
                                    'local_timeline_evidence': {
                                        'kind': 'observed_local_timeline',
                                        'door_event_id': 'e4',
                                        'target_check_event_id': 'e5'}}]}}))
        (campaign / 'offline-causal-audit.json').write_text(json.dumps({
            'case_id': 'HBASE-23', 'allow_local_timeline_doors': True,
            'healthy_local_timeline_doors': 1, 'healthy_closure_proven': True,
            'report_gate_passed': True,
            'healthy_observed_path_doors': 0,
            'healthy_local_timeline_evidence_sample': [
                {'door_event_id': 'e4', 'target_check_event_id': 'e5'}]}))
        with gzip.open(trial / 'events.jsonl.gz', 'wt') as stream:
            for event in events:
                stream.write(json.dumps(event) + '\n')
        return campaign

    def test_exact_local_sequence_admits_without_graph_edge(self):
        with tempfile.TemporaryDirectory() as root:
            result = review(self.make_campaign(root))
            self.assertEqual(result['status'], 'healthy_admitted')
            self.assertEqual(result['evidence_kind'], 'observed_local_timeline')
            self.assertEqual(result['strict_graph_path_doors'], 0)
            self.assertEqual(len(result['matched_witnesses']), 1)

    def test_other_thread_does_not_admit(self):
        with tempfile.TemporaryDirectory() as root:
            result = review(self.make_campaign(root, wrong_thread=True))
            self.assertEqual(result['status'], 'healthy_not_admitted')
            self.assertFalse(result['matched_witnesses'])

    def test_unmatched_worker_token_does_not_admit(self):
        with tempfile.TemporaryDirectory() as root:
            result = review(self.make_campaign(root, wrong_token=True))
            self.assertEqual(result['status'], 'healthy_not_admitted')
            self.assertFalse(result['matched_witnesses'])


if __name__ == '__main__':
    unittest.main()
