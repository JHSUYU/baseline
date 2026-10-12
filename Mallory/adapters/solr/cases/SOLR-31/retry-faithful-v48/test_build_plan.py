import unittest

from build_plan import CLASS_SHA, COLLECTION, PATH, SITE, plan_from_receipt


def receipt():
    return {"schema_version": 1, "status": "retry_lowlevel_healthy_admitted",
            "binding": {"site": SITE, "collection": COLLECTION, "path": PATH,
                        "original_class_sha256": CLASS_SHA, "node": "shard-2",
                        "epoch": 0, "watch_read_ordinal": 4, "retry_count": 8,
                        "reader_id": "abc", "keeper_id": "def", "session_id": 1234}}


class PlanTests(unittest.TestCase):
    def test_transient_is_one_low_level_failure(self):
        plan = plan_from_receipt(receipt(), "transient")
        faults = plan["faults"]
        self.assertEqual([1], [f["point"]["hit"] for f in faults])
        self.assertEqual("shard-2", faults[0]["point"]["node"])
        self.assertEqual(4, plan["selection"]["watch_read_ordinal"])

    def test_exhaust_uses_all_reported_retry_attempts(self):
        faults = plan_from_receipt(receipt(), "exhaust")["faults"]
        self.assertEqual(list(range(1, 9)), [f["point"]["hit"] for f in faults])
        self.assertEqual(8, len({f["fault_id"] for f in faults}))
        fourteen = receipt()
        fourteen["binding"]["retry_count"] = 14
        self.assertEqual(14, len(plan_from_receipt(fourteen, "exhaust")["faults"]))

    def test_rejects_unbound_or_changed_source(self):
        bad = receipt()
        bad["binding"]["node"] = "unknown"
        with self.assertRaises(ValueError):
            plan_from_receipt(bad, "exhaust")
        bad = receipt()
        bad["binding"]["original_class_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            plan_from_receipt(bad, "transient")

    def test_rejects_unbounded_retry_count_and_session(self):
        bad = receipt()
        bad["binding"]["retry_count"] = 100
        with self.assertRaises(ValueError):
            plan_from_receipt(bad, "exhaust")
        bad = receipt()
        bad["binding"]["session_id"] = None
        with self.assertRaises(ValueError):
            plan_from_receipt(bad, "transient")
        bad["binding"]["session_id"] = 0
        with self.assertRaises(ValueError):
            plan_from_receipt(bad, "transient")


if __name__ == "__main__":
    unittest.main()
