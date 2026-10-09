"""A DELAY target reach counts only after its HTTP fault effect."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fuzz_rpc


CHILD = 'SOLR/SUBSHARD/collection1/shard1_0/core_node11'
PARENT = 'SOLR/PARENT/collection1/shard1/core_node3'
ROLE = 'SOLR/PARENT_LEADER/collection1/shard1'


def point_event(seq: int, event: str) -> dict:
    return {'seq': seq, 'event': event,
            'identityVersion': 'ROLE_VERIFIED_NONLAZY_V2',
            'marker': 'FAULT:HTTP:parentForwardAdd',
            'siteId': 'SolrCmdDistributor.submit#L309',
            'senderKey': ROLE, 'senderActorKey': PARENT,
            'leaderActorKey': PARENT, 'senderPhysicalNode': 'node3',
            'sourceKey': CHILD, 'physicalNode': 'http://child',
            'resource': '/update/Add/collection1/shard1_0/core_node11',
            'hitOrdinal': 16, 'applied': True,
            'detail': 'delayMs=5000;sent=next' if event == 'FAULT_EFFECT' else ''}


def guard(seq: int) -> dict:
    return {'seq': seq, 'event': 'TARGET_CHECK',
            'marker': 'SOLR36:ACTIVE_SUBSHARD_GUARD',
            'sourceKey': CHILD, 'detail': 'state=active;phase=FROMLEADER'}


class FaultEffectTest(unittest.TestCase):
    def analyze(self, guards: list[int], *, include_effect: bool = True) -> dict:
        events = [point_event(10, 'IO_OBSERVED'), *(guard(n) for n in guards)]
        if include_effect:
            events.append(point_event(12, 'FAULT_EFFECT'))
        events.append({'seq': 30, 'event': 'SUMMARY', 'detail': 'applied=1/1'})
        events.sort(key=lambda event: event['seq'])
        with tempfile.TemporaryDirectory(prefix='solr-role-effect-') as scratch:
            directory = Path(scratch)
            (directory / 'events.jsonl').write_text(
                ''.join(json.dumps(event) + '\n' for event in events))
            (directory / 'run.json').write_text(json.dumps(
                {'elapsed_seconds': 1.0, 'exit_code': 0}))
            (directory / 'console.log').write_text('')
            sequence = [fuzz_rpc.step(fuzz_rpc.point(events[0]), 'DELAY', 5000)]
            with patch.object(fuzz_rpc, 'junit_gate', return_value=(1, 0, 0)):
                result, _, _ = fuzz_rpc.analyze(
                    directory, sequence,
                    {'covered_probes': [], 'observed_rpc_selectors': []})
            return result

    def test_guard_during_delay_does_not_count(self) -> None:
        result = self.analyze([11])
        self.assertTrue(result['strict_injection'])
        self.assertEqual(result['fault_effect_boundary_seq'], 12)
        self.assertEqual(result['postfault_same_child_guards']['SOLR-36'], 0)

    def test_guard_after_effect_counts(self) -> None:
        result = self.analyze([11, 13])
        self.assertEqual(result['postfault_same_child_guards']['SOLR-36'], 1)

    def test_missing_delay_effect_is_not_strict(self) -> None:
        result = self.analyze([13], include_effect=False)
        self.assertFalse(result['strict_injection'])
        self.assertEqual(result['postfault_same_child_guards']['SOLR-36'], 0)

    def test_reviewed_rejection_requires_exact_active_branch_and_success(self) -> None:
        check = {'seq': 20, 'event': 'TARGET_CHECK',
                 'marker': 'SOLR36:ACTIVE_SUBSHARD_GUARD',
                 'siteId': 'DistributedZkUpdateProcessor.java:986',
                 'sourceKey': CHILD, 'threadId': 7, 'physicalNode': 'node3',
                 'detail': 'state=active;phase=FROMLEADER'}
        thrown = {'seq': 21, 'event': 'TARGET_THROW',
                  'marker': 'SOLR36:ACTIVE_SUBSHARD_THROW',
                  'siteId': 'DistributedZkUpdateProcessor.java:987',
                  'sourceKey': CHILD, 'threadId': 7, 'physicalNode': 'node3',
                  'detail': fuzz_rpc.REVIEWED_SOLR36_THROW}
        self.assertTrue(fuzz_rpc.reviewed_protective_rejection(
            [check, thrown], CHILD, 12, (1, 0, 0), 0))
        self.assertFalse(fuzz_rpc.reviewed_protective_rejection(
            [check, thrown], CHILD, 12, (1, 0, 1), 0))
        self.assertFalse(fuzz_rpc.reviewed_protective_rejection(
            [check, thrown], CHILD, 20, (1, 0, 0), 0))
        self.assertFalse(fuzz_rpc.reviewed_protective_rejection(
            [check, {**thrown, 'detail': 'different exception'}],
            CHILD, 12, (1, 0, 0), 0))
        self.assertFalse(fuzz_rpc.reviewed_protective_rejection(
            [check, {**thrown, 'threadId': 8}], CHILD, 12, (1, 0, 0), 0))


if __name__ == '__main__':
    unittest.main()
