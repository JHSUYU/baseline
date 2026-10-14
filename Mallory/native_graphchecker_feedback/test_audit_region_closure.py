"""Fixture-backed checks for the selected-instance Finalizer audit."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_feedback.audit_region_closure import audit
from Mallory.native_graphchecker_feedback.region_state_graph import _sha


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


class RegionClosureAuditTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = self.root / "engine.jar"
        self.engine.write_bytes(b"pinned engine fixture")
        self.trial = self.root / "campaign/trials/r0001"
        self.trial.mkdir(parents=True)
        self.selected_address = "peer-1#epoch0/region/REGION.target/ctx:first"
        self.other_address = "peer-1#epoch0/region/REGION.target/ctx:second"
        self.plan = self.trial / "original-graph/recorded/concolic_region_plan.jsonl"
        write_jsonl(self.plan, [
            {"kind": "CONCOLIC_RUNTIME_MODEL_CATALOG"},
            {"kind": "CONCOLIC_REGION_PLAN", "occurrenceId": self.selected_address},
            {"kind": "CONCOLIC_REGION_PLAN", "occurrenceId": self.other_address},
        ])
        self.members = {
            "selected-id": {"occurrenceId": self.selected_address},
            "other-id": {"occurrenceId": self.other_address},
        }
        self.summary_path = self.trial / "native-summary.json"
        self.summary = {
            "targetSiteId": "Check#u7", "closureOccurrenceIds": list(self.members),
            "provenance": {"engineJarSha256": _sha(self.engine)},
            "targetEvidence": {
                "selectedOccurrenceAddress": self.selected_address,
                "targetCheckOccurrenceIds": ["selected-id", "other-id", "remote-id"],
                "physicalActor": "peer-1", "actorEpochOrdinal": 0,
            },
        }
        self.result_path = self.trial / "result.json"
        self.result = {
            "strict_injection": True, "native_target_retained": True,
            "native_target_occurrence_ids": ["selected-id", "other-id", "remote-id"],
            "fault_in_target_closure": True,
        }
        self.events_path = self.trial / "iteration-native/fault-events.jsonl"
        self.events = [
            {"kind": "TARGET_CHECK", "siteId": "Check#u7", "node": "peer-1",
             "actorEpochOrdinal": 0, "ordinal": 1, "occurrenceId": "selected-id"},
            {"kind": "TARGET_CHECK", "siteId": "Check#u7", "node": "peer-1",
             "actorEpochOrdinal": 0, "ordinal": 1, "occurrenceId": "other-id"},
            {"kind": "TARGET_CHECK", "siteId": "Check#u7", "node": "peer-2",
             "actorEpochOrdinal": 1, "ordinal": 1, "occurrenceId": "remote-id"},
            {"kind": "FAULT_DOOR", "occurrenceId": "selected-id"},
            {"kind": "FAULT_APPLIED", "occurrenceId": "selected-id"},
        ]
        self.save()

    def save(self):
        write_jsonl(self.events_path, self.events)
        self.summary["provenance"].update({
            "regionPlanSha256": _sha(self.plan),
            "faultEventsSha256": _sha(self.events_path),
        })
        self.summary_path.write_text(json.dumps(self.summary))
        self.result["native_session_sha256"] = _sha(self.summary_path)
        self.result_path.write_text(json.dumps(self.result))

    def run_audit(self):
        with patch("Mallory.native_graphchecker_feedback.audit_region_closure."
                   "_plan_identity_rows", return_value=self.members):
            return audit(self.root / "campaign", self.engine)

    def test_other_same_actor_and_remote_hits_do_not_invalidate_selected_target(self):
        outcome = self.run_audit()
        self.assertEqual(1, outcome["strictTargetRetainedTrials"])
        row = outcome["trials"][0]
        self.assertEqual("selected-id", row["selectedTargetOccurrenceId"])
        self.assertEqual(["remote-id"], row["observedTargetIdsOutsideClosure"])
        self.assertTrue(row["correctedLastFaultInClosure"])

    def test_selected_instance_must_have_exact_plan_and_runtime_receipt(self):
        self.summary["targetEvidence"]["selectedOccurrenceAddress"] = (
            "peer-1#epoch0/region/REGION.target/ctx:unplanned")
        self.save()
        with self.assertRaisesRegex(ValueError, "selected target absent"):
            self.run_audit()
        self.summary["targetEvidence"]["selectedOccurrenceAddress"] = (
            self.selected_address)
        self.events = [row for row in self.events if row.get("occurrenceId") !=
                       "selected-id" or row["kind"] != "TARGET_CHECK"]
        self.save()
        with self.assertRaisesRegex(ValueError, "exact runtime check"):
            self.run_audit()


if __name__ == "__main__":
    unittest.main()
