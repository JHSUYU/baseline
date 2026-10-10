"""Pure Python tests of strict postfault split retry identity and ordering."""

import unittest

from audit_healthy import CHECK, FIRST, SECOND, TYPED
from postfault_gate import evaluate


def row(kind, site, seq, occurrence, node="control"):
    event = dict(type=kind, site=site, seq=seq, occurrence=occurrence,
                 node=node, epoch=0)
    if kind in ("DOOR_OBSERVED", "FAULT_APPLIED"):
        event.update(fault_type="EXCEPTION", exception_class=TYPED)
    return event


def sample():
    return [row("DOOR_OBSERVED", FIRST, 1, "first"),
            row("DOOR_OBSERVED", SECOND, 2, "first"),
            row("TARGET_CHECK", CHECK, 3, "first"),
            row("FAULT_APPLIED", SECOND, 4, "first"),
            row("DOOR_OBSERVED", FIRST, 5, "retry"),
            row("DOOR_OBSERVED", SECOND, 6, "retry"),
            row("TARGET_CHECK", CHECK, 7, "retry")]


class PostfaultGateTest(unittest.TestCase):
    def setUp(self):
        self.feedback = dict(all_faults_effective=True, fault_identity_valid=True)

    def test_accepts_later_same_actor_retry(self):
        got = evaluate(sample(), self.feedback, "control")
        self.assertTrue(got["valid"])
        self.assertEqual(7, got["retry_target_seq"])

    def test_rejects_prefault_only_target(self):
        events = sample()[:4]
        self.assertFalse(evaluate(events, self.feedback, "control")["valid"])

    def test_rejects_wrong_actor_and_untyped_fault(self):
        events = sample()
        for event in events[4:]:
            event["node"] = "other"
        self.assertFalse(evaluate(events, self.feedback, "control")["valid"])
        events = sample()
        events[3]["exception_class"] = "java.io.IOException"
        self.assertFalse(evaluate(events, self.feedback, "control")["valid"])

    def test_rejects_same_invocation_target(self):
        events = sample()
        for event in events[4:]:
            event["occurrence"] = "first"
        self.assertFalse(evaluate(events, self.feedback, "control")["valid"])


if __name__ == "__main__":
    unittest.main()
