"""Source-backed checks for original JUnit eligibility decisions."""

import json
import unittest

from Mallory.cases.generate import SOLR_AUDIT, classify_eligibility
from Mallory.cases.inventory import (
    AWAIT_FIX_OPT_IN_FAILURES,
    BASELINE,
    EXPECTED_BASELINE_TARGET_EXCEPTIONS,
    INFERRED_TESTS,
    SOURCES,
    parse_selectors,
    test_evidence,
)


class EligibilityDecisionTest(unittest.TestCase):
    def setUp(self):
        self.row = {
            "case_id": "SOLR-15",
            "eligibility": {"may_attempt_seed": True},
            "build": {"tool": "direct_junit", "runner_ready_on_designated_host": True},
            "workload": {"source_reachability_audit": {
                "healthy_guard_reachability": "source_infeasible_healthy_guard"}},
        }
        self.site = {"mapping_status": "unique_compiled_site", "gaps": []}

    def test_fault_only_inner_guard_does_not_exclude_original_junit(self):
        status, gaps = classify_eligibility(self.row, self.site)
        self.assertEqual("ready_for_healthy_seed", status)
        self.assertEqual([], gaps)

    def test_expected_baseline_exception_is_separate_from_workload_validity(self):
        self.row["case_id"] = "ZOOKEEPER-13"
        self.row["workload"] = {"expected_baseline_target_exception":
                                EXPECTED_BASELINE_TARGET_EXCEPTIONS["ZOOKEEPER-13"]}
        self.assertEqual("ready_for_healthy_seed",
                         classify_eligibility(self.row, self.site)[0])

    def test_unmapped_test_and_overload_mismatch_remain_excluded(self):
        self.row["eligibility"]["may_attempt_seed"] = False
        self.assertEqual("no_mapped_cluster_test",
                         classify_eligibility(self.row, self.site)[0])
        self.row["eligibility"]["may_attempt_seed"] = True
        self.row["case_id"] = "HDFS-13"
        self.assertEqual("workload_target_overload_mismatch",
                         classify_eligibility(self.row, self.site)[0])

    def test_inherited_awaits_fix_blocks_unchanged_junit(self):
        selector = "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#test"
        self.row["workload"] = {"selected_selector": selector,
                                "candidates": [{"selector": selector,
                                                "inherited_awaits_fix_sources": [
                                                    "solr/core/src/test/org/apache/solr/update/processor/RoutedAliasUpdateProcessorTest.java"]}]}
        self.assertEqual("original_junit_skipped",
                         classify_eligibility(self.row, self.site)[0])


class OriginalClusterJUnitSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = SOURCES["zookeeper"][1]
        if not cls.root.is_dir():
            raise unittest.SkipTest("pinned ZooKeeper source is unavailable")
        cls.test_path = cls.root / (
            "zookeeper-server/src/test/java/org/apache/zookeeper/test/ReadOnlyModeTest.java")
        cls.test_source = cls.test_path.read_text()

    def test_read_only_junits_are_original_cluster_tests(self):
        for case_id, method in (("ZOOKEEPER-08", "testMultiTransaction"),
                                ("ZOOKEEPER-09", "testSessionEstablishment")):
            selector = parse_selectors(INFERRED_TESTS[case_id]["selector"])[0]
            self.assertEqual(method, selector["method"])
            evidence = test_evidence(self.root, {"ReadOnlyModeTest": [self.test_path]},
                                     selector, None)
            self.assertEqual("test_method_found", evidence["resolution"])
            self.assertTrue(evidence["has_junit_annotation"])
            self.assertIn("QuorumUtil", evidence["cluster_fixture_markers_in_test_source"])

    def test_read_only_request_paths_reach_learner_methods(self):
        def source(relative):
            return (self.root / relative).read_text()

        server = source("zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java")
        processor = source("zookeeper-server/src/main/java/org/apache/zookeeper/server/PrepRequestProcessor.java")
        tracker = source("zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/LearnerSessionTracker.java")
        self.assertIn("new LearnerSessionTracker(", server)
        self.assertIn("new PrepRequestProcessor(this, finalProcessor)", server)
        self.assertIn("zks.sessionTracker.checkSession(request.sessionId", processor)
        self.assertIn("zks.setOwner(request.sessionId, request.getOwner())", processor)
        self.assertIn("void checkSession(long sessionId, Object owner)", tracker)
        self.assertIn("void setOwner(long sessionId, Object owner)", tracker)
        self.assertIn("zk.getData(node1, false, null)", self.test_source)
        self.assertIn("qu.enableLocalSession(true)", self.test_source)

    def test_expected_global_session_rejection_is_in_original_junit(self):
        server = (self.root / "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java").read_text()
        self.assertIn("void testGlobalSessionInRO()", self.test_source)
        self.assertIn("Should not be able to renew a global session", self.test_source)
        self.assertIn("throw new ServerCnxn.CloseRequestException", server)


class InheritedSolrJUnitSourceTest(unittest.TestCase):
    def test_abort_only_solr_guards_retain_workload_without_claiming_healthy_exact_hit(self):
        root = SOURCES["solr"][1]
        if not root.is_dir():
            self.skipTest("pinned Solr source is unavailable")
        split = (root / "solr/core/src/java/org/apache/solr/cloud/api/collections/SplitShardCmd.java").read_text()
        coordinator = (root / "solr/core/src/java/org/apache/solr/servlet/CoordinatorHttpSolrCall.java").read_text()
        split_test = (root / "solr/core/src/test/org/apache/solr/cloud/SplitShardTest.java").read_text()
        coordinator_test = (root / "solr/core/src/test/org/apache/solr/search/TestCoordinatorRole.java").read_text()
        self.assertIn("leaderZnodeStat == null || ephemeralOwner != leaderZnodeStat.getEphemeralOwner()", split)
        self.assertIn("splitShard.process(cluster.getSolrClient())", split_test)
        self.assertIn("if (syntheticColl == null)", coordinator)
        self.assertIn("coordinatorJetty.getNodeName()", coordinator_test)
        inventory = json.loads((BASELINE / "Mallory/cases/inventory.json").read_text())
        cases = {row["case_id"]: row for row in inventory["cases"]}
        for case_id in ("SOLR-15", "SOLR-16", "SOLR-34"):
            self.assertEqual("source_infeasible_healthy_guard",
                             SOLR_AUDIT[case_id]["healthy_guard_reachability"])
            self.assertEqual("ready_for_healthy_seed", cases[case_id]["eligibility"]["state"])
            self.assertEqual("requires_fault_to_reach_exact_guard",
                             cases[case_id]["eligibility"]["healthy_exact_guard_reachability"])
            self.assertFalse(cases[case_id]["eligibility"]["may_promote_fault_campaign"])

    def test_routed_alias_test_inherits_awaits_fix_and_opt_in_fails_early(self):
        root = SOURCES["solr"][1]
        if not root.is_dir():
            self.skipTest("pinned Solr source is unavailable")
        test_path = root / "solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.java"
        base_path = test_path.with_name("RoutedAliasUpdateProcessorTest.java")
        evidence = test_evidence(root, {"TimeRoutedAliasUpdateProcessorTest": [test_path],
                                        "RoutedAliasUpdateProcessorTest": [base_path]},
                                 parse_selectors("TimeRoutedAliasUpdateProcessorTest#test")[0], None)
        self.assertEqual("test_method_found", evidence["resolution"])
        self.assertIn(str(base_path.relative_to(root)), evidence["inherited_awaits_fix_sources"])
        failure = AWAIT_FIX_OPT_IN_FAILURES[evidence["class"]]
        self.assertIn("createConfigSet", test_path.read_text())
        self.assertIn("@org.apache.lucene.util.LuceneTestCase.AwaitsFix", base_path.read_text())
        self.assertTrue((BASELINE / failure["evidence"]).is_file())


if __name__ == "__main__":
    unittest.main()
