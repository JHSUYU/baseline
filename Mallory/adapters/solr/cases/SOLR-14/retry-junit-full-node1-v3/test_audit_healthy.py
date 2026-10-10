"""Offline acceptance and rejection checks for the retry JUnit gate."""

import unittest

from audit_healthy import CHECK, FIRST, SECOND, TYPED, CONFIG, evaluate


def event(kind, site, seq, occurrence):
    row = dict(type=kind, site=site, seq=seq, occurrence=occurrence,
               node="node1", epoch=0)
    if kind == "DOOR_OBSERVED":
        row.update(fault_type="EXCEPTION", exception_class=TYPED)
    return row


def fixture():
    result = dict(case_id="SOLR-14", healthy_seed_valid=True,
                  cluster_test=CONFIG["cluster_test"],
                  runtime_attestation=dict(valid=True, observed_target_class_sha256=
                                           CONFIG["expected_target_class_sha256"]))
    pilot = dict(source_revision=CONFIG["mapping"]["source_git_revision"],
                 agent_sha256=CONFIG["mapping"]["agent_sha256"],
                 target_throw_count=0)
    junit = dict(status="passed", tests=1, failures=0, errors=0, skipped=0)
    events = [event("DOOR_OBSERVED", FIRST, 1, "first"),
              event("DOOR_OBSERVED", SECOND, 2, "first"),
              event("TARGET_CHECK", CHECK, 3, "first"),
              event("DOOR_OBSERVED", FIRST, 4, "retry"),
              event("DOOR_OBSERVED", SECOND, 5, "retry"),
              event("TARGET_CHECK", CHECK, 6, "retry")]
    return result, pilot, junit, events


class HealthyGateTest(unittest.TestCase):
    def test_accepts_typed_first_and_retry_paths(self):
        self.assertEqual("healthy_retry_gate_passed", evaluate(*fixture())["status"])

    def test_rejects_missing_retry_check(self):
        args = fixture()
        args[-1].pop()
        with self.assertRaisesRegex(ValueError, "two typed target paths"):
            evaluate(*args)

    def test_rejects_wrong_type_and_cross_actor(self):
        args = fixture()
        args[-1][4]["exception_class"] = "java.io.IOException"
        with self.assertRaisesRegex(ValueError, "untyped"):
            evaluate(*args)
        args = fixture()
        for row in args[-1][3:]:
            row["node"] = "node2"
        with self.assertRaisesRegex(ValueError, "two typed target paths"):
            evaluate(*args)


if __name__ == "__main__":
    unittest.main()
