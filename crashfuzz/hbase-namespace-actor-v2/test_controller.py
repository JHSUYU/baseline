#!/usr/bin/env python3
"""Offline receipt checks; no HBase or ZooKeeper cluster is started."""
import unittest
import tempfile
from pathlib import Path
import json

import controller


SELECTOR = "ACTIVE_MASTER~ZK_EXISTS~L2hiYXNl~start:52~1"
STEP = SELECTOR + "~CONNECTIONLOSS"
IO = ("NSACTOR IO_ATTEMPT seq=1 role=ACTIVE_MASTER actor_raw=m1 manager=3 "
      "watcher=7 family=ZK_EXISTS path=/hbase site=start:52 ordinal=1 selector=" + SELECTOR)
FAULT = ("NSACTOR FAULT_APPLIED seq=1 step=1 actor_raw=m1 manager=3 selector="
         + SELECTOR + " kind=CONNECTIONLOSS")


def target(actor="m1", manager=3, point="HBASE-08", subject="TestNamespaceAuditor_np2",
           outcome="normal", seq=2, bound="true"):
    return (f"NSACTOR TARGET_EXIT seq={seq} point={point} subject={subject} "
            f"role=ACTIVE_MASTER actor_raw={actor} manager={manager} watcher=7 "
            f"bound_match={bound} exception=none outcome={outcome}")


def guard(point="HBASE-08", subject="TestNamespaceAuditor_np2", seq=2, event_seq=3,
          actor="m1"):
    site = ("getNamespace:115" if point == "HBASE-08" else
            "checkAndUpdateNamespaceRegionCount:128" if point == "HBASE-21" else
            "checkAndUpdateNamespaceTableCount:166")
    return (f"NSACTOR GUARD_OPERAND event_seq={event_seq} seq={seq} point={point} subject={subject} "
            f"role=ACTIVE_MASTER actor_raw={actor} manager=3 watcher=7 "
            f"bound_match=true site={site}")


class ReceiptTests(unittest.TestCase):
    def test_exact_same_actor_after_fault(self):
        trace = controller.parse("\n".join((IO, FAULT, guard(), target())))
        receipt = controller.exact_receipt("HBASE-08", [STEP], trace)
        self.assertTrue(receipt["strict"])
        self.assertTrue(receipt["target_after_final_fault"])

    def test_wrong_actor_fails_closed(self):
        trace = controller.parse("\n".join((IO, FAULT, guard(), target(actor="m2"))))
        receipt = controller.exact_receipt("HBASE-08", [STEP], trace)
        self.assertTrue(receipt["strict"])
        self.assertFalse(receipt["target_after_final_fault"])

    def test_wrong_manager_fails_closed(self):
        trace = controller.parse("\n".join((IO, FAULT, guard(), target(manager=4))))
        self.assertFalse(controller.exact_receipt("HBASE-08", [STEP], trace)
                         ["target_after_final_fault"])

    def test_wrong_subject_does_not_count(self):
        trace = controller.parse("\n".join((IO, FAULT, guard(subject="unrelated"),
                                           target(subject="unrelated"))))
        self.assertFalse(controller.exact_receipt("HBASE-08", [STEP], trace)
                         ["target_after_final_fault"])

    def test_target_before_last_fault_is_lost(self):
        trace = controller.parse("\n".join((guard(seq=0, event_seq=0), target(seq=0), IO, FAULT)))
        self.assertFalse(controller.exact_receipt("HBASE-08", [STEP], trace)
                         ["target_after_final_fault"])

    def test_method_enter_before_fault_but_guard_after_is_admitted(self):
        trace = controller.parse("\n".join((IO, FAULT, guard(seq=0, event_seq=2),
                                           target(seq=0))))
        self.assertTrue(controller.exact_receipt("HBASE-08", [STEP], trace)
                        ["target_after_final_fault"])

    def test_later_selected_exception_is_not_hidden_by_normal_target(self):
        trace = controller.parse("\n".join((IO, FAULT,
                                           guard(seq=2, event_seq=3), target(seq=2),
                                           guard(seq=4, event_seq=5),
                                           target(seq=4, outcome="selected_namespace_not_found"))))
        receipt = controller.exact_receipt("HBASE-08", [STEP], trace)
        self.assertTrue(receipt["target_after_final_fault"])
        self.assertEqual(receipt["target_outcomes"],
                         ["normal", "selected_namespace_not_found"])
        self.assertEqual(receipt["target_outcome"], "selected_namespace_not_found")

    def test_missing_second_fault_is_not_strict(self):
        trace = controller.parse("\n".join((IO, FAULT, guard(), target())))
        self.assertFalse(controller.exact_receipt("HBASE-08", [STEP, STEP], trace)["strict"])

    def test_region_quota_expected_signature(self):
        subject = "TestNamespaceAuditor_testRestoreSnapshotQuotaExceed:table1:4"
        trace = controller.parse("\n".join((IO, FAULT, guard("HBASE-21", subject), target(
            point="HBASE-21", subject=subject, outcome="selected_region_count_quota"))))
        coverage = "BRANCH class=org/apache/hadoop/hbase/namespace/NamespaceStateManager line=128 covered=1"
        self.assertTrue(controller.exact_receipt("HBASE-21", [STEP], trace, coverage)
                        ["target_after_final_fault"])

    def test_region_count_normal_requires_guard_line(self):
        subject = "TestNamespaceAuditor_testRestoreSnapshotQuotaExceed:table1:4"
        trace = controller.parse("\n".join((IO, FAULT, target(point="HBASE-21", subject=subject))))
        self.assertFalse(controller.exact_receipt("HBASE-21", [STEP], trace)
                         ["target_after_final_fault"])
        coverage = "BRANCH class=org/apache/hadoop/hbase/namespace/NamespaceStateManager line=128 covered=1"
        self.assertFalse(controller.exact_receipt("HBASE-21", [STEP], trace, coverage)
                         ["target_after_final_fault"])
        trace = controller.parse("\n".join((IO, FAULT, guard("HBASE-21", subject),
                                           target(point="HBASE-21", subject=subject))))
        self.assertTrue(controller.exact_receipt("HBASE-21", [STEP], trace, coverage)
                        ["target_after_final_fault"])

    def test_ambiguous_selector_excluded_during_calibration(self):
        first = controller.parse("\n".join((IO, guard(seq=3, event_seq=5), target(seq=3))))
        second_io = IO.replace("seq=1", "seq=2").replace("actor_raw=m1", "actor_raw=m2")
        second_target = target(actor="m2", seq=4)
        first["IO_ATTEMPT"].append(controller.parse(second_io)["IO_ATTEMPT"][0])
        first["TARGET_EXIT"].append(controller.parse(second_target)["TARGET_EXIT"][0])
        first["GUARD_OPERAND"].append(
            controller.parse(guard(seq=4, event_seq=6, actor="m2"))["GUARD_OPERAND"][0])
        with self.assertRaisesRegex(RuntimeError, "changed Master/manager"):
            controller.stable_seed_io("HBASE-08", [first, first])

    def test_postfault_feedback_excludes_other_master_io(self):
        other = IO.replace("seq=1", "seq=3").replace("actor_raw=m1", "actor_raw=m2")
        other_target = target(actor="m2", seq=4)
        same = IO.replace("seq=1", "seq=5").replace("ordinal=1", "ordinal=2") \
            .replace(SELECTOR, SELECTOR[:-1] + "2")
        log = "\n".join((IO, FAULT, other, guard(seq=4, event_seq=4, actor="m2"),
                         other_target, same, guard(seq=6, event_seq=7), target(seq=6)))
        trace = controller.parse(log)
        self.assertEqual(controller.pretarget_io("HBASE-08", trace, 1),
                         [SELECTOR[:-1] + "2"])

    def test_case_local_result_excludes_legacy_counts(self):
        state = {"case": "HBASE-08", "status": "ready", "healthy_seeds": ["h1", "h2"],
                 "healthy_selected_target_counts": [1, 1],
                 "healthy_stable_selectors": [SELECTOR],
                 "healthy_io_families": ["ZK_EXISTS"],
                 "healthy_expected_outcomes": ["normal"],
                 "trials": [], "effective": 0, "covered_methods": [],
                 "baseline_methods": [], "covered_branches": {},
                 "baseline_branches": {}, "io_family_counts": {"ZK_EXISTS": 2},
                 "healthy_elapsed_seconds": 2.5, "max_effective": 80,
                 "max_faults": 8, "max_attempts": 320}
        with tempfile.TemporaryDirectory() as temporary:
            old = controller.HERE
            try:
                controller.HERE = Path(temporary)
                controller.publish(state)
                row = json.loads((Path(temporary) / "campaigns/HBASE-08/result.json").read_text())
            finally:
                controller.HERE = old
        self.assertEqual(row["attempted_trials"], 0)
        self.assertEqual(row["effective_trials"], 0)
        self.assertEqual(row["budget"]["effective_trials"], 80)
        self.assertEqual(row["target_function"], "getNamespace(String)")
        self.assertEqual(row["total_elapsed_seconds"], 2.5)

    def test_healthy_normal_is_not_counted_as_expected_exception(self):
        expected = ["normal", "selected_region_count_quota"]
        self.assertEqual(controller.exception_review("normal", expected), "none")
        self.assertEqual(controller.exception_review("selected_region_count_quota", expected),
                         "healthy_expected")
        self.assertEqual(controller.exception_review("selected_namespace_not_found", expected),
                         "candidate_needs_source_and_replay")

    def test_healthy_same_actor_guard_distance(self):
        trace = controller.parse("\n".join((IO, guard(seq=3, event_seq=5), target(seq=3))))
        self.assertEqual(controller.selector_distances("HBASE-08", [trace], [SELECTOR]),
                         {SELECTOR: 4})

    def test_near_guard_priority_retains_distant_plan(self):
        distant = "ACTIVE_MASTER~ZK_CHILDREN_READ~L2hiYXNl~start:20~1"
        state = {"queue": [{"plan": [distant + "~CONNECTIONLOSS"], "score": 0},
                           {"plan": [STEP], "score": 0}],
                 "trials": [], "selector_distance": {distant: 23, SELECTOR: 2}}
        self.assertEqual(controller.next_trial(state)["plan"], [STEP])
        self.assertEqual(len(state["queue"]), 2)

    def test_repeated_same_site_loss_only_changes_priority(self):
        other = "ACTIVE_MASTER~ZK_CREATE~L2hiYXNl~writeNamespace:183~1~CONNECTIONLOSS"
        failing = STEP
        losses = [{"plan": [failing], "strict": True,
                   "target_after_final_fault": False, "effective": False}
                  for _ in range(4)]
        state = {"loss_priority_policy": "same_site_target_loss_v1",
                 "trials": losses,
                 "queue": [{"plan": [failing], "score": 0},
                           {"plan": [other], "score": 0}],
                 "selector_distance": {SELECTOR: 5,
                                       other.rsplit("~", 1)[0]: 6}}
        self.assertGreater(controller.same_site_loss_penalty(state["queue"][0], state), 0)
        self.assertEqual(controller.same_site_loss_penalty(state["queue"][1], state), 0)
        self.assertEqual(controller.next_trial(state)["plan"], [other])
        self.assertEqual(len(state["queue"]), 2)
        state["trials"].append({"plan": [failing], "strict": True,
                                "target_after_final_fault": True, "effective": True})
        failed_entry = next(x for x in state["queue"] if x["plan"] == [failing])
        self.assertEqual(controller.same_site_loss_penalty(failed_entry, state), 0)


if __name__ == "__main__":
    unittest.main()
