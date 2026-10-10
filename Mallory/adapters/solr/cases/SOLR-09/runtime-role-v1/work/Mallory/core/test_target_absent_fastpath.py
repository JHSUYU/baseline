"""A missing healthy target must not spend minutes building an irrelevant graph."""

from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .audit import audit_campaign
from .events import Trace
from .feedback import analyze


TARGET = {"check_sites": ["Wanted#check"], "throw_site": "Wanted#throw",
          "exception_class": "java.io.IOException"}


def row(kind: str, seq: int, node: str, occurrence: str, **fields):
    return {"type": kind, "id": f"e{seq}", "seq": seq, "node": node,
            "epoch": 0, "occurrence": occurrence, "region": occurrence, **fields}


EVENTS = (
    row("DOOR_OBSERVED", 1, "A", "source", site="D#read", door_ordinal=1,
        fault_type="EXCEPTION", exception_class="java.io.IOException"),
    row("SEND", 2, "A", "source", transport="rpc", correlation="c1", port="request"),
    row("RECV", 3, "B", "receiver", transport="rpc", correlation="c1", port="request"),
    row("METHOD", 4, "B", "receiver", site="B#run", coverage_id="method:B#run"),
    row("BRANCH", 5, "B", "receiver", site="B#if", outcome="true"),
    row("DOOR_OBSERVED", 6, "unknown", "unbound", site="D#unknown",
        door_ordinal=1),
    row("TARGET_CHECK", 7, "B", "receiver", site="Another#check"),
)


class TargetAbsentFastPathTest(unittest.TestCase):
    def test_wrong_exception_at_exact_throw_site_retains_graph_diagnostics(self):
        events = EVENTS + (row("TARGET_THROW", 8, "B", "receiver",
                               site="Wanted#throw",
                               exception_class="java.lang.IllegalStateException"),)
        feedback = analyze(Trace(events), TARGET, [], return_code=0, timed_out=False)
        self.assertEqual(feedback["status"], "healthy_target_missing")
        self.assertNotIn("analysis_skipped", feedback["graph"])
        self.assertGreater(feedback["graph"]["edges"], 0)

    def test_fast_path_matches_full_graph_oracle_and_coverage(self):
        with patch("Mallory.core.feedback._skip_graph_for_missing_target",
                   return_value=False):
            full = analyze(Trace(EVENTS), TARGET, [], return_code=0, timed_out=False)
        with patch("Mallory.core.feedback.OccurrenceGraph",
                   side_effect=AssertionError("target-absent graph was built")):
            fast = analyze(Trace(EVENTS), TARGET, [], return_code=0, timed_out=False)

        self.assertEqual({key: value for key, value in fast.items() if key != "graph"},
                         {key: value for key, value in full.items() if key != "graph"})
        self.assertEqual(fast["status"], "healthy_target_missing")
        self.assertEqual(fast["coverage_ids"],
                         ["branch:B#if:true", "method:B#run"])
        self.assertEqual(fast["closure_coverage_ids"], [])
        self.assertEqual(fast["eligible_doors_before_target"], 1)
        self.assertFalse(fast["doors"][0]["in_closure"])
        self.assertGreater(full["graph"]["edges"], 0)
        self.assertEqual(fast["graph"]["analysis_skipped"], "healthy_target_absent")
        self.assertEqual(fast["graph"]["occurrences"], full["graph"]["occurrences"])
        self.assertEqual(fast["graph"]["gaps"],
                         {"door_unknown_actor": full["graph"]["gaps"]["door_unknown_actor"]})

    def test_archived_invalid_seed_audits_without_building_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Path(directory) / "case"
            trial = campaign / "trials" / "r0000"
            trial.mkdir(parents=True)
            (campaign / "config.json").write_text(json.dumps({"case_id": "MISSING",
                                                                "target": TARGET}))
            raw = b"".join(json.dumps(event).encode() + b"\n" for event in EVENTS)
            archived = trial / "events.jsonl.gz"
            with gzip.open(archived, "wb") as stream:
                stream.write(raw)
            evidence = {"raw_path": None, "gzip_path": archived.name,
                        "raw_sha256": hashlib.sha256(raw).hexdigest(),
                        "raw_bytes": len(raw),
                        "gzip_sha256": hashlib.sha256(archived.read_bytes()).hexdigest(),
                        "gzip_bytes": archived.stat().st_size}
            # Simulate an archived pre-optimization receipt with a full graph.
            with patch("Mallory.core.feedback._skip_graph_for_missing_target",
                       return_value=False):
                feedback = analyze(Trace(EVENTS), TARGET, [], return_code=0,
                                   timed_out=False)
            result = {"case_id": "MISSING", "trial_id": 0, "plan": [],
                      "feedback": feedback, "return_code": 0, "timed_out": False,
                      "novelty": {"coverage": len(feedback["coverage_ids"]),
                                  "closure_coverage": 0, "closure_edges": 0},
                      "selection_reason": "healthy_seed", "events_evidence": evidence}
            (trial / "result.json").write_text(json.dumps(result))
            (campaign / "result.json").write_text(json.dumps({
                "case_id": "MISSING", "status": "healthy_seed_invalid",
                "trials": [{"trial_id": 0, "result": "trials/r0000/result.json"}]}))
            with patch("Mallory.core.feedback.OccurrenceGraph",
                       side_effect=AssertionError("feedback built graph")), patch(
                           "Mallory.core.audit.OccurrenceGraph",
                           side_effect=AssertionError("audit built graph")):
                artifact = audit_campaign(campaign, Path(directory) / "audit.json")
            self.assertTrue(artifact["archive_integrity_valid"])
            self.assertTrue(artifact["guidance_consistent"])
            self.assertTrue(artifact["trials"][0]["graph_changed"])
            self.assertFalse(artifact["healthy_closure_proven"])
            self.assertFalse(artifact["report_gate_passed"])
            self.assertEqual(artifact["trials"][0]["recomputed_status"],
                             "healthy_target_missing")


if __name__ == "__main__":
    unittest.main()
