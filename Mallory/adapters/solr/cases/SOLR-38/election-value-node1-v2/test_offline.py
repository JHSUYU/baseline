"""No JVM: value evidence never upgrades a sampled field edge."""

from __future__ import annotations

import unittest
import tempfile
import hashlib
from pathlib import Path
from unittest import mock

from audit_healthy import value_witnesses
import build_adapter
from run_pilot import ADAPTER, AGENT, verify_campaign_context
from run_healthy import generated_config


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
             "site": "org.apache.solr.cloud.ShardLeaderElectionContext#waitForReplicasToComeUp(I)Z@396:door:1",
             "fault_type": "EXCEPTION",
             "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException"},
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
             "org.apache.solr.cloud.ShardLeaderElectionContext#waitForReplicasToComeUp(I)Z@396:door:1",
             "fault_type": "EXCEPTION",
             "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException"},
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

        wrong_fault = [dict(row) for row in rows]
        wrong_fault[1]["exception_class"] = "java.io.IOException"
        self.assertEqual(value_witnesses(wrong_fault), [])

        unknown_thread = [dict(row) for row in rows]
        for row in unknown_thread:
            row.pop("thread_id", None)
        self.assertEqual(value_witnesses(unknown_thread), [])


class DirectRunnerPinTest(unittest.TestCase):
    def test_generated_config_replaces_shared_runner_adapter(self) -> None:
        fake_sha = "a" * 64
        with mock.patch("run_healthy.sha", side_effect=lambda path: (
                fake_sha if path == ADAPTER else hashlib.sha256(path.read_bytes()).hexdigest())):
            config = generated_config()
        self.assertEqual(config["agent_jar"], str(AGENT))
        self.assertEqual(config["agent_properties"]["adapter.jar"], str(ADAPTER))
        self.assertEqual(config["env"]["MALLORY_SOLR_AGENT_JAR"], str(AGENT))
        self.assertEqual(config["env"]["MALLORY_SOLR_ADAPTER_JAR"], str(ADAPTER))
        self.assertEqual(config["mapping"]["value_diagnostic_adapter_sha256"], fake_sha)
        self.assertEqual(config["command"][1], str(Path(__file__).parent / "run_pilot.py"))

    def test_build_requires_pinned_base_adapter(self) -> None:
        self.assertFalse(build_adapter.preflight()["maven_required"])
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(build_adapter, "BASE_JAR", Path(temporary) / "missing.jar"):
                with self.assertRaises(ValueError):
                    build_adapter.preflight()

    def test_campaign_context_requires_exact_agent_and_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            properties = output / "agent.properties"
            good = ("adapter.jar=" + str(ADAPTER) + "\n"
                    "adapter.transformer=edu.uva.liftlab.mallory.solr.SolrTransformer\n"
                    "events=" + str(output / "events.jsonl") + "\n"
                    "run.id=SOLR-38-r0000\n")
            properties.write_text(good, encoding="utf-8")
            option = f"-javaagent:{AGENT}=config={properties}"
            verify_campaign_context(output, option)
            for wrong_option in ("-javaagent:/tmp/old-agent.jar=config=" + str(properties),
                                 option + " -javaagent:/tmp/extra.jar=config=/tmp/extra"):
                with self.assertRaises(ValueError):
                    verify_campaign_context(output, wrong_option)
            properties.write_text(good.replace(str(ADAPTER), "/tmp/old-adapter.jar"),
                                  encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_campaign_context(output, option)


if __name__ == "__main__":
    unittest.main()
