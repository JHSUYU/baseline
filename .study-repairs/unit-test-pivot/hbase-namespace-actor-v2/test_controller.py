#!/usr/bin/env python3
"""Offline receipt checks; no HBase or ZooKeeper cluster is started."""
import unittest

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


class ReceiptTests(unittest.TestCase):
    def test_exact_same_actor_after_fault(self):
        trace = controller.parse("\n".join((IO, FAULT, target())))
        receipt = controller.exact_receipt("HBASE-08", [STEP], trace)
        self.assertTrue(receipt["strict"])
        self.assertTrue(receipt["target_after_final_fault"])

    def test_wrong_actor_fails_closed(self):
        trace = controller.parse("\n".join((IO, FAULT, target(actor="m2"))))
        receipt = controller.exact_receipt("HBASE-08", [STEP], trace)
        self.assertTrue(receipt["strict"])
        self.assertFalse(receipt["target_after_final_fault"])

    def test_wrong_manager_fails_closed(self):
        trace = controller.parse("\n".join((IO, FAULT, target(manager=4))))
        self.assertFalse(controller.exact_receipt("HBASE-08", [STEP], trace)
                         ["target_after_final_fault"])

    def test_wrong_subject_does_not_count(self):
        trace = controller.parse("\n".join((IO, FAULT, target(subject="unrelated"))))
        self.assertFalse(controller.exact_receipt("HBASE-08", [STEP], trace)
                         ["target_after_final_fault"])

    def test_target_before_last_fault_is_lost(self):
        trace = controller.parse("\n".join((target(seq=0), IO, FAULT)))
        self.assertFalse(controller.exact_receipt("HBASE-08", [STEP], trace)
                         ["target_after_final_fault"])

    def test_missing_second_fault_is_not_strict(self):
        trace = controller.parse("\n".join((IO, FAULT, target())))
        self.assertFalse(controller.exact_receipt("HBASE-08", [STEP, STEP], trace)["strict"])

    def test_region_quota_expected_signature(self):
        trace = controller.parse("\n".join((IO, FAULT, target(
            point="HBASE-21", subject="TestNamespaceAuditor_testRestoreSnapshotQuotaExceed:table1:4",
            outcome="selected_region_count_quota"))))
        self.assertTrue(controller.exact_receipt("HBASE-21", [STEP], trace)
                        ["target_after_final_fault"])

    def test_region_count_normal_requires_guard_line(self):
        trace = controller.parse("\n".join((IO, FAULT, target(
            point="HBASE-21", subject="TestNamespaceAuditor_testRestoreSnapshotQuotaExceed:table1:4"))))
        self.assertFalse(controller.exact_receipt("HBASE-21", [STEP], trace)
                         ["target_after_final_fault"])
        coverage = "BRANCH class=org/apache/hadoop/hbase/namespace/NamespaceStateManager line=128 covered=1"
        self.assertTrue(controller.exact_receipt("HBASE-21", [STEP], trace, coverage)
                        ["target_after_final_fault"])

    def test_ambiguous_selector_excluded_during_calibration(self):
        first = controller.parse("\n".join((IO, target(seq=3))))
        second_io = IO.replace("seq=1", "seq=2").replace("actor_raw=m1", "actor_raw=m2")
        second_target = target(actor="m2", seq=4)
        first["IO_ATTEMPT"].append(controller.parse(second_io)["IO_ATTEMPT"][0])
        first["TARGET_EXIT"].append(controller.parse(second_target)["TARGET_EXIT"][0])
        with self.assertRaisesRegex(RuntimeError, "changed Master/manager"):
            controller.stable_seed_io("HBASE-08", [first, first])

    def test_postfault_feedback_excludes_other_master_io(self):
        other = IO.replace("seq=1", "seq=3").replace("actor_raw=m1", "actor_raw=m2")
        other_target = target(actor="m2", seq=4)
        same = IO.replace("seq=1", "seq=5").replace("ordinal=1", "ordinal=2") \
            .replace(SELECTOR, SELECTOR[:-1] + "2")
        log = "\n".join((IO, FAULT, other, other_target, same, target(seq=6)))
        trace = controller.parse(log)
        self.assertEqual(controller.pretarget_io("HBASE-08", trace, 1),
                         [SELECTOR[:-1] + "2"])


if __name__ == "__main__":
    unittest.main()
