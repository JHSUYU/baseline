"""Regression for mutation toward an alias I/O identity with no selected guard."""

import json
from pathlib import Path
import tempfile
import unittest

from campaign import GUARD, mutate, select


GUARDED = 'SOLR/ROUTED_ALIAS/myalias/myalias__TRA__2017-10-25'
UNGUARDED = 'SOLR/ROUTED_ALIAS/myalias/myalias__TRA__2017-10-27'
SITE = ('org.apache.solr.common.cloud.ZkStateReader$AliasesManager.'
        'applyModificationAndExportToZk#L2259->SolrZkClient.lambda$setData$7')


def point(source, ordinal=1):
    return {'marker': 'FAULT:ZK_NATIVE:setData', 'siteId': SITE,
            'sourceKey': source, 'resource': '/aliases.json', 'hitOrdinal': ordinal}


class TargetSelectorTest(unittest.TestCase):
    def test_selection_defers_unwitnessed_source(self):
        state = {'observed_target_sources': [GUARDED], 'completed': [],
                 'queue': [{'id': 'unwitnessed', 'sequence': [point(UNGUARDED)],
                            'parent_gain': 99, 'created_after': 0},
                           {'id': 'witnessed', 'sequence': [point(GUARDED)],
                            'parent_gain': 0, 'created_after': 0}]}
        chosen = select(state)
        self.assertEqual('witnessed', chosen['id'])
        self.assertEqual(['unwitnessed'], [item['id'] for item in state['queue']])

    def test_mutation_requires_later_exact_source_guard(self):
        parent = point(GUARDED)
        rows = [{'event': 'IO_OBSERVED', 'seq': 1, 'applied': True, **parent},
                {'event': 'IO_OBSERVED', 'seq': 2, 'applied': False,
                 **point(GUARDED, 2)},
                {'event': 'IO_OBSERVED', 'seq': 3, 'applied': False, **point(UNGUARDED)},
                {'event': 'TARGET_CHECK', 'seq': 4, 'marker': GUARD,
                 'sourceKey': GUARDED}]
        state = {'budget': {'max_faults': 8}, 'queue': [],
                 'seen_sequences': [], 'completed': []}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / 'events.jsonl').write_text(
                ''.join(json.dumps(row) + '\n' for row in rows))
            mutate(state, [parent], out, 0)
        self.assertEqual(1, len(state['queue']))
        self.assertEqual(GUARDED, state['queue'][0]['sequence'][-1]['sourceKey'])


if __name__ == '__main__':
    unittest.main()
