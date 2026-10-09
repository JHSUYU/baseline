import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from Mallory.report.build import (_causal_audit, _posthoc_attestation, _quality,
                                  _row, _source_gap, _source_review, build,
                                  markdown)


class ReportEvidenceTest(unittest.TestCase):
    def test_source_only_gap_is_separate_from_audited_workload_gap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "data" / "mallory"
            source = root / "source"
            source.mkdir()
            (source / "Check.java").write_text("class Check {}\n")
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "add", "Check.java"], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=Test",
                            "-c", "user.email=test@example.com", "commit", "-qm", "source"],
                           check=True)
            commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, check=True).stdout.strip()
            old_path = results / "calibration" / "CASE-000" / "trials" / "r0000" / "result.json"
            old_path.parent.mkdir(parents=True)
            old_path.write_text('{"target_reached": false}\n')
            review_path = root / "Mallory" / "cases" / "revisions" / "source-review.json"
            review_path.parent.mkdir(parents=True)
            review_path.write_text(json.dumps({
                "source_root": str(source), "source_commit": commit,
                "cases": [{"case_id": "CASE-000",
                           "category": "no_suitable_existing_cluster_test_proven",
                           "source_refs": [{"path": "Check.java", "sha256": hashlib.sha256(
                               (source / "Check.java").read_bytes()).hexdigest()}],
                           "prior_healthy": {"result_path": str(old_path.relative_to(root)),
                                             "result_sha256": hashlib.sha256(
                                                 old_path.read_bytes()).hexdigest()}}]}))
            receipt_path = results / "source_gaps" / "CASE-000" / "receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps({
                "schema_version": 1, "kind": "source_review_no_suitable_test_v1",
                "case_id": "CASE-000", "status": "source_review_no_suitable_test",
                "review_path": str(review_path.relative_to(root)),
                "review_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest()}))
            self.assertEqual("source_review_no_suitable_test",
                             _source_gap(results, "CASE-000", None))
            (source / "Check.java").write_text("class Changed {}\n")
            self.assertEqual("invalid_source_gap", _source_gap(results, "CASE-000", None))

    def test_source_gap_requires_current_zero_path_proof_and_source_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "data" / "mallory"
            healthy_path = results / "calibration_v8" / "CASE-000" / "result.json"
            healthy_path.parent.mkdir(parents=True)
            healthy = {"case_id": "CASE-000", "status": "calibration_complete",
                       "healthy_seed_valid": True, "fault_trials_completed": 0}
            healthy_path.write_text(json.dumps(healthy))
            healthy_hash = hashlib.sha256(healthy_path.read_bytes()).hexdigest()
            audit_path = healthy_path.with_name("offline-causal-audit.json")
            audit_path.write_text(json.dumps({"campaign_result_sha256": healthy_hash,
                                              "healthy_observed_path_doors": 0,
                                              "report_gate_passed": False}))
            audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
            review_path = root / "Mallory" / "cases" / "revisions" / "review.json"
            review_path.parent.mkdir(parents=True)
            review_path.write_text(json.dumps({
                "status": "no_suitable_existing_cluster_test_identified",
                "cases": [{"case_id": "CASE-000",
                           "current_healthy_result_sha256": healthy_hash,
                           "current_offline_audit_sha256": audit_hash}]}))
            receipt_path = results / "source_gaps" / "CASE-000" / "receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps({
                "schema_version": 1, "case_id": "CASE-000",
                "status": "no_suitable_cluster_test",
                "review_path": "Mallory/cases/revisions/review.json",
                "review_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
                "healthy_result_sha256": healthy_hash, "audit_sha256": audit_hash}))
            calibration = {"path": str(healthy_path)}
            self.assertEqual("no_suitable_cluster_test",
                             _source_gap(results, "CASE-000", calibration))
            audit_path.write_text(json.dumps({"campaign_result_sha256": healthy_hash,
                                              "healthy_observed_path_doors": 1,
                                              "report_gate_passed": True}))
            self.assertEqual("invalid_source_gap",
                             _source_gap(results, "CASE-000", calibration))

    def test_source_review_requires_terminal_result_and_matching_preserved_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_dir = root / "cases" / "CASE-000"
            result_dir.mkdir(parents=True)
            result_path = result_dir / "result.json"
            result = {"case_id": "CASE-000", "status": "budget_exhausted"}
            result_path.write_text(json.dumps(result))
            triage_dir = root / "triage" / "CASE-000"
            triage_dir.mkdir(parents=True)
            evidence = triage_dir / "r0013" / "events.jsonl.gz"
            evidence.parent.mkdir()
            evidence.write_bytes(b"observed events")
            manifest = {"case_id": "CASE-000", "classification": "expected_guard",
                        "files": [{"path": "r0013/events.jsonl.gz",
                                   "bytes": evidence.stat().st_size,
                                   "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]}
            triage_path = triage_dir / "triage.json"
            triage_path.write_text(json.dumps(manifest))
            receipt = {"schema_version": 1, "case_id": "CASE-000",
                       "campaign_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
                       "triage_sha256": hashlib.sha256(triage_path.read_bytes()).hexdigest(),
                       "classification": "expected_guard",
                       "source_review_status": "expected_guard", "new_bug": False}
            (triage_dir / "review.json").write_text(json.dumps(receipt))
            self.assertEqual("expected_guard",
                             _source_review(root, result_path, result)["status"])
            evidence.write_bytes(b"changed events")
            self.assertEqual("invalid_review",
                             _source_review(root, result_path, result)["status"])
            evidence.write_bytes(b"observed events")
            result_path.write_text(json.dumps({**result, "fault_trials_completed": 1}))
            self.assertEqual("invalid_review",
                             _source_review(root, result_path, result)["status"])
            result_path.write_text(json.dumps(result))
            (triage_dir / "review.json").write_text(json.dumps({**receipt, "new_bug": True}))
            self.assertEqual("invalid_review",
                             _source_review(root, result_path, result)["status"])
            self.assertIsNone(_source_review(root, result_path, {**result, "status": "running"}))

    def test_causal_audit_requires_matching_raw_result_and_all_gates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = {"case_id": "CASE-000", "status": "budget_exhausted",
                      "fault_trials_completed": 2, "strict_target_trials": 1}
            path = root / "result.json"
            path.write_text(json.dumps(result))
            audit = {"schema_version": 1, "audit_kind": "offline_causal_quality",
                     "case_id": "CASE-000", "terminal_status": "budget_exhausted",
                     "campaign_result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "trial_count": 3, "archive_integrity_valid": True,
                     "applied_fault_identity_valid": True,
                     "target_claims_reverified": True, "guidance_consistent": True,
                     "healthy_closure_proven": True, "healthy_observed_path_doors": 1,
                     "unknown_applied_faults": 0, "target_retained_fault_trials": 1,
                     "report_gate_passed": True}
            audit_path = root / "offline-causal-audit.json"
            audit_path.write_text(json.dumps(audit))
            self.assertEqual("verified", _causal_audit(path, result))
            audit_path.write_text(json.dumps({**audit, "healthy_closure_proven": False}))
            self.assertEqual("invalid", _causal_audit(path, result))
            audit_path.write_text(json.dumps({**audit, "healthy_observed_path_doors": 0}))
            self.assertEqual("invalid", _causal_audit(path, result))
            path.write_text(json.dumps({**result, "strict_target_trials": 2}))
            self.assertEqual("invalid", _causal_audit(path, result))

    def test_causal_audit_accepts_only_opted_in_matching_local_timeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = {"case_id": "CASE-LOCAL", "status": "budget_exhausted",
                      "fault_trials_completed": 1, "strict_target_trials": 1,
                      "healthy_local_timeline_doors": 1}
            path = root / "result.json"
            path.write_text(json.dumps(result))
            audit = {"schema_version": 1, "audit_kind": "offline_causal_quality",
                     "case_id": "CASE-LOCAL", "terminal_status": "budget_exhausted",
                     "campaign_result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "trial_count": 2, "archive_integrity_valid": True,
                     "applied_fault_identity_valid": True,
                     "target_claims_reverified": True, "guidance_consistent": True,
                     "healthy_closure_proven": True, "healthy_observed_path_doors": 0,
                     "healthy_local_timeline_doors": 1,
                     "healthy_closure_evidence_types": ["observed_local_timeline"],
                     "allow_local_timeline_doors": True,
                     "local_timeline_only": True,
                     "same_actor_target_required": True,
                     "same_actor_target_gate_passed": True,
                     "same_actor_target_trials": 1,
                     "trials": [{"trial_id": 0, "same_actor_target_after_fault": False,
                                 "same_actor_target_followups": []},
                                {"trial_id": 1, "same_actor_target_after_fault": True,
                                 "same_actor_target_followups": [{
                                     "door_event_id": "e1", "fault_event_id": "e2",
                                     "target_check_event_id": "e3", "fault_seq": 2,
                                     "target_check_seq": 3, "node": "A",
                                     "epoch": 0, "occurrence": "source"}]}],
                     "unknown_applied_faults": 0, "target_retained_fault_trials": 1,
                     "report_gate_passed": True}
            audit_path = root / "offline-causal-audit.json"
            audit_path.write_text(json.dumps(audit))
            self.assertEqual("verified", _causal_audit(path, result))
            audit_path.write_text(json.dumps({**audit, "allow_local_timeline_doors": False}))
            self.assertEqual("invalid", _causal_audit(path, result))
            audit_path.write_text(json.dumps({**audit, "healthy_local_timeline_doors": 2}))
            self.assertEqual("invalid", _causal_audit(path, result))
            audit_path.write_text(json.dumps({**audit,
                                              "healthy_closure_evidence_types": ["observed_graph_path"]}))
            self.assertEqual("invalid", _causal_audit(path, result))
            audit_path.write_text(json.dumps({**audit, "same_actor_target_trials": 0}))
            self.assertEqual("invalid", _causal_audit(path, result))
            audit_path.write_text(json.dumps({**audit,
                                              "trials": [{"trial_id": 0}, {"trial_id": 1}]}))
            self.assertEqual("invalid", _causal_audit(path, result))

    def test_terminal_target_exercise_without_causal_audit_stays_unproven(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = {"case_id": "CASE-000", "cohort": "original_102",
                    "system": "example", "system_version": "1",
                    "target": {"source_path": "X.java", "source_line": 10,
                               "function": "X.check", "site_id": "X#u1",
                               "check_code": "throw new E();", "target_exception": "E"},
                    "workload": {"selected_selector": "TestX#test"},
                    "eligibility": {"state": "mapped_test_pending_healthy_calibration",
                                    "may_dispatch_healthy_seed": True}}
            case_dir = root / "cases" / "CASE-000"
            case_dir.mkdir(parents=True)
            (case_dir / "result.json").write_text(json.dumps({
                "case_id": "CASE-000", "status": "budget_exhausted",
                "healthy_seed_valid": True, "runtime_attestation": {"valid": True},
                "strict_injected_trials": 2, "strict_target_trials": 1,
                "fault_trials_completed": 2,
            }))
            row = _row(case, root)
            self.assertEqual("completed_campaign", row["report_status"])
            self.assertEqual("causal_audit_unproven", row["quality_status"])

    def test_posthoc_audit_is_bound_to_unchanged_result_and_exact_sites(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = b"compiled target class"
            compiled_hash = hashlib.sha256(compiled).hexdigest()
            result = {"case_id": "CASE-000", "status": "budget_exhausted",
                      "target": {"check_sites": ["C#check"], "throw_site": "C#throw"},
                      "fault_trials_completed": 2, "strict_injected_trials": 2,
                      "trials": [{"result": f"trials/r{index:04d}/result.json"}
                                 for index in range(3)]}
            path = root / "result.json"
            path.write_text(json.dumps(result))
            for index in range(3):
                trial = root / "trials" / f"r{index:04d}"
                trial.mkdir(parents=True)
                rows = [{"class_name": "C", "bytecode_sha256": compiled_hash,
                         "class_loader_id": "loader", "type": kind, "site": site}
                        for kind, site in (("TARGET_CHECK", "C#check"),
                                           ("TARGET_THROW", "C#throw"))]
                (trial / "sites.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
            archived = root / "posthoc"
            archived.mkdir()
            (archived / "target.class").write_bytes(compiled)
            (archived / "agent.jar").write_bytes(b"agent")
            (archived / "source.tar.gz").write_bytes(b"source")
            audit = {"schema_version": 1, "attestation": "passed", "case_id": "CASE-000",
                     "campaign_status": "budget_exhausted",
                     "campaign_result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "target_source_sha256": "a" * 64,
                     "source_snapshot_path": "posthoc/source.tar.gz",
                     "source_snapshot_sha256": hashlib.sha256(b"source").hexdigest(),
                     "agent_jar_path": "posthoc/agent.jar",
                     "agent_jar_sha256": hashlib.sha256(b"agent").hexdigest(),
                     "exact_check_site": "C#check", "exact_throw_site": "C#throw",
                     "trials_audited": 3, "counts": {"effective_fault": 2},
                     "archived_compiled_target_path": "posthoc/target.class",
                     "archived_compiled_target_sha256": compiled_hash,
                     "loaded_target_class_sha256": [compiled_hash],
                     "target_class_loader_per_trial": [["loader"]] * 3}
            (root / "posthoc-attestation.json").write_text(json.dumps(audit))
            case = {"case_id": "CASE-000"}
            self.assertEqual("verified", _posthoc_attestation(path, case, result))
            path.write_text(json.dumps({**result, "strict_injected_trials": 1}))
            self.assertEqual("invalid", _posthoc_attestation(path, case, result))

    def test_terminal_budget_is_distinct_from_verified_target_exercise(self):
        result = {"status": "budget_exhausted", "healthy_seed_valid": True,
                  "runtime_attestation": {"valid": True},
                  "strict_injected_trials": 4, "strict_target_trials": 0}
        self.assertEqual("target_lost_after_fault", _quality(result))
        result["strict_target_trials"] = 2
        self.assertEqual("target_exercised", _quality(result))
        result["runtime_attestation"]["valid"] = False
        self.assertEqual("runtime_attestation_unproven", _quality(result))

    def test_mapping_gap_is_not_reported_as_ready_to_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = []
            for index in range(102):
                cases.append({
                    "case_id": f"CASE-{index:03d}", "cohort": "original_102",
                    "system": "example", "system_version": "1",
                    "target": {"source_path": "X.java", "source_line": 10,
                               "function": "X.check", "site_id": "X#u1",
                               "check_code": "throw new E();", "target_exception": "E"},
                    "workload": {"selected_selector": "TestX#test"},
                    "eligibility": {"state": "unready", "may_attempt_seed": True,
                                    "may_dispatch_healthy_seed": False,
                                    "bytecode_mapping_status": "unresolved",
                                    "mapping_gaps": ["called_throw_unresolved"]},
                })
            cases[0]["eligibility"] = {"state": "source_infeasible_healthy_guard",
                                        "may_dispatch_healthy_seed": False,
                                        "mapping_gaps": ["guard_implies_target_throw"]}
            inventory = root / "inventory.json"
            inventory.write_text(json.dumps({"cases": cases}))
            report = build(inventory, root / "results")
            self.assertEqual(101, report["counts"]["target_mapping_gap"])
            self.assertEqual(1, report["counts"]["source_infeasible_healthy_guard"])
            self.assertEqual(["guard_implies_target_throw"], report["rows"][0]["mapping_gaps"])

    def test_missing_result_is_pending_and_does_not_inherit_legacy_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = []
            for index in range(102):
                cases.append({
                    "case_id": f"CASE-{index:03d}", "cohort": "original_102",
                    "system": "example", "system_version": "1",
                    "target": {"source_path": "X.java", "source_line": 10,
                               "function": "X.check", "site_id": "X#u1",
                               "check_code": "throw new E();", "target_exception": "E"},
                    "workload": {"selected_selector": "TestX#test"},
                    "eligibility": {"state": "mapped_test_pending_healthy_calibration",
                                    "may_attempt_seed": True},
                })
            inventory = root / "inventory.json"
            inventory.write_text(json.dumps({"cases": cases}))
            report = build(inventory, root / "results")
            self.assertEqual(102, report["counts"]["pending_seed"])
            self.assertIsNone(report["rows"][0]["strict_injected_trials"])
            self.assertIn("| Strict injected trials |", markdown(report))

            calibration = root / "results" / "calibration" / "CASE-000"
            calibration.mkdir(parents=True)
            (calibration / "result.json").write_text(json.dumps({
                "case_id": "CASE-000", "status": "calibration_complete",
                "duration_seconds": 3.5,
            }))
            report = build(inventory, root / "results")
            self.assertEqual(102, report["counts"]["pending_seed"])
            self.assertEqual(1, report["calibration_counts"]["calibration_complete"])
            self.assertEqual(3.5, report["rows"][0]["calibration_duration_seconds"])

            calibration_v2 = root / "results" / "calibration_v2" / "CASE-000"
            calibration_v2.mkdir(parents=True)
            (calibration_v2 / "result.json").write_text(json.dumps({
                "case_id": "CASE-000", "status": "healthy_no_injectable_door",
                "cluster_test": "TestX#alternate",
                "duration_seconds": 5.25,
            }))
            report = build(inventory, root / "results")
            self.assertEqual("healthy_no_injectable_door",
                             report["rows"][0]["calibration_status"])
            self.assertEqual(2, len(report["rows"][0]["calibration_history"]))
            self.assertEqual(5.25, report["rows"][0]["calibration_duration_seconds"])
            self.assertEqual("TestX#test", report["rows"][0]["cluster_test"])
            self.assertEqual("TestX#alternate",
                             report["rows"][0]["calibration_cluster_test"])

            case_dir = root / "results" / "cases" / "CASE-000"
            case_dir.mkdir(parents=True)
            (case_dir / "result.json").write_text(json.dumps({
                "case_id": "CASE-000", "status": "budget_exhausted",
                "duration_seconds": 12.4, "strict_injected_trials": 3,
                "target_reached_trials": 2, "exact_exception_trials": 1,
                "source_review_status": "not_reviewed", "new_bug": None,
            }))
            report = build(inventory, root / "results")
            self.assertEqual(101, report["counts"]["pending_seed"])
            self.assertEqual(1, report["counts"]["completed_campaign"])
            self.assertEqual(3, report["rows"][0]["strict_injected_trials"])
            self.assertIsNone(report["rows"][0]["new_bug"])


if __name__ == "__main__":
    unittest.main()
