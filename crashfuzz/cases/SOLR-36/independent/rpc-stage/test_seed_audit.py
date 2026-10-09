#!/usr/bin/env python3
"""Exact parent leader selection across unchanged JUnit healthy attempts."""

import json
import unittest

from seed_audit import role_receipt_valid, stable_pair


def selectors(sender: str) -> set[str]:
    return {json.dumps({'marker': marker, 'senderKey': sender,
                        'sourceKey': child}, sort_keys=True)
            for marker in ('FAULT:HTTP:parentForwardAdd',
                           'FAULT:HTTP:parentForwardDeleteById')
            for child in ('SOLR/SUBSHARD/collection1/shard1_0/core_node11',
                          'SOLR/SUBSHARD/collection1/shard1_1/core_node12')}


class SeedPairTest(unittest.TestCase):
    def test_current_leader_role_pairs_across_raw_replicas(self) -> None:
        role = 'SOLR/PARENT_LEADER/collection1/shard1'
        self.assertEqual(stable_pair([selectors(role), selectors(role)]),
                         (0, 1, selectors(role)))

    def test_raw_receipt_requires_actual_unique_leader(self) -> None:
        event = {'identityVersion': 'ROLE_VERIFIED_NONLAZY_V2',
                 'senderKey': 'SOLR/PARENT_LEADER/collection1/shard1',
                 'senderActorKey': 'SOLR/PARENT/collection1/shard1/core_node4',
                 'leaderActorKey': 'SOLR/PARENT/collection1/shard1/core_node4',
                 'senderPhysicalNode': 'node4', 'physicalNode': 'http://node11'}
        self.assertTrue(role_receipt_valid(event))
        event['leaderActorKey'] = 'SOLR/PARENT/collection1/shard1/core_node3'
        self.assertFalse(role_receipt_valid(event))

    def test_missing_delete_or_child_does_not_pair(self) -> None:
        complete = selectors('SOLR/PARENT_LEADER/collection1/shard1')
        add_only = {item for item in complete
                    if json.loads(item)['marker'].endswith('Add')}
        self.assertIsNone(stable_pair([complete, add_only]))


if __name__ == '__main__':
    unittest.main()
