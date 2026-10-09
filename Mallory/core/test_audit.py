"""Offline archive audit checks without launching a cluster."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from .audit import (_audit_faults, _load_archived_trace,
                    _same_actor_target_followups, audit_campaign)
from .events import Trace, load_trace
from .feedback import analyze, digest


def event(kind, seq, node, occurrence, **fields):
    return {"type": kind, "id": f"e{seq}", "seq": seq, "node": node, "epoch": 0,
            "occurrence": occurrence, "region": occurrence, **fields}


class AuditTest(unittest.TestCase):
    def _archive(self, root: Path, *, causal_handoff: bool = True,
                 candidate_only_door_path: bool = False,
                 local_timeline_only: bool = False,
                 allow_local_timeline_doors: bool = False,
                 fault_target_node: str | None = None,
                 fault_target_occurrence: str | None = None,
                 fault_door_site: str | None = None) -> Path:
        campaign = root / "campaign"
        campaign.mkdir(parents=True)
        target = {"check_sites": ["C#guard"], "throw_site": "C#throw",
                  "exception_class": "java.io.IOException"}
        config = {"case_id": "TEST-AUDIT", "target": target,
                  "allow_local_timeline_doors": allow_local_timeline_doors}
        (campaign / "config.json").write_text(json.dumps(config))
        point = {"site": "C#door", "node": "A", "epoch": 0, "door_ordinal": 1}
        fault = {"fault_id": "f1", "point": point, "fault_type": "EXCEPTION",
                 "exception_class": "java.io.IOException"}
        known_coverage = set()
        known_closure = set()
        known_edges = set()
        trial_rows = []
        for trial_id in (0, 1):
            door_site = fault_door_site if trial_id and fault_door_site else "C#door"
            trial_fault = {**fault, "point": {**point, "site": door_site}}
            events = [
                event("DOOR_OBSERVED", 1, "A", "source", site=door_site,
                      door_ordinal=1, hit=1, fault_type="EXCEPTION",
                      exception_class="java.io.IOException"),
            ]
            if candidate_only_door_path:
                events += [event("STATE_WRITE", 2, "A", "source", object="o1", key="k",
                                 version=1, version_confidence="sampled"),
                           event("STATE_READ", 3, "B", "target", object="o1", key="k",
                                 version=1, version_confidence="sampled"),
                           event("SEND", 4, "C", "other", transport="rpc",
                                 correlation="c2", port="request"),
                           event("RECV", 5, "B", "target", transport="rpc",
                                 correlation="c2", port="request")]
            elif causal_handoff and not local_timeline_only:
                events += [event("SEND", 2, "A", "source", transport="rpc",
                                 correlation="c1", port="request"),
                           event("RECV", 3, "B", "target", transport="rpc",
                                 correlation="c1", port="request")]
            if trial_id:
                events += [event("FAULT_MATCHED", 8, "A", "source", site=door_site,
                                 door_ordinal=1, fault_id="f1"),
                           event("FAULT_APPLIED", 9, "A", "source", site=door_site,
                                 door_ordinal=1, fault_id="f1")]
            target_node = "A" if local_timeline_only else "B"
            target_occurrence = "source" if local_timeline_only else "target"
            if trial_id:
                target_node = fault_target_node or target_node
                target_occurrence = fault_target_occurrence or target_occurrence
            events += [event("TARGET_CHECK", 10, target_node, target_occurrence,
                             site="C#guard")]
            if trial_id:
                events += [event("TARGET_THROW", 11, target_node, target_occurrence,
                                 site="C#throw",
                                 exception_class="java.io.IOException")]
            trial = campaign / "trials" / f"r{trial_id:04d}"
            trial.mkdir(parents=True)
            raw = b"".join(json.dumps(e).encode() + b"\n" for e in events)
            compressed = trial / "events.jsonl.gz"
            with gzip.open(compressed, "wb") as stream:
                stream.write(raw)
            plan = [trial_fault] if trial_id else []
            feedback = analyze(Trace(tuple(events)), {**target, "nodes": [target_node]}
                               if trial_id else target, plan,
                               return_code=1 if trial_id else 0, timed_out=False,
                               allow_local_timeline_doors=allow_local_timeline_doors)
            coverage = set(feedback["coverage_ids"])
            closure = set(feedback["closure_coverage_ids"])
            edges = {digest([e["source"], e["target"], e["kind"], e["certainty"]])
                     for e in feedback["closure_edges"]}
            novelty = {"coverage": len(coverage - known_coverage),
                       "closure_coverage": len(closure - known_closure),
                       "closure_edges": len(edges - known_edges)}
            known_coverage |= coverage
            known_closure |= closure
            known_edges |= edges
            result = {"case_id": "TEST-AUDIT", "trial_id": trial_id, "plan": plan,
                      "feedback": feedback, "return_code": 1 if trial_id else 0,
                      "timed_out": False, "novelty": novelty,
                      "selection_reason": "dynamic_closure" if trial_id else "healthy_seed",
                      "events_evidence": {"raw_path": None,
                                          "gzip_path": compressed.name,
                                          "raw_sha256": hashlib.sha256(raw).hexdigest(),
                                          "raw_bytes": len(raw),
                                          "gzip_sha256": hashlib.sha256(compressed.read_bytes()).hexdigest(),
                                          "gzip_bytes": compressed.stat().st_size}}
            (trial / "result.json").write_text(json.dumps(result))
            trial_rows.append({"trial_id": trial_id,
                               "result": f"trials/r{trial_id:04d}/result.json"})
        summary = {"case_id": "TEST-AUDIT", "status": "budget_exhausted",
                   "target_binding": {"nodes": sorted({
                       "A" if local_timeline_only else "B",
                       fault_target_node or ("A" if local_timeline_only else "B")})},
                   "trials": trial_rows}
        (campaign / "result.json").write_text(json.dumps(summary))
        return campaign

    def test_full_archive_passes_and_tampering_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = self._archive(root)
            artifact = audit_campaign(campaign, root / "audit.json")
            self.assertTrue(artifact["report_gate_passed"])
            self.assertTrue(artifact["guidance_consistent"])
            self.assertEqual(artifact["named_applied_faults"], 1)
            self.assertEqual(artifact["unknown_applied_faults"], 0)
            self.assertEqual(artifact["target_retained_fault_trials"], 1)
            self.assertTrue(artifact["healthy_closure_proven"])
            self.assertGreater(artifact["healthy_closure_observed_edges"], 0)
            self.assertGreater(artifact["healthy_closure_included_named_doors"], 0)
            self.assertGreater(artifact["healthy_observed_path_doors"], 0)
            self.assertIn("audit.py", artifact["core_source_sha256"])
            self.assertEqual(len(artifact["core_source_sha256"]["audit.py"]), 64)
            self.assertIn("sha256", artifact["trials"][0]["old_eligible_door_membership"])
            self.assertNotIn("e1", artifact["trials"][0]["old_eligible_door_membership"])
            self.assertLessEqual(len(artifact["trials"][0]["eligible_door_membership_diff_sample"]), 10)
            original_result = (campaign / "result.json").read_bytes()
            inside = audit_campaign(campaign, campaign / "offline-causal-audit.json")
            self.assertTrue(inside["report_gate_passed"])
            self.assertEqual((campaign / "result.json").read_bytes(), original_result)
            compressed = campaign / "trials/r0001/events.jsonl.gz"
            compressed.write_bytes(compressed.read_bytes() + b"changed")
            bad = audit_campaign(campaign, root / "bad-audit.json")
            self.assertFalse(bad["archive_integrity_valid"])
            self.assertFalse(bad["report_gate_passed"])
            self.assertIn("compressed trace SHA-256 mismatch", bad["trials"][1]["error"])

    def test_singleton_target_closure_cannot_pass_quality_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = self._archive(root, causal_handoff=False)
            artifact = audit_campaign(campaign, root / "singleton-audit.json")
            self.assertTrue(artifact["archive_integrity_valid"])
            self.assertTrue(artifact["applied_fault_identity_valid"])
            self.assertTrue(artifact["target_claims_reverified"])
            self.assertTrue(artifact["guidance_consistent"])
            self.assertEqual(artifact["healthy_closure_observed_edges"], 0)
            self.assertEqual(artifact["healthy_closure_included_named_doors"], 0)
            self.assertFalse(artifact["healthy_closure_proven"])
            self.assertFalse(artifact["report_gate_passed"])

    def test_candidate_state_path_does_not_prove_door_to_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = self._archive(root, candidate_only_door_path=True)
            artifact = audit_campaign(campaign, root / "candidate-path-audit.json")
            self.assertTrue(artifact["archive_integrity_valid"])
            self.assertTrue(artifact["guidance_consistent"])
            self.assertGreater(artifact["healthy_closure_observed_edges"], 0)
            self.assertGreater(artifact["healthy_closure_included_named_doors"], 0)
            self.assertEqual(artifact["healthy_observed_path_doors"], 0)
            self.assertFalse(artifact["healthy_closure_proven"])
            self.assertFalse(artifact["report_gate_passed"])

    def test_local_timeline_is_opt_in_temporal_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opted = self._archive(root / "opted", causal_handoff=False,
                                  local_timeline_only=True,
                                  allow_local_timeline_doors=True)
            artifact = audit_campaign(opted, root / "local-audit.json")
            self.assertTrue(artifact["report_gate_passed"])
            self.assertEqual(artifact["healthy_closure_observed_edges"], 0)
            self.assertEqual(artifact["healthy_observed_path_doors"], 0)
            self.assertEqual(artifact["healthy_local_timeline_doors"], 1)
            self.assertEqual(artifact["healthy_closure_evidence_types"],
                             ["observed_local_timeline"])
            self.assertTrue(artifact["local_timeline_only"])
            self.assertTrue(artifact["same_actor_target_required"])
            self.assertEqual(artifact["same_actor_target_trials"], 1)
            self.assertTrue(artifact["trials"][1]["same_actor_target_after_fault"])
            self.assertEqual(artifact["trials"][1]["same_actor_target_followups"][0]
                             ["target_check_event_id"], "e10")
            self.assertEqual(artifact["trials"][1]["same_actor_target_followups"][0]
                             ["door_site"], "C#door")
            self.assertEqual(artifact["healthy_local_timeline_evidence_sample"][0]["kind"],
                             "observed_local_timeline")
            default = self._archive(root / "default", causal_handoff=False,
                                    local_timeline_only=True)
            default_audit = audit_campaign(default, root / "default-audit.json")
            self.assertFalse(default_audit["healthy_closure_proven"])
            self.assertFalse(default_audit["report_gate_passed"])

    def test_local_timeline_other_actor_or_occurrence_does_not_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, actor, occurrence in (("other-actor", "B", "target"),
                                             ("other-occurrence", "A", "another")):
                with self.subTest(label=label):
                    campaign = self._archive(root / label, causal_handoff=False,
                                             local_timeline_only=True,
                                             allow_local_timeline_doors=True,
                                             fault_target_node=actor,
                                             fault_target_occurrence=occurrence)
                    audit = audit_campaign(campaign, root / f"{label}-audit.json")
                    self.assertEqual(audit["target_retained_fault_trials"], 1)
                    self.assertTrue(audit["healthy_closure_proven"])
                    self.assertEqual(audit["same_actor_target_trials"], 0)
                    self.assertFalse(audit["trials"][1]["same_actor_target_after_fault"])
                    self.assertFalse(audit["same_actor_target_gate_passed"])
                    self.assertFalse(audit["report_gate_passed"])

    def test_local_timeline_unrelated_door_in_same_occurrence_does_not_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = self._archive(root, causal_handoff=False,
                                     local_timeline_only=True,
                                     allow_local_timeline_doors=True,
                                     fault_door_site="C#unrelated")
            audit = audit_campaign(campaign, root / "unrelated-door-audit.json")
            self.assertEqual(audit["target_retained_fault_trials"], 1)
            self.assertEqual(audit["healthy_local_timeline_sites"], ["C#door"])
            self.assertEqual(audit["same_actor_target_trials"], 0)
            self.assertFalse(audit["report_gate_passed"])

    def test_hbase24_pilot_faults_hit_only_other_members(self):
        workspace = Path(__file__).resolve().parents[2]
        pilot = workspace / "data/mallory/pilots_v24_5a/HBASE-24"
        if not (pilot / "result.json").is_file():
            self.skipTest("preserved HBASE-24 two-fault pilot is unavailable")
        summary = json.loads((pilot / "result.json").read_text())
        target = {**summary["target"], **summary["target_binding"]}
        healthy_result = json.loads((pilot / "trials/r0000/result.json").read_text())
        admitted_sites = {door["site"] for door in healthy_result["feedback"]["doors"]
                          if "local_timeline_evidence" in door}
        self.assertTrue(admitted_sites)
        for trial_id in (1, 2):
            with self.subTest(trial_id=trial_id):
                trial_dir = pilot / "trials" / f"r{trial_id:04d}"
                result = json.loads((trial_dir / "result.json").read_text())
                trace, _ = _load_archived_trace(trial_dir, result)
                self.assertTrue(result["feedback"]["all_faults_effective"])
                self.assertTrue(result["feedback"]["target_reached"])
                self.assertEqual(_same_actor_target_followups(
                    trace.events, target, result["plan"], True,
                    admitted_sites, result["feedback"]["doors"]), [])

    def test_unnamed_injection_is_rejected(self):
        point = {"site": "C#door", "node": "unknown", "epoch": 0,
                 "door_ordinal": 1}
        events = (event("DOOR_OBSERVED", 1, "unknown", "startup", site="C#door",
                        door_ordinal=1),
                  event("FAULT_MATCHED", 2, "unknown", "startup", site="C#door",
                        door_ordinal=1, fault_id="f1"),
                  event("FAULT_APPLIED", 3, "unknown", "startup", site="C#door",
                        door_ordinal=1, fault_id="f1"))
        row = _audit_faults(events, [{"fault_id": "f1", "point": point}])[0]
        self.assertFalse(row["named_actor"])
        self.assertFalse(row["applied_identity_valid"])

    def test_real_zk11_archived_trace_local_timeline_regression(self):
        workspace = Path(__file__).resolve().parents[2]
        source = (workspace / "data/mallory/calibration/ZOOKEEPER-11/"
                  "epoch-file-healthy-v1/events.jsonl")
        case_config = workspace / "Mallory/cases/ZOOKEEPER-11.json"
        if not source.is_file() or not case_config.is_file():
            self.skipTest("archived ZK11 calibration trace is unavailable")
        target = json.loads(case_config.read_text())["target"]
        trace = load_trace(source)
        feedback = analyze(trace, target, [], return_code=0, timed_out=False,
                           allow_local_timeline_doors=True)
        proofs = [door["local_timeline_evidence"] for door in feedback["doors"]
                  if "local_timeline_evidence" in door]
        self.assertEqual(len(proofs), 1)
        self.assertEqual((proofs[0]["door_seq"], proofs[0]["target_check_seq"]),
                         (4618, 4630))
        self.assertEqual((proofs[0]["node"], proofs[0]["epoch"]), ("zk0", 2))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "zk11-diagnostic"
            trial = campaign / "trials/r0000"
            trial.mkdir(parents=True)
            archive = trial / "events.jsonl"
            shutil.copyfile(source, archive)
            (campaign / "config.json").write_text(json.dumps({
                "case_id": "ZOOKEEPER-11", "target": target,
                "allow_local_timeline_doors": True}))
            edge_ids = {digest([e["source"], e["target"], e["kind"], e["certainty"]])
                        for e in feedback["closure_edges"]}
            trial_result = {"case_id": "ZOOKEEPER-11", "trial_id": 0,
                            "plan": [], "feedback": feedback,
                            "return_code": 0, "timed_out": False,
                            "novelty": {"coverage": len(feedback["coverage_ids"]),
                                        "closure_coverage": len(feedback["closure_coverage_ids"]),
                                        "closure_edges": len(edge_ids)},
                            "events_evidence": {"raw_path": "events.jsonl", "gzip_path": None,
                                                "raw_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                                "raw_bytes": archive.stat().st_size}}
            (trial / "result.json").write_text(json.dumps(trial_result))
            (campaign / "result.json").write_text(json.dumps({
                "case_id": "ZOOKEEPER-11", "status": "calibration_complete",
                "calibration_only": True, "target_binding": {"nodes": ["zk0"]},
                "trials": [{"trial_id": 0, "result": "trials/r0000/result.json"}]}))
            artifact = audit_campaign(campaign, root / "zk11-audit.json")
            self.assertTrue(artifact["report_gate_passed"])
            self.assertEqual(artifact["healthy_closure_observed_edges"], 0)
            self.assertEqual(artifact["healthy_observed_path_doors"], 0)
            self.assertEqual(artifact["healthy_local_timeline_doors"], 1)
            self.assertEqual(artifact["healthy_closure_evidence_types"],
                             ["observed_local_timeline"])


if __name__ == "__main__":
    unittest.main()
