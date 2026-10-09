import json
import gzip
import hashlib
import io
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from Mallory.report.build import (_causal_audit, _causal_precision_review,
                                  _event_path_review, _faulted_path_review,
                                  _hdfs11_faulted_event_review,
                                  _local_timeline_review,
                                  _posthoc_attestation, _quality,
                                  _row, _source_gap, _source_review, build,
                                  markdown)


class ReportEvidenceTest(unittest.TestCase):
    def test_zk06_retry_gap_requires_same_packet_raw_lineage(self):
        from Mallory.report.build import _zk06_retry_guard_gap
        baseline = Path(__file__).resolve().parents[2]
        source = baseline / "data/mallory"
        names = (
            "admissions/ZOOKEEPER-06-ackepoch-retry-door-node1-negative-v1.json",
            "admissions/ZOOKEEPER-06-ackepoch-retry-door-node1-source-gap-v1.json",
            "admissions/ZOOKEEPER-06-ackepoch-retry-door-node1-healthy-v1.json",
            "pilots/ZOOKEEPER-06-ackepoch-retry-door-node1-v1/focused-pilot-result.json",
            "pilots/ZOOKEEPER-06-ackepoch-retry-door-node1-v1/config.json",
            "pilots/ZOOKEEPER-06-ackepoch-retry-door-node1-v1/pilot-plan.json",
            "pilots/ZOOKEEPER-06-ackepoch-retry-door-node1-v1/trials/r0001/result.json",
            "pilots/ZOOKEEPER-06-ackepoch-retry-door-node1-v1/trials/r0001/events.jsonl.gz",
            "quality_reviews/zk06_ackepoch_retry_gap/index.json",
        )
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary) / "data/mallory"
            for name in names:
                target = results / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, target)
            shutil.copytree(source / "source_snapshots/ZOOKEEPER-06-ackepoch-retry-v1",
                            results / "source_snapshots/ZOOKEEPER-06-ackepoch-retry-v1")
            self.assertEqual(_zk06_retry_guard_gap(results, "ZOOKEEPER-06")[0],
                             "fault_model_target_guard_skipped_on_retry")
            trace = results / names[7]
            trace.write_bytes(trace.read_bytes() + b"tampered")
            index_path = results / names[8]
            index = json.loads(index_path.read_text())
            index["pilot_trace_gzip_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
            index_path.write_text(json.dumps(index))
            self.assertEqual(_zk06_retry_guard_gap(results, "ZOOKEEPER-06")[0],
                             "invalid_fault_model_receipt")

    def test_solr38_39_source_gaps_replay_and_reject_rehashed_claims(self):
        from Mallory.report.build import _solr38_39_source_gap
        baseline = Path(__file__).resolve().parents[2]
        original = baseline / "data/mallory/quality_reviews"
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary) / "data/mallory"
            for case_id in ("SOLR-38", "SOLR-39"):
                tag = case_id.lower().replace("-", "")
                folder = f"{tag}_source_gap"
                target = results / "quality_reviews" / folder
                target.mkdir(parents=True)
                for name in ("index.json", f"{case_id}.json"):
                    shutil.copy2(original / folder / name, target / name)
                status, _ = _solr38_39_source_gap(results, case_id)
                self.assertIn(status, {"fault_model_current_typed_io_no_retained_target",
                                       "source_review_selector_and_io_path_unproven"})
                receipt_path = target / f"{case_id}.json"
                receipt = json.loads(receipt_path.read_text())
                receipt["source_finding"] = "changed claim"
                receipt_path.write_text(json.dumps(receipt))
                index_path = target / "index.json"
                index = json.loads(index_path.read_text())
                index["receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
                index_path.write_text(json.dumps(index))
                self.assertEqual(_solr38_39_source_gap(results, case_id)[0],
                                 "invalid_fault_model_receipt")

    def test_hbase02_compact_archive_gate_rejects_member_tamper(self):
        from Mallory.report.build import _hbase02_offhost_review
        baseline = Path(__file__).resolve().parents[2]
        source = baseline / "data/mallory"
        names = (
            "cases/HBASE-02/result.json",
            "cases/HBASE-02/config.json",
            "cases/HBASE-02/offline-causal-audit.json",
            "HBASE-02/campaigns/request-token-scoped-v4-full-offhost/result.json",
            "HBASE-02/campaigns/request-token-scoped-v4-full-offhost/config.json",
            "HBASE-02/campaigns/request-token-scoped-v4-full-offhost/offline-causal-audit.json",
            "HBASE-02/campaigns/request-token-scoped-v4-full-offhost/negative-receipt.json",
            "evidence_archives/campaign_request_token_scoped_v4/HBASE-02.tar.gz",
            "quality_reviews/hbase02_v4_offhost/index.json",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "data/mallory"
            for name in names:
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, dest)
            result_path = root / "cases/HBASE-02/result.json"
            result = json.loads(result_path.read_text())
            review = lambda: _hbase02_offhost_review(root, result_path, result)[0]
            self.assertEqual(review(), "faulted_path_unverified")
            archive = root / "evidence_archives/campaign_request_token_scoped_v4/HBASE-02.tar.gz"
            rewritten = archive.with_suffix(".tampered.gz")
            with tarfile.open(archive, "r:gz") as original, \
                 tarfile.open(rewritten, "w:gz") as changed:
                for member in original:
                    if not member.isfile():
                        changed.addfile(member)
                        continue
                    stream = original.extractfile(member)
                    self.assertIsNotNone(stream)
                    payload = stream.read()
                    if member.name.endswith("trials/r0002/events.jsonl.gz"):
                        payload += b"tampered"
                        member.size = len(payload)
                    changed.addfile(member, io.BytesIO(payload))
            rewritten.replace(archive)
            receipt_path = root / "HBASE-02/campaigns/request-token-scoped-v4-full-offhost/negative-receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
            receipt["archive_bytes"] = archive.stat().st_size
            receipt_path.write_text(json.dumps(receipt))
            index_path = root / "quality_reviews/hbase02_v4_offhost/index.json"
            index = json.loads(index_path.read_text())
            index["archive_sha256"] = receipt["archive_sha256"]
            index["receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            index_path.write_text(json.dumps(index))
            self.assertEqual(review(), "invalid")

    def test_zk12_terminal_review_rechecks_archive_and_trial_identity(self):
        from Mallory.report.build import _zk12_filenotfound_review
        baseline = Path(__file__).resolve().parents[2]
        source = baseline / "data/mallory"
        names = (
            "cases/ZOOKEEPER-12/result.json",
            "cases/ZOOKEEPER-12/config.json",
            "cases/ZOOKEEPER-12/offline-causal-audit.json",
            "cases/ZOOKEEPER-12/sync-receipt.json",
            "evidence_archives/campaign/ZOOKEEPER-12.tar.gz",
            "evidence_archives/campaign/ZOOKEEPER-12.tar.manifest.json",
            "admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-full-review.json",
            "quality_reviews/zk12_filenotfound_full/index.json",
            "quality_reviews/zk12_filenotfound_full/ZOOKEEPER-12.json",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "data/mallory"
            for name in names:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, target)
            result_path = root / "cases/ZOOKEEPER-12/result.json"
            result = json.loads(result_path.read_text())
            review = lambda: _zk12_filenotfound_review(root, result_path, result)[0]
            self.assertEqual(review(), "observed_local_timeline")

            receipt_path = root / "quality_reviews/zk12_filenotfound_full/ZOOKEEPER-12.json"
            index_path = root / "quality_reviews/zk12_filenotfound_full/index.json"
            original = receipt_path.read_bytes()
            receipt = json.loads(original)
            receipt["trial_evidence"][0]["last_fault_identity"]["thread_id"] += 1
            receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            index = json.loads(index_path.read_text())
            index["receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            index_path.write_text(json.dumps(index))
            self.assertEqual(review(), "invalid")
            receipt_path.write_bytes(original)
            archive = root / "evidence_archives/campaign/ZOOKEEPER-12.tar.gz"
            archive.write_bytes(archive.read_bytes()[:-1])
            self.assertEqual(review(), "invalid")

    def test_solr10_sparse_role_gate_recomputes_path_and_rejects_tampering(self):
        baseline = Path(__file__).resolve().parents[2]
        script = (baseline / "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1/"
                  "terminal-role-audit/verify_sparse.py")
        source = baseline / "data/mallory/replays/SOLR-10-role-v1-full-metadata"
        index_source = baseline / "data/mallory/quality_reviews/solr10_role_v1_full/index.json"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sparse = root / "data/mallory/replays/SOLR-10-role-v1-full-metadata"
            shutil.copytree(source, sparse, symlinks=True)
            canonical = root / "data/mallory/cases/SOLR-10"
            canonical.parent.mkdir(parents=True)
            canonical.symlink_to("../replays/SOLR-10-role-v1-full-metadata")
            index = root / "data/mallory/quality_reviews/solr10_role_v1_full/index.json"
            index.parent.mkdir(parents=True)
            shutil.copy2(index_source, index)
            case_source = baseline / "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1"
            case_copy = root / "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1"
            case_copy.parent.mkdir(parents=True)
            case_copy.symlink_to(case_source, target_is_directory=True)
            audit_copy = root / "Mallory/core/audit.py"
            audit_copy.parent.mkdir(parents=True)
            audit_copy.symlink_to(baseline / "Mallory/core/audit.py")

            def check():
                return subprocess.run(
                    ["python3", str(script), "--base", str(root),
                     "--canonical", str(canonical), "--index", str(index)],
                    capture_output=True, text=True, timeout=10)

            self.assertEqual(check().returncode, 0)
            trace = sparse / "trials/r0002/events.jsonl.gz"
            original = trace.read_bytes()
            trace.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            self.assertNotEqual(check().returncode, 0)
            trace.write_bytes(original)
            index_json = json.loads(index.read_text())
            index_json["offhost_postfault_path_trials"] = 78
            index.write_text(json.dumps(index_json))
            self.assertNotEqual(check().returncode, 0)
            shutil.copy2(index_source, index)
            archive_receipt = sparse / "SOLR-10-role-v1-export-receipt.json"
            archive_receipt.write_text(archive_receipt.read_text() + " ")
            self.assertNotEqual(check().returncode, 0)

    def test_hbase07_client_review_requires_pinned_archive_and_verifier(self):
        from Mallory.report.build import _hbase07_client_event_review
        with tempfile.TemporaryDirectory() as temporary:
            baseline = Path(temporary)
            results = baseline / "data/mallory"

            def write(relative, content):
                path = baseline / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content if isinstance(content, str) else json.dumps(content))
                return path

            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            campaign_rel = "data/mallory/HBASE-07/campaigns/client-only-v1"
            legacy_rel = "data/mallory/HBASE-07/campaigns/legacy-pre-client-only"
            review_rel = "data/mallory/quality_reviews/hbase07_client_only_v1/HBASE-07.json"
            release_rel = ("Mallory/dispatch/releases/"
                           "96dd5cda2fe8e3f67130c8232fb98fa316a1eeac9a2ff3237075d7d8fe95538d")
            result = {"case_id": "HBASE-07", "status": "queue_exhausted",
                      "fault_trials_completed": 27, "strict_injected_trials": 27,
                      "strict_target_trials": 27, "exact_exception_trials": 0,
                      "duration_seconds": 100.0}
            result_path = write(f"{campaign_rel}/result.json", result)
            audit = write(f"{campaign_rel}/offline-causal-audit.json", {})
            config = write(f"{campaign_rel}/config.json", {})
            healthy = write(f"{campaign_rel}/trials/r0000/result.json", {})
            archive = write("data/mallory/evidence_archives/campaign_client_only_v1/HBASE-07.tar.gz",
                            "archive")
            collector = write("data/mallory/HBASE-07/campaigns/client-only-v1-receipt.json", {})
            legacy_result = write(f"{legacy_rel}/result.json", {"status": "budget_exhausted"})
            legacy_audit = write(f"{legacy_rel}/offline-causal-audit.json", {})
            legacy_review = write("data/mallory/HBASE-07/campaigns/legacy-pre-client-only-causal-precision-v2.json", {})
            verifier = write("Mallory/adapters/hbase/pilot/verify-HBASE-07-client-only-v1-review.py",
                             "# pinned verifier")
            manifest = write(f"{release_rel}/manifest.json", {})
            canonical = results / "cases/HBASE-07"
            canonical.parent.mkdir(parents=True)
            canonical.symlink_to(result_path.parent, target_is_directory=True)
            review = {"schema_version": 1, "case_id": "HBASE-07",
                      "classification": "observed_event_path", "status": "positive_frozen_96dd_review",
                      "campaign_result_sha256": digest(result_path),
                      "campaign_audit_sha256": digest(audit),
                      "campaign_config_sha256": digest(config),
                      "archive_sha256": digest(archive),
                      "collector_receipt_sha256": digest(collector),
                      "core_manifest_sha256": digest(manifest),
                      "core_release_id": Path(release_rel).name,
                      "versioned_campaign_path": campaign_rel,
                      "healthy_trial_result_sha256": digest(healthy),
                      "legacy_negative_review_sha256": digest(legacy_review),
                      "legacy_result_sha256": digest(legacy_result),
                      "legacy_audit_sha256": digest(legacy_audit),
                      "canonical_result_path": "data/mallory/cases/HBASE-07/result.json",
                      "canonical_audit_path": "data/mallory/cases/HBASE-07/offline-causal-audit.json",
                      "campaign_status": "queue_exhausted", "duration_seconds": 100.0,
                      "fault_trials_completed": 27,
                      "strict_injected_trials": 27, "strict_postfault_event_path_trials": 27,
                      "selected_exception_trials": 0, "qualifying_trial_ids": list(range(1, 28))}
            review_path = write(review_rel, review)
            index = {"schema_version": 1, "case_id": "HBASE-07",
                     "classification": "observed_event_path", "receipt": review_rel,
                     "receipt_sha256": digest(review_path), "verifier_sha256": digest(verifier),
                     "result_sha256": digest(result_path), "audit_sha256": digest(audit),
                     "config_sha256": digest(config), "archive_sha256": digest(archive),
                     "collector_receipt_sha256": digest(collector),
                     "core_manifest_sha256": digest(manifest),
                     "legacy_v2_review_sha256": digest(legacy_review),
                     "legacy_v2_result_sha256": digest(legacy_result),
                     "legacy_v2_audit_sha256": digest(legacy_audit),
                     "strict_postfault_event_path_trials": 27}
            write("data/mallory/quality_reviews/hbase07_client_only_v1/index.json", index)
            passed = type("Completed", (), {"returncode": 0})()
            with patch("Mallory.report.build.__file__", str(baseline / "Mallory/report/build.py")), \
                 patch("Mallory.report.build.subprocess.run", return_value=passed) as runner:
                self.assertEqual("observed_event_path", _hbase07_client_event_review(
                    results, canonical / "result.json", result)[0])
                runner.assert_called_once()
                archive.write_text("tampered")
                self.assertEqual("invalid", _hbase07_client_event_review(
                    results, canonical / "result.json", result)[0])
                runner.assert_called_once()

    def test_solr18_scope_gap_is_hash_bound_and_reverified(self):
        from Mallory.report.build import _solr18_scope_gap
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "data/mallory"
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            def write(relative, content):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content if isinstance(content, str) else json.dumps(content))
                return path
            release = "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
            manifest = write(f"{release}/manifest.json", {})
            verifier = write("Mallory/adapters/solr/releases/v34/verify_solr18_scope_gap.py",
                             "# pinned verifier")
            campaign = "data/mallory/calibration_v34_lane1/SOLR-18"
            result = write(f"{campaign}/result.json",
                           {"case_id": "SOLR-18", "status": "calibration_complete",
                            "healthy_junit_validation": {"status": "passed"}})
            audit = write(f"{campaign}/offline-causal-audit.json",
                          {"report_gate_passed": True})
            sync = write(f"{campaign}/sync-receipt.json", {})
            config = write(f"{campaign}/config.json", {})
            trace = root / campaign / "trials/r0000/events.jsonl.gz"
            trace.parent.mkdir(parents=True)
            raw = b'{"type":"TARGET_CHECK"}\n'
            with gzip.open(trace, "wb") as stream:
                stream.write(raw)
            trial = write(f"{campaign}/trials/r0000/result.json",
                          {"events_evidence": {"gzip_sha256": digest(trace),
                                               "raw_sha256": hashlib.sha256(raw).hexdigest(),
                                               "raw_bytes": len(raw)}})
            receipt = write("data/mallory/quality_reviews/solr18_v34_gap/SOLR-18.json",
                            {"schema_version": 1, "case_id": "SOLR-18",
                             "classification": "instrumentation_identity_and_causal_path_gap",
                             "full_campaign_promoted": False, "new_bug": None,
                             "root_free_time_respecting_door_to_node2_target_paths": 0,
                             "identity_gap_reason": "unregistered_receiver",
                             "named_node2_exact_check_count": 1,
                             "healthy_result_sha256": digest(result),
                             "healthy_audit_sha256": digest(audit),
                             "sync_receipt_sha256": digest(sync),
                             "config_sha256": digest(config),
                             "trial_result_sha256": digest(trial),
                             "raw_trace_gzip_sha256": digest(trace),
                             "raw_trace_sha256": hashlib.sha256(raw).hexdigest(),
                             "raw_trace_bytes": len(raw)})
            index = write("data/mallory/quality_reviews/solr18_v34_gap/index.json",
                          {"schema_version": 1, "case_id": "SOLR-18",
                           "classification": "instrumentation_identity_and_causal_path_gap",
                           "receipt_path": str(receipt.relative_to(root)),
                           "receipt_sha256": digest(receipt),
                           "verifier_path": str(verifier.relative_to(root)),
                           "verifier_sha256": digest(verifier),
                           "core_manifest_path": str(manifest.relative_to(root)),
                           "core_manifest_sha256": digest(manifest)})
            with patch("Mallory.report.build.subprocess.run",
                       return_value=subprocess.CompletedProcess([], 0)):
                self.assertEqual("instrumentation_identity_and_causal_path_gap",
                                 _solr18_scope_gap(results, "SOLR-18")[0])
            altered = json.loads(receipt.read_text())
            altered["root_free_time_respecting_door_to_node2_target_paths"] = 1
            receipt.write_text(json.dumps(altered))
            updated = json.loads(index.read_text())
            updated["receipt_sha256"] = digest(receipt)
            index.write_text(json.dumps(updated))
            self.assertEqual("invalid_instrumentation_gap",
                             _solr18_scope_gap(results, "SOLR-18")[0])
            altered["root_free_time_respecting_door_to_node2_target_paths"] = 0
            receipt.write_text(json.dumps(altered))
            updated["receipt_sha256"] = digest(receipt)
            index.write_text(json.dumps(updated))
            with patch("Mallory.report.build.subprocess.run",
                       return_value=subprocess.CompletedProcess([], 1)):
                self.assertEqual("invalid_instrumentation_gap",
                                 _solr18_scope_gap(results, "SOLR-18")[0])

    def test_solr22_bounded_gap_keeps_terminal_row_and_rejects_tamper(self):
        from Mallory.report.build import _solr22_dynamic_bounded_gap
        baseline = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            replay = "data/mallory/replays/SOLR-22-v33g2p-lane4"
            names = [
                "data/mallory/quality_reviews/solr22_v33g2p_gap/index.json",
                "data/mallory/quality_reviews/solr22_v33g2p_gap/SOLR-22.json",
                "data/mallory/audit_sidecars/SOLR-22-v33g2p-dynamic-pilot.json",
                "Mallory/adapters/solr/releases/v33/verify_solr22_dynamic_gap.py",
                "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f/manifest.json",
                *(f"{replay}/{name}" for name in
                  ("result.json", "offline-causal-audit.json", "sync-receipt.json",
                   "config.json")),
            ]
            for number in range(9):
                names.extend((f"{replay}/trials/r{number:04d}/result.json",
                              f"{replay}/trials/r{number:04d}/events.jsonl.gz"))
            for relative in names:
                dest = root / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(baseline / relative, dest)
            results = root / "data/mallory"
            receipt = json.loads((root / names[1]).read_text())
            def replay_verifier(args, **_kwargs):
                Path(args[args.index("--out") + 1]).write_text(json.dumps(receipt))
                return subprocess.CompletedProcess(args, 0)
            with patch("Mallory.report.build.subprocess.run", side_effect=replay_verifier):
                self.assertEqual("bounded_fault_model_gap_verified",
                                 _solr22_dynamic_bounded_gap(results, "SOLR-22")[0])
                trace = root / f"{replay}/trials/r0006/events.jsonl.gz"
                trace.write_bytes(trace.read_bytes() + b"tampered")
                self.assertEqual("invalid_bounded_fault_model_gap",
                                 _solr22_dynamic_bounded_gap(results, "SOLR-22")[0])

    def test_hbase37_source_fault_gap_rejects_changed_archived_trace(self):
        from Mallory.report.build import _hbase37_source_fault_gap
        baseline = Path(__file__).resolve().parents[2]
        receipt = json.loads((baseline / "data/mallory/fault_model_gaps/HBASE-37/receipt.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (
                "data/mallory/fault_model_gaps/HBASE-37/receipt.json",
                receipt["review_path"], receipt["source_review_path"],
                receipt["typed_sites_path"], receipt["prior_evidence"]["result_path"],
                receipt["prior_evidence"]["archive_path"],
            ):
                dest = root / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(baseline / relative, dest)
            results = root / "data/mallory"
            self.assertEqual("source_review_fault_model_gap",
                             _hbase37_source_fault_gap(results, "HBASE-37")[0])
            archive = root / receipt["prior_evidence"]["archive_path"]
            archive.write_bytes(archive.read_bytes() + b"tampered")
            self.assertEqual("invalid_fault_model_receipt",
                             _hbase37_source_fault_gap(results, "HBASE-37")[0])

    def test_hdfs48_fault_gap_rechecks_ten_raw_trials(self):
        from Mallory.report.build import _hdfs48_target_retention_gap
        baseline = Path(__file__).resolve().parents[2]
        receipt_name = "data/mallory/admissions/HDFS-48-v14-fault-model-no-target-retaining-pretarget-door.json"
        receipt = json.loads((baseline / receipt_name).read_text())
        review = json.loads((baseline / receipt["review_path"]).read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = [receipt_name, receipt["review_path"]]
            for section in (review["healthy_evidence"]["files"],
                            review["pilot_evidence"]["files"]):
                names.extend(record["path"] for record in section.values())
            names.append(review["pilot_evidence"]["decision"]["path"])
            for item in review["pilot_evidence"]["trial_evidence"]:
                names.extend((item["result"]["path"], item["trace_gzip"]["path"]))
            for relative in names:
                dest = root / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(baseline / relative, dest)
            results = root / "data/mallory"
            self.assertEqual("fault_model_no_target_retaining_pretarget_door",
                             _hdfs48_target_retention_gap(results, "HDFS-48")[0])
            trace = root / review["pilot_evidence"]["trial_evidence"][4]["trace_gzip"]["path"]
            trace.write_bytes(trace.read_bytes() + b"tampered")
            self.assertEqual("invalid_fault_model_receipt",
                             _hdfs48_target_retention_gap(results, "HDFS-48")[0])

    def test_zk10_packet_gap_rejects_changed_healthy_trace(self):
        from Mallory.report.build import _zk10_packet_fault_gap
        baseline = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = (
                "data/mallory/admissions/ZOOKEEPER-10-fa5f-observer-v1-fault-model-gap.json",
                "data/mallory/admissions/ZOOKEEPER-10-fa5f-observer-v1-healthy.json",
                "data/mallory/calibration_fa5f_node0/ZOOKEEPER-10-observer-v1/result.json",
                "data/mallory/calibration_fa5f_node0/ZOOKEEPER-10-observer-v1/offline-causal-audit.json",
                "data/mallory/calibration_fa5f_node0/ZOOKEEPER-10-observer-v1/trials/r0000/result.json",
                "data/mallory/calibration_fa5f_node0/ZOOKEEPER-10-observer-v1/trials/r0000/events.jsonl.gz",
                "Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-fa5f-observer-healthy.json",
                "Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-fa5f-observer-healthy.sites.json",
                "Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-fa5f-observer-source-review.json",
            )
            for relative in names:
                dest = root / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(baseline / relative, dest)
            results = root / "data/mallory"
            self.assertEqual("fault_model_packet_io_no_target_retention",
                             _zk10_packet_fault_gap(results, "ZOOKEEPER-10")[0])
            trace = root / names[5]
            trace.write_bytes(trace.read_bytes() + b"tampered")
            self.assertEqual("invalid_fault_model_receipt",
                             _zk10_packet_fault_gap(results, "ZOOKEEPER-10")[0])

    def test_zk05_epoch_gap_rechecks_each_fault_trace_and_fails_closed(self):
        from Mallory.report.build import _zk05_epoch_influence_gap
        original = Path(__file__).resolve().parents[2] / "data/mallory"
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary) / "data/mallory"
            for relative in (
                "admissions/ZOOKEEPER-05-5820-fault-model-gap-v1.json",
                "admissions/ZOOKEEPER-05-5820-fault-model-gap-v2.json",
                "admissions/ZOOKEEPER-05-5820-actor-retention-v2.json",
                "calibration_core5820/ZOOKEEPER-05/result.json",
                "calibration_core5820/ZOOKEEPER-05/offline-causal-audit.json",
                "pilot_core5820/ZOOKEEPER-05/result.json",
                "pilot_core5820/ZOOKEEPER-05/offline-causal-audit.json",
                "pilot_core5820/ZOOKEEPER-05/config.json",
            ):
                dest = results / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original / relative, dest)
            for trial_id in range(1, 7):
                relative = f"pilot_core5820/ZOOKEEPER-05/trials/r{trial_id:04d}"
                dest = results / relative
                dest.mkdir(parents=True)
                for name in ("result.json", "events.jsonl.gz"):
                    shutil.copy2(original / relative / name, dest / name)
            self.assertEqual("fault_model_epoch_influence_unproven",
                             _zk05_epoch_influence_gap(results, "ZOOKEEPER-05")[0])
            trace = (results / "pilot_core5820/ZOOKEEPER-05" /
                     "trials/r0003/events.jsonl.gz")
            trace.write_bytes(trace.read_bytes() + b"tampered")
            self.assertEqual("invalid_fault_model_receipt",
                             _zk05_epoch_influence_gap(results, "ZOOKEEPER-05")[0])

    def test_zk04_zxid_gap_is_nonterminal_and_fails_closed_on_tamper(self):
        from Mallory.report.build import _zk04_zxid_influence_gap
        baseline = Path(__file__).resolve().parents[2]
        original = baseline / "data/mallory"
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary) / "data/mallory"
            for relative in (
                "calibration_fa5f_lane2/ZOOKEEPER-04-write-reconnect-v1",
                "pilot_fa5f_lane2/ZOOKEEPER-04-readbool-v2",
            ):
                shutil.copytree(original / relative, results / relative)
            admission = results / "admissions"
            admission.mkdir(parents=True)
            for name in (
                "ZOOKEEPER-04-fa5f-write-reconnect-v1-healthy.json",
                "ZOOKEEPER-04-fa5f-write-reconnect-v1-fault-model-gap.json",
            ):
                shutil.copy2(original / "admissions" / name, admission / name)
            self.assertEqual("fault_model_zxid_influence_unproven",
                             _zk04_zxid_influence_gap(results, "ZOOKEEPER-04")[0])

            healthy_result = (results / "calibration_fa5f_lane2" /
                              "ZOOKEEPER-04-write-reconnect-v1/result.json")
            healthy_result.write_bytes(healthy_result.read_bytes() + b" ")
            self.assertEqual("invalid_fault_model_receipt",
                             _zk04_zxid_influence_gap(results, "ZOOKEEPER-04")[0])
            shutil.copy2(original / "calibration_fa5f_lane2" /
                         "ZOOKEEPER-04-write-reconnect-v1/result.json", healthy_result)

            receipt_path = (admission /
                            "ZOOKEEPER-04-fa5f-write-reconnect-v1-fault-model-gap.json")
            receipt = json.loads(receipt_path.read_text())
            source = next(iter(receipt["source_files"]))
            receipt["source_files"][source] = "0" * 64
            receipt_path.write_text(json.dumps(receipt))
            self.assertEqual("invalid_fault_model_receipt",
                             _zk04_zxid_influence_gap(results, "ZOOKEEPER-04")[0])

    def test_solr37_no_target_path_receipt_fails_closed(self):
        from Mallory.report.build import _fault_model_no_target_path
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "data/mallory"
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            def write(relative, content):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content if isinstance(content, str) else json.dumps(content))
                return path
            healthy = write("data/mallory/calibration/SOLR-37/result.json",
                            {"case_id": "SOLR-37", "status": "calibration_complete"})
            healthy_audit = write("data/mallory/calibration/SOLR-37/offline-causal-audit.json",
                                  {"report_gate_passed": True})
            pilot = write("data/mallory/pilot/SOLR-37/result.json",
                          {"case_id": "SOLR-37", "status": "budget_exhausted",
                           "fault_trials_completed": 1, "strict_injected_trials": 1,
                           "strict_target_trials": 1, "exact_exception_trials": 0})
            pilot_audit = write("data/mallory/pilot/SOLR-37/offline-causal-audit.json",
                                {"report_gate_passed": True})
            sync = write("data/mallory/pilot/SOLR-37/sync-receipt.json", {})
            raw = b'{"type":"FAULT_APPLIED"}\n'
            trace = pilot.parent / "trials/r0001/events.jsonl.gz"
            trace.parent.mkdir(parents=True)
            with gzip.open(trace, "wb") as stream:
                stream.write(raw)
            trial = write("data/mallory/pilot/SOLR-37/trials/r0001/result.json",
                          {"events_evidence": {"raw_sha256": hashlib.sha256(raw).hexdigest(),
                                               "raw_bytes": len(raw),
                                               "gzip_sha256": digest(trace)}})
            sidecar = write("data/mallory/audit_sidecars/SOLR-37.json",
                            {"case_id": "SOLR-37", "campaign_result_sha256": digest(pilot),
                             "offline_causal_audit_sha256": digest(pilot_audit),
                             "fault_trials_completed": 1,
                             "trials_with_time_respecting_observed_path": 0,
                             "trials": [{"trial_id": 1, "trial_result_sha256": digest(trial),
                                         "trace_gzip_sha256": digest(trace),
                                         "trace_raw_sha256": hashlib.sha256(raw).hexdigest(),
                                         "trace_raw_bytes": len(raw),
                                         "applied_faults": [{"time_respecting_observed_path": None}]}]})
            source = write("Mallory/adapters/solr/source-review.md", "source SHA abc123")
            files = {"healthy_result": healthy, "healthy_audit": healthy_audit,
                     "pilot_result": pilot, "pilot_audit": pilot_audit,
                     "pilot_sync_receipt": sync, "postfault_path_sidecar": sidecar,
                     "source_request_order_review": source}
            artifacts = {key: {"path": str(path.relative_to(root)),
                               "bytes": path.stat().st_size, "sha256": digest(path)}
                         for key, path in files.items()}
            receipt = write("data/mallory/quality_reviews/solr37_v29p_gap/SOLR-37.json",
                            {"schema_version": 1, "case_id": "SOLR-37",
                             "classification": "fault_model_no_target_path",
                             "full_campaign_promoted": False, "healthy_junit_pass": True,
                             "healthy_named_exact_target": True,
                             "time_respecting_observed_postfault_paths": 0,
                             "pilot_fault_trials": 1, "pilot_strict_applied": 1,
                             "pilot_target_retained": 1, "exact_target_exception_trials": 0,
                             "source_file_sha256_as_attested_in_review": "abc123",
                             "artifacts": artifacts})
            self.assertEqual("fault_model_no_target_path",
                             _fault_model_no_target_path(results, "SOLR-37")[0])
            altered = json.loads(sidecar.read_text())
            altered["trials_with_time_respecting_observed_path"] = 1
            sidecar.write_text(json.dumps(altered))
            update = json.loads(receipt.read_text())
            update["artifacts"]["postfault_path_sidecar"] = {
                "path": str(sidecar.relative_to(root)), "bytes": sidecar.stat().st_size,
                "sha256": digest(sidecar)}
            receipt.write_text(json.dumps(update))
            self.assertEqual("invalid_fault_model_receipt",
                             _fault_model_no_target_path(results, "SOLR-37")[0])

    def test_hdfs11_event_path_receipt_fails_closed_on_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            baseline = Path(__file__).resolve().parents[2]
            release = (baseline / "Mallory/dispatch/releases/"
                       "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f")
            results = Path(temporary) / "data/mallory"
            case = results / "cases/HDFS-11"
            case.mkdir(parents=True)
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            result = {"case_id": "HDFS-11", "strict_injected_trials": 1,
                      "strict_target_trials": 1}
            result_path = case / "result.json"
            result_path.write_text(json.dumps(result))
            audit_path = case / "offline-causal-audit.json"
            audit_path.write_text("{}")
            config_path = case / "config.json"
            config_path.write_text("{}")
            archive_root = results / "evidence_archives/campaign"
            archive_root.mkdir(parents=True)
            archive = archive_root / "HDFS-11.tar.gz"
            archive.write_bytes(b"archive")
            manifest = archive_root / "HDFS-11.tar.manifest.json"
            manifest.write_text("{}")
            review_root = results / "quality_reviews/hdfs11_v27_faulted_path"
            review_root.mkdir(parents=True)
            receipt_path = review_root / "HDFS-11.json"
            receipt = {"classification": "observed_event_path",
                       "graph_source_sha256": digest(release / "Mallory/core/graph.py"),
                       "campaign_result_sha256": digest(result_path),
                       "offline_audit_sha256": digest(audit_path),
                       "config_sha256": digest(config_path),
                       "archive_sha256": digest(archive),
                       "archive_manifest_sha256": digest(manifest),
                       "strict_injected_trials": 1, "strict_target_trials": 1,
                       "qualifying_trial_count": 1}
            receipt_path.write_text(json.dumps(receipt))
            index = {"schema_version": 1, "case_id": "HDFS-11",
                     "classification": "observed_event_path",
                     "receipt_sha256": digest(receipt_path),
                     "verifier_sha256": digest(baseline / "Mallory/ops/audit_hdfs11_v27_full.py"),
                     "core_manifest_sha256": digest(release / "manifest.json"),
                     "qualifying_trial_count": 1}
            (review_root / "index.json").write_text(json.dumps(index))
            with patch("Mallory.report.build.subprocess.run",
                       return_value=subprocess.CompletedProcess([], 0)):
                self.assertEqual(_hdfs11_faulted_event_review(
                    results, result_path, result)[0], "observed_event_path")
            receipt["qualifying_trial_count"] = 0
            receipt_path.write_text(json.dumps(receipt))
            self.assertEqual(_hdfs11_faulted_event_review(
                results, result_path, result)[0], "invalid")
            receipt["qualifying_trial_count"] = 1
            receipt_path.write_text(json.dumps(receipt))
            index["receipt_sha256"] = digest(receipt_path)
            (review_root / "index.json").write_text(json.dumps(index))
            with patch("Mallory.report.build.subprocess.run",
                       return_value=subprocess.CompletedProcess([], 1)):
                self.assertEqual(_hdfs11_faulted_event_review(
                    results, result_path, result)[0], "invalid")

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
