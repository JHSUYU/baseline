"""Read-only exact-check frontier tests; no cluster or fault process is run."""

from __future__ import annotations

import unittest

from Mallory.native_graphchecker_campaign import campaign as core


SITE = "<Target: void check()>#u4"


def summary() -> dict:
    return {"targetSiteId": SITE,
            "closureMembershipAuthority":
                "original_runtime_selected_region_finalizer",
            "closureOccurrenceIds": ["shared-closure"],
            "targetEvidence": {
                "selectedOccurrenceAddress": "dn0#epoch0/region/exact",
                "physicalActor": "dn0", "actorEpochOrdinal": 0,
                "targetCheckOccurrenceIds": ["check-1", "check-2"]}}


def check(seq: int, occurrence: str) -> dict:
    return {"kind": "TARGET_CHECK", "seq": seq, "siteId": SITE,
            "node": "dn0", "actorEpochOrdinal": 0,
            "occurrenceId": occurrence}


def door(seq: int, actor: str = "dn0", *, ordinal: int = 1,
         occurrence: str = "shared-closure") -> dict:
    return {"kind": "FAULT_DOOR", "seq": seq,
            "siteId": "<Rpc: void call()>#u2", "node": actor,
            "actorEpochOrdinal": 0, "occurrenceId": occurrence,
            "ordinal": ordinal, "exceptionClass": "java.io.IOException"}


class RepeatedTargetTemporalFrontierTest(unittest.TestCase):
    def test_same_actor_door_between_two_exact_checks_is_timely(self) -> None:
        rows = [check(1, "check-1"), door(2), check(3, "check-2")]
        default = core._region_doors(rows, summary())
        self.assertEqual("after_selected_target", default[0]["target_phase"])
        self.assertNotIn("later_selected_target_order", default[0])
        opted = core._region_doors(
            rows, summary(), repeated_target_temporal_frontier=True)
        self.assertEqual("before_later_selected_target",
                         opted[0]["target_phase"])
        self.assertEqual(1, opted[0]["target_order_distance"])
        self.assertEqual({"checkOccurrenceId": "check-2", "checkSeq": 3,
                          "orderBasis": "same_actor_seq", "sameActor": True,
                          "peerIncarnationVerified": False},
                         opted[0]["later_selected_target_order"])

    def test_lost_later_check_after_fault_does_not_promote(self) -> None:
        applied = {"kind": "FAULT_APPLIED", "seq": 2,
                   "node": "client", "actorEpochOrdinal": 0,
                   "occurrenceId": "applied"}
        rows = [check(1, "check-1"), applied, door(3)]
        opted = core._region_doors(
            rows, summary(), applied,
            repeated_target_temporal_frontier=True)
        self.assertEqual("after_selected_target", opted[0]["target_phase"])
        self.assertNotIn("later_selected_target_order", opted[0])

    def test_cross_actor_needs_gapless_clock_and_same_peer_incarnation(self) -> None:
        rpc = door(2, "client", occurrence="shared-closure")
        rows = [check(1, "check-1"), rpc, check(3, "check-2")]
        exact = core._fault_identity(rpc, applied=True)
        different = core._region_doors(
            rows, summary(), repeated_target_temporal_frontier=True)
        self.assertEqual("after_selected_target",
                         different[0]["target_phase"])
        self.assertEqual("gapless_hook_clock", different[0][
            "later_selected_target_order"]["orderBasis"])
        same = core._region_doors(rows, summary(),
            repeated_target_temporal_frontier=True,
            same_peer_incarnation_door_check_pairs=frozenset({(exact, 3)}))
        self.assertEqual("before_later_selected_target",
                         same[0]["target_phase"])
        self.assertFalse(same[0]["selected_target_actor"])
        self.assertTrue(same[0]["later_selected_target_order"][
            "peerIncarnationVerified"])

        # Same occurrence ID at another site/ordinal is not the same door.
        other = door(2, "client", ordinal=2)
        other["siteId"] = "<OtherRpc: void call()>#u2"
        changed = core._region_doors([rows[0], other, rows[2]], summary(),
            repeated_target_temporal_frontier=True,
            same_peer_incarnation_door_check_pairs=frozenset({(exact, 3)}))
        self.assertEqual("after_selected_target", changed[0]["target_phase"])

        # The same door's relation to another check does not authorize this
        # check; the target-side peer may change between activations.
        wrong_check = core._region_doors(rows, summary(),
            repeated_target_temporal_frontier=True,
            same_peer_incarnation_door_check_pairs=frozenset({(exact, 99)}))
        self.assertEqual("after_selected_target",
                         wrong_check[0]["target_phase"])
        third_summary = summary()
        third_summary["targetEvidence"]["targetCheckOccurrenceIds"].append(
            "check-3")
        third = core._region_doors([*rows, check(4, "check-3")],
            third_summary, repeated_target_temporal_frontier=True,
            same_peer_incarnation_door_check_pairs=frozenset({(exact, 4)}))
        self.assertEqual("before_later_selected_target",
                         third[0]["target_phase"])
        self.assertEqual(4, third[0]["later_selected_target_order"]["checkSeq"])
        self.assertEqual(2, third[0]["target_order_distance"])

        # A non-gapless merged receipt does not order CLIENT against DN.
        uncertain = [check(10, "check-1"), door(20, "client"),
                     check(30, "check-2")]
        uncertain_exact = core._fault_identity(uncertain[1], applied=True)
        unproved = core._region_doors(uncertain, summary(),
            repeated_target_temporal_frontier=True,
            same_peer_incarnation_door_check_pairs=frozenset({
                (uncertain_exact, 30)}))
        self.assertEqual("after_selected_target", unproved[0]["target_phase"])
        self.assertNotIn("later_selected_target_order", unproved[0])

    def test_bad_selected_actor_order_is_not_a_frontier(self) -> None:
        rows = [check(1, "check-1"), door(2), check(1, "check-2")]
        opted = core._region_doors(
            rows, summary(), repeated_target_temporal_frontier=True)
        self.assertEqual("after_selected_target", opted[0]["target_phase"])

    def test_legacy_plan_key_and_oracle_are_unchanged(self) -> None:
        rpc = door(2)
        fault = {field: rpc[field] for field in core.SELECTOR_FIELDS}
        self.assertEqual(core._plan_key([fault]), core._plan_key([fault], None))
        active = {"target_phase": "before_later_selected_target"}
        result = {"runner_mode": "region_state", "strict_injection": True,
                  "native_target_retained": True,
                  "post_fault_target_check_observed": True,
                  "fault_in_target_closure": False,
                  "target_temporal_admitted": False}
        feedback = core._depth_feedback(active, result, 0)
        self.assertTrue(feedback["observed_pre_target_phase"])
        self.assertEqual(1, feedback["score"])


if __name__ == "__main__":
    unittest.main()
