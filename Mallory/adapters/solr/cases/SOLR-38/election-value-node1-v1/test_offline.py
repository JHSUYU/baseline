"""No JVM: value evidence never upgrades a sampled field edge."""

from __future__ import annotations

import unittest

from audit_healthy import value_witnesses


class ValueDiagnosticTest(unittest.TestCase):
    def test_missing_value_events_stays_empty(self) -> None:
        self.assertEqual(value_witnesses([]), [])

    def test_unrelated_object_stays_empty(self) -> None:
        target = ("org.apache.solr.update.processor.DistributedZkUpdateProcessor"
                  "#doDefensiveChecks(Lorg/apache/solr/update/processor/"
                  "DistributedUpdateProcessor$DistribPhase;)V@1021:branch:17")
        common = {"node": "node1", "epoch": 1, "thread_id": 7}
        rows = [
            {**common, "id": "d", "seq": 1, "type": "DOOR_OBSERVED",
             "site": "org.apache.solr.cloud.ShardLeaderElectionContext#waitForReplicasToComeUp(I)Z@396:door:1"},
            {**common, "id": "w", "seq": 2, "type": "STATE_WRITE",
             "site": "solr38:leader-value:write", "key": "solr38:isLeader=true",
             "object": "o1"},
            {**common, "id": "r", "seq": 3, "type": "STATE_READ",
             "site": "solr38:leader-value:read", "key": "solr38:isLeader=true",
             "object": "o2"},
            {**common, "id": "t", "seq": 4, "type": "TARGET_CHECK", "site": target},
        ]
        self.assertEqual(value_witnesses(rows), [])

    def test_same_value_and_object_remains_candidate(self) -> None:
        target = ("org.apache.solr.update.processor.DistributedZkUpdateProcessor"
                  "#doDefensiveChecks(Lorg/apache/solr/update/processor/"
                  "DistributedUpdateProcessor$DistribPhase;)V@1021:branch:17")
        common = {"node": "node1", "epoch": 1, "thread_id": 7,
                  "context": "test-context"}
        rows = [
            {**common, "id": "e1", "seq": 1, "type": "REGION_ENTER",
             "occurrence": "election", "region":
             "org.apache.solr.cloud.ShardLeaderElectionContext#runLeaderProcess(ZI)V"},
            {**common, "id": "d", "seq": 2, "type": "DOOR_OBSERVED",
             "occurrence": "election", "site":
             "org.apache.solr.cloud.ShardLeaderElectionContext#waitForReplicasToComeUp(I)Z@396:door:1"},
            {**common, "id": "w", "seq": 3, "type": "STATE_WRITE",
             "occurrence": "election", "site": "solr38:leader-value:write",
             "key": "solr38:isLeader=true", "object": "o1",
             "version": 1, "version_confidence": "sampled"},
            {**common, "id": "e2", "seq": 4, "type": "REGION_EXIT",
             "occurrence": "election"},
            {**common, "id": "t1", "seq": 5, "type": "REGION_ENTER",
             "occurrence": "target-region", "region":
             "org.apache.solr.update.processor.DistributedZkUpdateProcessor#doDefensiveChecks(Lorg/apache/solr/update/processor/DistributedUpdateProcessor$DistribPhase;)V"},
            {**common, "id": "r", "seq": 6, "type": "STATE_READ",
             "occurrence": "target-region", "site": "solr38:leader-value:read",
             "key": "solr38:isLeader=true", "object": "o1",
             "version": 1, "version_confidence": "sampled"},
            {**common, "id": "t", "seq": 7, "type": "TARGET_CHECK",
             "occurrence": "target-region", "site": target},
            {**common, "id": "t2", "seq": 8, "type": "REGION_EXIT",
             "occurrence": "target-region"},
        ]
        result = value_witnesses(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["field_edge_certainty"], "candidate")
        self.assertFalse(result[0]["strict_graph_path"])


if __name__ == "__main__":
    unittest.main()
