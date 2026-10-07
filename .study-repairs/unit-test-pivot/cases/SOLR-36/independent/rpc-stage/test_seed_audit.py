#!/usr/bin/env python3
"""Exact parent leader selection across unchanged JUnit healthy attempts."""

import json
import unittest

from seed_audit import stable_pair


def selectors(sender: str) -> set[str]:
    return {json.dumps({'marker': marker, 'senderKey': sender,
                        'sourceKey': child}, sort_keys=True)
            for marker in ('FAULT:HTTP:parentForwardAdd',
                           'FAULT:HTTP:parentForwardDeleteById')
            for child in ('SOLR/SUBSHARD/collection1/shard1_0/core_node11',
                          'SOLR/SUBSHARD/collection1/shard1_1/core_node12')}


class SeedPairTest(unittest.TestCase):
    def test_different_raw_parent_leaders_do_not_pair(self) -> None:
        first = selectors('SOLR/PARENT/collection1/shard1/core_node4')
        second = selectors('SOLR/PARENT/collection1/shard1/core_node3')
        self.assertIsNone(stable_pair([first, second]))
        self.assertEqual(stable_pair([first, second, first]),
                         (0, 2, first))

    def test_missing_delete_or_child_does_not_pair(self) -> None:
        complete = selectors('SOLR/PARENT/collection1/shard1/core_node4')
        add_only = {item for item in complete
                    if json.loads(item)['marker'].endswith('Add')}
        self.assertIsNone(stable_pair([complete, add_only]))


if __name__ == '__main__':
    unittest.main()
