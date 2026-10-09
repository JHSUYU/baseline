import json
import gzip
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from Mallory.report.build import (_causal_audit, _causal_precision_review,
                                  _event_path_review, _faulted_path_review,
                                  _local_timeline_review,
                                  _posthoc_attestation, _quality,
                                  _row, _source_gap, _source_review, build,
                                  markdown)


class ReportEvidenceTest(unittest.TestCase):
    def test_local_timeline_receipt_requires_raw_named_occurrence_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary) / "data" / "mallory"
            case = results / "cases" / "CASE-000"
            trial_dir = case / "trials" / "r0001"
            trial_dir.mkdir(parents=True)
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            write = lambda path, value: path.write_text(json.dumps(value))
            result = {"case_id": "CASE-000", "fault_trials_completed": 1,
                      "strict_target_trials": 1,
                      "target": {"check_sites": ["X#check"]}}
            result_path = case / "result.json"
            write(result_path, result)
            audit_path = case / "offline-causal-audit.json"
            write(audit_path, {"report_gate_passed": True, "local_timeline_only": True,
                               "same_actor_target_gate_passed": True,
                               "campaign_result_sha256": digest(result_path),
                               "same_actor_target_trials": 1})
            config_path = case / "config.json"
            write(config_path, {})
            occurrence = "node1:0:X#reload:unique:1"
            def event(kind, seq, **extra):
                return {"id": f"CASE-000-r0001:{seq}", "type": kind,
                        "seq": seq, "node": "node1", "epoch": 0,
                        "occurrence": occurrence, "thread": "worker",
                        "thread_id": None, **extra}
            events = [event("REGION_ENTER", 1), event("DOOR_OBSERVED", 2,
                       site="X#door"), event("FAULT_APPLIED", 3,
                       site="X#door", fault_id="f1"), event("TARGET_CHECK", 4,
                       site="X#check")]
            raw = b"".join((json.dumps(item) + "\n").encode() for item in events)
            trace_path = trial_dir / "events.jsonl.gz"
            with gzip.open(trace_path, "wb") as stream:
                stream.write(raw)
            trial_path = trial_dir / "result.json"
            write(trial_path, {
                "events_evidence": {"gzip_sha256": digest(trace_path),
                                    "raw_sha256": hashlib.sha256(raw).hexdigest()},
                "feedback": {"target_reached": True, "all_faults_effective": True,
                             "all_faults_applied": True, "target_identity_complete": True,
                             "last_fault_seq": 3, "applied_fault_ids": ["f1"]}})
            sidecars = results / "audit_sidecars"
            sidecars.mkdir(parents=True)
            prior_path = sidecars / "prior.json"
            write(prior_path, {"campaign_result_sha256": digest(result_path),
                               "offline_causal_audit_sha256": digest(audit_path)})
            witnesses_path = sidecars / "witnesses.json"
            write(witnesses_path, {
                "case_id": "CASE-000", "campaign_result_sha256": digest(result_path),
                "offline_causal_audit_sha256": digest(audit_path),
                "prior_precision_receipt_sha256": digest(prior_path),
                "qualifying_trials": 1, "trials": [{
                    "trial_id": 1, "trial_result_sha256": digest(trial_path),
                    "trace_gzip_sha256": digest(trace_path),
                    "trace_gzip_bytes": trace_path.stat().st_size,
                    "trace_raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "trace_raw_bytes": len(raw), "witnesses": [{
                        "node": "node1", "epoch": 0, "occurrence": occurrence,
                        "thread": "worker", "door": {"id": "CASE-000-r0001:2",
                                                    "site": "X#door"},
                        "fault": {"id": "CASE-000-r0001:3", "site": "X#door",
                                  "fault_id": "f1"},
                        "target_check": {"id": "CASE-000-r0001:4",
                                         "site": "X#check"}}]}]})
            sync_path = case / "sync-receipt.json"
            retained = {"result.json": {"sha256": digest(result_path),
                                        "bytes": result_path.stat().st_size}}
            write(sync_path, {"result_sha256": digest(result_path),
                              "retained_files": retained,
                              "remote_only_scratch_files": {}})
            archive = results / "evidence_archives" / "campaign" / "CASE-000.tar.gz"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"archive")
            manifest = archive.with_suffix(".manifest.json")
            write(manifest, {"case_id": "CASE-000", "members": retained,
                             "source_result_sha256": digest(result_path),
                             "config_sha256": digest(config_path),
                             "archive_sha256": digest(archive)})
            root = results / "quality_reviews" / "local_timeline_v1"
            root.mkdir(parents=True)
            receipt_path = root / "CASE-000.json"
            write(receipt_path, {
                "schema_version": 1, "kind": "verified_faulted_local_timeline_v1",
                "case_id": "CASE-000", "campaign_result_sha256": digest(result_path),
                "offline_audit_sha256": digest(audit_path),
                "config_sha256": digest(config_path),
                "archive_sha256": digest(archive),
                "archive_manifest_sha256": digest(manifest),
                "sync_receipt_sha256": digest(sync_path),
                "prior_precision_receipt": "data/mallory/audit_sidecars/prior.json",
                "prior_precision_receipt_sha256": digest(prior_path),
                "trial_witnesses_receipt": "data/mallory/audit_sidecars/witnesses.json",
                "trial_witnesses_receipt_sha256": digest(witnesses_path),
                "qualifying_trial_count": 1,
                "thread_identity": "thread_name_plus_unique_reload_occurrence",
                "numeric_thread_id_proven": False,
                "one_region_enter_per_witness_actor": True})
            write(root / "index.json", {
                "schema_version": 1,
                "review_status": "verified_faulted_local_timeline",
                "cases": [{"case_id": "CASE-000",
                           "classification": "observed_local_timeline",
                           "receipt_sha256": digest(receipt_path),
                           "result_sha256": digest(result_path),
                           "audit_sha256": digest(audit_path),
                           "archive_sha256": digest(archive),
                           "qualifying_trial_count": 1}]})
            self.assertEqual("observed_local_timeline",
                             _local_timeline_review(results, result_path, result)[0])
            trace_path.write_bytes(trace_path.read_bytes() + b"tampered")
            self.assertEqual("invalid",
                             _local_timeline_review(results, result_path, result)[0])

    def test_event_path_receipt_requires_ordered_matching_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary) / "data" / "mallory"
            case_id = "CASE-000"
            case = results / "cases" / case_id
            case.mkdir(parents=True)
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            result = {"case_id": case_id, "fault_trials_completed": 1,
                      "strict_target_trials": 1,
                      "target": {"check_sites": ["X#check"]}}
            result_path = case / "result.json"
            result_path.write_text(json.dumps(result))
            audit_path = case / "offline-causal-audit.json"
            audit_path.write_text("{}")
            config_path = case / "config.json"
            config_path.write_text("{}")
            rows = []
            for trial_id in (0, 1):
                path = case / "trials" / f"r{trial_id:04d}" / "result.json"
                path.parent.mkdir(parents=True)
                evidence = {"raw_sha256": "a" * 64}
                if trial_id == 1:
                    def event(kind, seq, occurrence, **extra):
                        return {"id": f"{case_id}-r0001:{seq}", "type": kind,
                                "node": "peer1", "epoch": 0, "thread": "worker",
                                "occurrence": occurrence, "seq": seq, **extra}
                    token = "zk-following-retry:1:1:2:3:1"
                    events = [
                        event("REGION_ENTER", 1, "old"),
                        event("FAULT_APPLIED", 2, "old"),
                        event("TASK_SUBMIT", 3, "old", correlation=token),
                        event("REGION_EXIT", 4, "old"),
                        event("REGION_ENTER", 5, "new"),
                        event("TASK_CLAIM", 6, "new", correlation=token,
                              parent_id=token),
                        event("REGION_ENTER", 7, "target", parent_id="new"),
                        event("TARGET_CHECK", 8, "target", site="X#check")]
                    raw = b"".join((json.dumps(item) + "\n").encode() for item in events)
                    gz = path.parent / "events.jsonl.gz"
                    with gzip.open(gz, "wb") as stream:
                        stream.write(raw)
                    evidence = {"raw_sha256": hashlib.sha256(raw).hexdigest(),
                                "raw_bytes": len(raw), "gzip_path": gz.name,
                                "gzip_sha256": digest(gz), "gzip_bytes": gz.stat().st_size}
                path.write_text(json.dumps({"events_evidence": evidence}))
                rows.append({"trial_id": trial_id, "trial_result_sha256": digest(path),
                             "trace_raw_sha256": evidence["raw_sha256"],
                             "applied_fault_event_ids": [], "verified_retry_edges": [],
                             "postfault_retry_target_paths": []})
            prefix = f"{case_id}-r0001:"
            rows[1]["applied_fault_event_ids"] = [prefix + "2"]
            rows[1]["verified_retry_edges"] = [{
                "producer_event": prefix + "3", "consumer_event": prefix + "6",
                "token": token, "node": "peer1", "epoch": 0, "thread": "worker"}]
            rows[1]["postfault_retry_target_paths"] = [{
                "fault_event": prefix + "2", "old_enter_event": prefix + "1",
                "submit_event": prefix + "3", "old_exit_event": prefix + "4",
                "new_enter_event": prefix + "5", "claim_event": prefix + "6",
                "target_enter_event": prefix + "7", "target_check_event": prefix + "8",
                "token": token, "node": "peer1", "epoch": 0,
                "thread": "worker",
                "evidence_type": "observed_task_edge_and_same_thread_retry_continuation"}]
            root = results / "quality_reviews" / "causal_precision_v3"
            root.mkdir(parents=True)
            receipt_path = root / "CASE-000-path.json"
            receipt = {"schema_version": 1, "case_id": case_id,
                       "status": "postfault_retry_target_proven",
                       "campaign_result_sha256": digest(result_path),
                       "offline_audit_sha256": digest(audit_path),
                       "config_sha256": digest(config_path),
                       "proven_postfault_path_trials": 1, "trials": rows}
            receipt_path.write_text(json.dumps(receipt))
            archive = results / "evidence_archives" / "campaign" / "CASE-000.tar.gz"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"archive")
            manifest_path = archive.with_suffix(".manifest.json")
            manifest_path.write_text(json.dumps({
                "case_id": case_id, "archive_sha256": digest(archive),
                "campaign_result_sha256": digest(result_path),
                "offline_audit_sha256": digest(audit_path),
                "config_sha256": digest(config_path),
                "continuation_receipt_sha256": digest(receipt_path),
                "strict_path_trials": 1}))
            (root / "index.json").write_text(json.dumps({
                "schema_version": 1, "review_status": "verified_faulted_event_path",
                "cases": [{"case_id": case_id, "classification": "observed_event_path",
                           "receipt": "data/mallory/quality_reviews/causal_precision_v3/CASE-000-path.json",
                           "receipt_sha256": digest(receipt_path),
                           "result_sha256": digest(result_path),
                           "audit_sha256": digest(audit_path),
                           "config_sha256": digest(config_path),
                           "archive_sha256": digest(archive),
                           "archive_manifest_sha256": digest(manifest_path),
                           "qualifying_trial_count": 1}]}))
            self.assertEqual("observed_event_path", _event_path_review(
                results, result_path, result)[0])
            compressed = case / "trials" / "r0001" / "events.jsonl.gz"
            original_trace = compressed.read_bytes()
            compressed.write_bytes(original_trace + b"tampered")
            self.assertEqual("invalid", _event_path_review(
                results, result_path, result)[0])
            compressed.write_bytes(original_trace)
            rows[1]["postfault_retry_target_paths"][0]["target_check_event"] = prefix + "1"
            receipt_path.write_text(json.dumps(receipt))
            self.assertEqual("invalid", _event_path_review(
                results, result_path, result)[0])

    def test_faulted_path_receipt_requires_canonical_hashes_and_region_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary) / "data" / "mallory"
            campaign = results / "cases" / "CASE-000"
            campaign.mkdir(parents=True)
            result = {"case_id": "CASE-000", "strict_target_trials": 1}
            result_path = campaign / "result.json"
            result_path.write_text(json.dumps(result))
            audit_path = campaign / "offline-causal-audit.json"
            audit_path.write_text("{}")
            config_path = campaign / "config.json"
            config_path.write_text("{}")
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            root = results / "quality_reviews" / "faulted_path_v1"
            root.mkdir(parents=True)
            receipt = {"schema_version": 1, "case_id": "CASE-000",
                       "classification": "legacy_faulted_region_evidence",
                       "recommended_quality_status": "retain_legacy_faulted_region_evidence",
                       "canonical_result_sha256": digest(result_path),
                       "canonical_audit_sha256": digest(audit_path),
                       "canonical_config_sha256": digest(config_path),
                       "strict_target_trials": 1,
                       "same_region_continuation_trials": 1,
                       "root_free_occurrence_path_trials": 1,
                       "same_actor_named_thread_order_trials": 1,
                       "ordered_root_free_region_path_trials": 0,
                       "trials": [{"trial_id": 1, "trial_result_sha256": "a" * 64,
                                   "raw_trace_sha256": "b" * 64,
                                   "applied_event_ids": ["CASE-000-r0001:1"],
                                   "postfault_target_check_count": 1,
                                   "same_region_continuation": True,
                                   "ordered_root_free_region_path": False}]}
            receipt_path = root / "CASE-000.json"
            receipt_path.write_text(json.dumps(receipt))
            entry = {"case_id": "CASE-000",
                     "classification": "legacy_faulted_region_evidence",
                     "recommended_quality_status": "retain_legacy_faulted_region_evidence",
                     "review_sha256": digest(receipt_path),
                     "strict_target_trials": 1,
                     "same_region_continuation_trials": 1,
                     "same_actor_named_thread_order_trials": 1,
                     "ordered_root_free_region_path_trials": 0}
            audit_source = Path(__file__).resolve().parents[1] / "ops" / "audit_faulted_precision.py"
            source_hash = digest(audit_source)
            (root / "index.json").write_text(json.dumps({
                "schema_version": 1, "cohort": ["CASE-000"], "rows": [entry],
                "source_sha256": source_hash}))
            self.assertEqual(("observed_local_timeline", str(receipt_path)),
                             _faulted_path_review(results, result_path, result))
            receipt["same_region_continuation_trials"] = 0
            receipt_path.write_text(json.dumps(receipt))
            self.assertEqual("invalid", _faulted_path_review(
                results, result_path, result)[0])
            receipt["same_region_continuation_trials"] = 1
            receipt_path.write_text(json.dumps(receipt))
            entry["review_sha256"] = digest(receipt_path)
            (root / "index.json").write_text(json.dumps({
                "schema_version": 1, "cohort": ["CASE-000"], "rows": [entry],
                "source_sha256": source_hash}))
            config_path.write_text('{"changed": true}')
            self.assertEqual("invalid", _faulted_path_review(
                results, result_path, result)[0])

    def test_precision_sidecar_downgrades_only_matching_terminal_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "data" / "mallory"
            case_id = "CASE-000"
            case = {"case_id": case_id, "cohort": "original_102",
                    "system": "example", "system_version": "1",
                    "target": {"source_path": "X.java", "source_line": 10,
                               "function": "X.check", "site_id": "X#u1",
                               "check_code": "throw new E();", "target_exception": "E"},
                    "workload": {"selected_selector": "TestX#test"},
                    "eligibility": {"state": "mapped_test_pending_healthy_calibration",
                                    "may_dispatch_healthy_seed": True}}
            campaign = results / "cases" / case_id
            campaign.mkdir(parents=True)
            result = {"case_id": case_id, "status": "budget_exhausted",
                      "healthy_seed_valid": True, "runtime_attestation": {"valid": True},
                      "strict_injected_trials": 2, "strict_target_trials": 1,
                      "fault_trials_completed": 2, "duration_seconds": 12.4}
            result_path = campaign / "result.json"
            result_path.write_text(json.dumps(result))
            result_hash = hashlib.sha256(result_path.read_bytes()).hexdigest()
            audit = {"schema_version": 1, "audit_kind": "offline_causal_quality",
                     "case_id": case_id, "terminal_status": "budget_exhausted",
                     "campaign_result_sha256": result_hash, "trial_count": 3,
                     "archive_integrity_valid": True, "applied_fault_identity_valid": True,
                     "target_claims_reverified": True, "guidance_consistent": True,
                     "healthy_closure_proven": True, "healthy_observed_path_doors": 1,
                     "healthy_closure_evidence_types": ["observed_graph_path"],
                     "unknown_applied_faults": 0, "target_retained_fault_trials": 1,
                     "report_gate_passed": True}
            audit_path = campaign / "offline-causal-audit.json"
            audit_path.write_text(json.dumps(audit))
            audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
            self.assertEqual("causal_precision_pending", _row(case, results)["quality_status"])

            reviews = results / "quality_reviews" / "causal_precision_v2"
            reviews.mkdir(parents=True)
            receipt = {"schema_version": 2, "case_id": case_id,
                       "classification": "causal_precision_unverified",
                       "canonical_files_modified": False,
                       "canonical_result": f"data/mallory/cases/{case_id}/result.json",
                       "canonical_audit": f"data/mallory/cases/{case_id}/offline-causal-audit.json",
                       "canonical_result_sha256": result_hash,
                       "canonical_audit_sha256": audit_hash,
                       "campaign_status": "budget_exhausted",
                       "duration_seconds": 12.4, "fault_trials_completed": 2,
                       "strict_postfault_target_trials": 1,
                       "root_free_qualifying_trial_ids": [],
                       "evidence_category": "root_intermediary_only"}
            receipt_path = reviews / f"{case_id}.json"
            receipt_path.write_text(json.dumps(receipt))
            entry = {"case_id": case_id,
                     "classification": "causal_precision_unverified",
                     "sidecar": f"data/mallory/quality_reviews/causal_precision_v2/{case_id}.json",
                     "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                     "result_sha256": result_hash, "audit_sha256": audit_hash}
            (reviews / "index.json").write_text(json.dumps({
                "schema_version": 2,
                "review_status": "provisional_scientific_classification",
                "weak_case_ids": [case_id], "cases": [entry]}))
            row = _row(case, results)
            self.assertEqual("completed_campaign", row["report_status"])
            self.assertEqual("verified", row["causal_audit"])
            self.assertEqual("causal_precision_unverified", row["quality_status"])
            self.assertEqual(12.4, row["duration_seconds"])
            self.assertEqual(1, row["strict_target_trials"])
            self.assertEqual(("causal_precision_unverified", str(receipt_path)),
                             _causal_precision_review(results, result_path, result))

            receipt["evidence_category"] = "root_free_door_unmatched"
            receipt_path.write_text(json.dumps(receipt))
            entry["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            (reviews / "index.json").write_text(json.dumps({
                "schema_version": 2,
                "review_status": "provisional_scientific_classification",
                "weak_case_ids": [case_id], "cases": [entry]}))
            self.assertEqual("causal_precision_unverified", _row(case, results)["quality_status"])

            receipt["evidence_category"] = "faulted_path_unverified"
            receipt_path.write_text(json.dumps(receipt))
            entry["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            (reviews / "index.json").write_text(json.dumps({
                "schema_version": 2,
                "review_status": "provisional_scientific_classification",
                "weak_case_ids": [case_id], "cases": [entry]}))
            self.assertEqual("causal_precision_unverified", _row(case, results)["quality_status"])

            (reviews / "index.json").write_text(json.dumps({
                "schema_version": 2,
                "review_status": "provisional_scientific_classification",
                "weak_case_ids": [], "cases": [entry]}))
            self.assertEqual("causal_precision_review_invalid", _row(case, results)["quality_status"])

            (reviews / "index.json").write_text(json.dumps({
                "schema_version": 2,
                "review_status": "provisional_scientific_classification",
                "weak_case_ids": [case_id], "cases": [{**entry, "sha256": "0" * 64}]}))
            self.assertEqual("causal_precision_review_invalid", _row(case, results)["quality_status"])

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

    def test_source_weak_candidate_is_hash_checked_and_nonterminal(self):
        from Mallory.report.build import _source_weak_candidate

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "data" / "mallory"
            source = root / "source"
            source.mkdir()
            source_file = source / "Check.java"
            source_file.write_text("class Check {}\n")
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "add", "Check.java"], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=Test",
                            "-c", "user.email=test@example.com", "commit", "-qm", "source"],
                           check=True)
            commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, check=True).stdout.strip()
            old_path = results / "calibration" / "CASE-000" / "result.json"
            old_path.parent.mkdir(parents=True)
            old_path.write_text(json.dumps({"case_id": "CASE-000",
                                            "status": "healthy_node_identity_missing",
                                            "fault_trials_completed": 0}))
            triage_path = root / "Mallory" / "triage.json"
            triage_path.parent.mkdir(parents=True)
            triage_path.write_text("{}\n")
            review_path = root / "Mallory" / "weak.json"
            review_path.write_text(json.dumps({
                "case_id": "CASE-000",
                "classification": "configuration_local_weak_static_candidate",
                "source_root": str(source), "source_commit": commit,
                "source_refs": [{"path": "Check.java", "sha256": hashlib.sha256(
                    source_file.read_bytes()).hexdigest()}],
                "prior_calibration": {"result_path": str(old_path.relative_to(root)),
                                      "result_sha256": hashlib.sha256(old_path.read_bytes()).hexdigest(),
                                      "status": "healthy_node_identity_missing"},
                "prior_triage": {"path": str(triage_path.relative_to(root)),
                                 "sha256": hashlib.sha256(triage_path.read_bytes()).hexdigest()},
            }))
            receipt_path = results / "source_weak" / "CASE-000" / "receipt-v1.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps({
                "schema_version": 1, "kind": "source_weak_candidate_v1",
                "case_id": "CASE-000", "status": "source_weak_candidate",
                "review_path": str(review_path.relative_to(root)),
                "review_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest()}))
            self.assertEqual("source_weak_candidate",
                             _source_weak_candidate(results, "CASE-000"))
            old_path.write_text('{"case_id":"CASE-000","status":"changed"}')
            self.assertEqual("invalid_source_weak",
                             _source_weak_candidate(results, "CASE-000"))

    def test_unreliable_healthy_target_requires_all_three_preserved_misses(self):
        from Mallory.report.build import _healthy_target_unreliable

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "data" / "mallory"

            def write(name, data):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
                return {"path": name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

            old_result = write("data/mallory/calibration_v13/CASE-000/result.json",
                               {"case_id": "CASE-000", "status": "calibration_complete",
                                "healthy_seed_valid": True, "fault_trials_completed": 0,
                                "runtime_attestation": {
                                    "valid": True, "exact_site_catalog_valid": True,
                                    "bound_nodes": ["node0"]}})
            old_trial = write("data/mallory/calibration_v13/CASE-000/trials/r0000/result.json",
                              {"feedback": {"target_reached": True,
                                            "target_identity_complete": True,
                                            "target_threw": False}})
            attempts = []
            for version in (21, 22, 23):
                prefix = f"data/mallory/calibration_v{version}/CASE-000"
                result = write(prefix + "/result.json", {
                    "case_id": "CASE-000", "status": "healthy_seed_invalid",
                    "healthy_seed_valid": False, "fault_trials_completed": 0,
                    "trials": [{"status": "healthy_target_missing",
                                "target_reached": False}]})
                audit = write(prefix + "/offline-causal-audit.json", {
                    "campaign_result_sha256": result["sha256"],
                    "archive_integrity_valid": True, "report_gate_passed": False,
                    "healthy_observed_path_doors": 0})
                junit = write(prefix + "/trials/r0000/junit-receipt.json", {
                    "status": "passed", "tests": 1, "failures": 0, "errors": 0})
                trace = write(prefix + "/trials/r0000/events.jsonl.gz", {})
                attempts.append({
                    "cohort": f"v{version}",
                    "result_path": result["path"], "result_sha256": result["sha256"],
                    "audit_path": audit["path"], "audit_sha256": audit["sha256"],
                    "junit_receipt_path": junit["path"],
                    "junit_receipt_sha256": junit["sha256"],
                    "trace_path": trace["path"], "trace_sha256": trace["sha256"],
                    "exact_target_reached": False, "junit_passed": True,
                    "target_site_catalog_valid": True})
            write("data/mallory/target_unreliable/CASE-000/receipt.json", {
                "schema_version": 1, "kind": "healthy_target_unreliable_v1",
                "case_id": "CASE-000", "status": "healthy_target_unreliable",
                "terminal_classification": False, "fault_trials_completed": 0,
                "prior_positive_target_evidence": {
                    "result_path": old_result["path"],
                    "result_sha256": old_result["sha256"],
                    "trial_result_path": old_trial["path"],
                    "trial_result_sha256": old_trial["sha256"],
                    "target_reached": True},
                "new_hook_attempts": attempts})
            self.assertEqual("healthy_target_unreliable",
                             _healthy_target_unreliable(results, "CASE-000"))
            (root / attempts[2]["junit_receipt_path"]).write_text(
                '{"status":"failed"}')
            self.assertEqual("invalid_target_unreliable",
                             _healthy_target_unreliable(results, "CASE-000"))

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
