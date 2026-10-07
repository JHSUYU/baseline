#!/usr/bin/env python3
"""Offline checks for the pilot-to-targeted HTTP scheduler migration."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import fuzz_rpc


def selected(ordinal: int, marker: str = 'FAULT:HTTP:parentForwardAdd') -> dict:
    return {'marker': marker,
            'siteId': 'SolrCmdDistributor.submit#L309',
            'senderKey': 'SOLR/PARENT_LEADER/collection1/shard1',
            'sourceKey': 'SOLR/SUBSHARD/collection1/shard1_0/core_node11',
            'resource': '/update/Add/collection1/shard1_0/core_node11',
            'hitOrdinal': ordinal}


class TimeoutStage2Test(unittest.TestCase):
    def test_fourth_selection_keeps_delay_exploration(self) -> None:
        point = selected(1)
        queue = [{'id': mode.lower(), 'sequence': [fuzz_rpc.step(point, mode)],
                  'parent_gain': 0, 'created_after': 0}
                 for mode in ('TIMEOUT', 'DELAY')]
        row = {'last_fault_sender': point['senderKey'],
               'last_fault_source': point['sourceKey'],
               'last_fault_marker': point['marker'],
               'last_fault_mode': 'DELAY',
               'last_fault_point_id': fuzz_rpc.point_id(point)}
        for completed, expected in ((24, 'TIMEOUT'), (27, 'DELAY')):
            state = {'completed': [row] * completed, 'queue': copy.deepcopy(queue)}
            actual = fuzz_rpc.choose(state)
            self.assertEqual(actual['sequence'][-1]['fault_mode'], expected)
            self.assertEqual(len(state['queue']), 1)

    def test_postfault_range_guard_enables_next_timeout(self) -> None:
        first = selected(1)
        later = dict(selected(2), seq=20, event='IO_OBSERVED', applied=False)
        parent = [fuzz_rpc.step(first, 'TIMEOUT')]
        result = {'strict_injection': True, 'fault_effect_boundary_seq': 10,
                  'postfault_same_child_guards': {'SOLR-36': 1, 'SOLR-37': 1}}
        state = {'budget': {'max_faults': 8}, 'queue': [],
                 'seen_sequences': [], 'completed': []}
        with patch.object(fuzz_rpc, 'load_events', return_value=[later]):
            fuzz_rpc.mutate(state, parent, None, result, 2, set())
        self.assertEqual({entry['sequence'][-1]['fault_mode']
                          for entry in state['queue']}, {'TIMEOUT', 'DELAY'})
        self.assertTrue(all(len(entry['sequence']) == 2 for entry in state['queue']))
        result['postfault_same_child_guards']['SOLR-37'] = 0
        empty = {'budget': {'max_faults': 8}, 'queue': [],
                 'seen_sequences': [], 'completed': []}
        with patch.object(fuzz_rpc, 'load_events', return_value=[later]):
            fuzz_rpc.mutate(empty, parent, None, result, 2, set())
        self.assertEqual([entry['sequence'][-1]['fault_mode']
                          for entry in empty['queue']], ['DELAY'])


if __name__ == '__main__':
    unittest.main()
