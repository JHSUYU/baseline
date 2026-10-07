#!/usr/bin/env python3
"""Offline checkpoint invariants for the child-source scheduler switch."""

from __future__ import annotations

import unittest

import fuzz_rpc
from migrate_child_balance import OLD_RUNNER_SHA, validated_update


class ChildBalanceMigrationTest(unittest.TestCase):
    def checkpoint(self) -> dict:
        source = 'SOLR/SUBSHARD/collection1/shard1_0/core_node11'
        rows = [{'selected_queue_id': f'done-{number}',
                 'last_fault_source': source} for number in range(80)]
        point = {'marker': 'FAULT:HTTP:parentForwardAdd',
                 'siteId': 'SolrCmdDistributor.submit#L309',
                 'senderKey': 'SOLR/PARENT_LEADER/collection1/shard1',
                 'sourceKey': 'SOLR/SUBSHARD/collection1/shard1_1/core_node12',
                 'resource': '/update/Add/collection1/shard1_1/core_node12',
                 'hitOrdinal': 3}
        return {
            'status': 'budget_complete',
            'budget': {'max_trials': 80, 'max_faults': 8},
            'active': None,
            'locks': {'rpc-stage/fuzz_rpc.py': OLD_RUNNER_SHA,
                      'rpc-stage/run.py': 'unchanged'},
            'completed': rows,
            'queue': [{'id': 'next', 'sequence': [fuzz_rpc.step(point, 'TIMEOUT')],
                       'parent_gain': 0, 'created_after': 80}],
            'seen_sequences': ['next'],
            'covered_probes': ['original-probe'],
            'observed_rpc_selectors': ['original-selector'],
        }

    def test_completed_checkpoint_keeps_all_evidence(self) -> None:
        before = self.checkpoint()
        updated = validated_update(before, {
            'rpc-stage/fuzz_rpc.py': 'new-scheduler',
            'rpc-stage/run.py': 'unchanged'})
        self.assertEqual(updated['locks']['rpc-stage/fuzz_rpc.py'], 'new-scheduler')
        for key in ('completed', 'queue', 'seen_sequences', 'covered_probes',
                    'observed_rpc_selectors', 'budget', 'active', 'status'):
            self.assertEqual(updated[key], before[key])
        self.assertEqual(before['locks']['rpc-stage/fuzz_rpc.py'], OLD_RUNNER_SHA)

    def test_rejects_inflight_or_changed_dependency(self) -> None:
        before = self.checkpoint()
        before['active'] = before['queue'][0]
        with self.assertRaisesRegex(RuntimeError, 'fully completed'):
            validated_update(before, {'rpc-stage/fuzz_rpc.py': 'new-scheduler',
                                      'rpc-stage/run.py': 'unchanged'})
        before['active'] = None
        with self.assertRaisesRegex(RuntimeError, 'dependency'):
            validated_update(before, {'rpc-stage/fuzz_rpc.py': 'new-scheduler',
                                      'rpc-stage/run.py': 'changed'})


if __name__ == '__main__':
    unittest.main()
