"""An inactive bounded checkpoint can be imported only from frozen evidence."""

from __future__ import annotations

import fcntl
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Mallory.native_graphchecker_campaign import campaign as core
from Mallory.native_graphchecker_campaign import test_campaign as campaign_tests


def sha(path: Path) -> str:
    return core._sha(path)


class BoundedPrefixImportTest(unittest.TestCase):
    def fixture(self, root: Path, *, active: bool = False,
                anchored: bool = False, strict_lost: bool = False,
                lock_claim: bool = True) -> tuple[Path, Path, dict, dict]:
        source_config, executed, source = campaign_tests.TerminalSuccessorImportTest(
            "runTest")._fixture(root)
        if anchored:
            address = "observer#epoch0|BlockTokenSecretManager#u1"
            keys = {}
            for item in source["trials"]:
                result_file = executed / item["result"]
                result = core._load(result_file)
                result["anchor_address"] = address
                core._atomic(result_file, result)
                item["anchor_address"] = address
                keys[core._plan_key(result["faults"])] = core._plan_key(
                    result["faults"], address)
            for item in source["queue"]:
                old_key = item["key"]
                item["anchor_address"] = address
                item["key"] = core._plan_key(item["faults"], address)
                keys[old_key] = item["key"]
            source["seen_plan_keys"] = sorted(keys.values())
        frozen = root / "frozen-prefix"
        frozen.mkdir()
        config_path = frozen / "config.json"
        original_config = core._load(source_config)
        original_config["runner"]["local_work_root"] = str(root / "old-work")
        original_config["runner"]["local_artifact_root"] = str(root / "old-raw")
        core._atomic(source_config, original_config)
        config_path.write_bytes(source_config.read_bytes())
        source["status"] = "bounded_checkpoint_stop"
        source["terminal"] = False
        source["scheduler_version"] = 15
        source["next_trial_index"] = 3
        source["elapsed_seconds"] = 10.0
        source["active"] = ({"name": "r0003", "faults": []} if active else None)
        source["healthy"] = {"name": "r0000", "status": "healthy_seed",
                             "result": "trials/r0000/result.json"}
        source["config_sha256"] = sha(config_path)
        (executed / ".campaign.lock").touch()
        evidence = {}
        for index in range(3):
            name = f"r{index:04d}"
            trial = frozen / "trials" / name
            (trial / "iteration-native").mkdir(parents=True)
            if index:
                result = core._load(executed / "trials" / name / "result.json")
            else:
                result = {"case_id": source["case_id"], "status": "healthy_seed",
                          "faults": [], "runner_mode": "region_state"}
            if index:
                result["strict_injection"] = index == 1 or strict_lost
                result["native_target_retained"] = index == 1
            events = trial / "iteration-native/fault-events.jsonl"
            if index == 2:
                events.write_bytes((executed / "trials" / name /
                                    "iteration-native/fault-events.jsonl").read_bytes())
            else:
                events.write_text("", encoding="utf-8")
            result["fault_events_sha256"] = sha(events)
            local = trial / "local-artifacts.json"
            core._atomic(local, {"campaign_root": str(executed), "trial": name})
            result["local_artifacts_manifest_sha256"] = sha(local)
            summary = trial / "native-summary.json"
            core._atomic(summary, {"trial": name})
            result["native_session_sha256"] = sha(summary)
            if index != 2:  # An unmatched trial need not emit peer ranking.
                peer = trial / "peer-ranking-receipt.json"
                core._atomic(peer, {"trial": name})
                result["peer_ranking_receipt_sha256"] = sha(peer)
            core._atomic(trial / "result.json", result)
            archive = root / f"raw-{name}.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(trial / "result.json", arcname=f"{name}/result.json")
            receipt = frozen / f"raw-archive-receipt-{name}.json"
            core._atomic(receipt, {"trial_index": index,
                                   "result_sha256": sha(trial / "result.json"),
                                   "archive_sha256": sha(archive),
                                   "verified_against_source": True})
            evidence[index] = {"trial_index": index,
                               "absolute_tar_path": str(archive),
                               "archive_sha256": sha(archive),
                               "absolute_receipt_path": str(receipt),
                               "receipt_sha256": sha(receipt),
                               "result_sha256": sha(trial / "result.json")}
        core._atomic(frozen / "checkpoint.json", source)
        core._atomic(executed / "checkpoint.json", source)
        core._atomic(frozen / "summary.json", {
            key: value for key, value in source.items()
            if key not in ("queue", "seen_plan_keys", "active")})
        files = {}
        for path in sorted(frozen.rglob("*")):
            if path.is_file() and path.name != "bounded-snapshot-manifest.json":
                files[path.relative_to(frozen).as_posix()] = {
                    "sha256": sha(path), "size_bytes": path.stat().st_size}
        checkpoint_sha = sha(frozen / "checkpoint.json")
        manifest = {"schema_version": 1, "case_id": source["case_id"],
                    "source_output_root": str(executed),
                    "source_lock_verified": lock_claim,
                    "source_checkpoint_before_sha256": checkpoint_sha,
                    "source_checkpoint_after_sha256": checkpoint_sha,
                    "config_sha256": sha(config_path),
                    "checkpoint_sha256": checkpoint_sha,
                    "summary_sha256": sha(frozen / "summary.json"),
                    "completed_fault_trials": 2, "files": files,
                    "raw_archives": list(evidence.values())}
        manifest_path = frozen / "bounded-snapshot-manifest.json"
        core._atomic(manifest_path, manifest)
        successor = core._load(config_path)
        successor["budget"] = {**successor["budget"], "fault_trials": 256,
                               "max_faults_per_trial": 256}
        return config_path, frozen, source, successor

    def test_imports_stopped_prefix_without_repeating_tested_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_config, frozen, source, successor = self.fixture(root)
            pins = core.build_predecessor_pins(
                source_config, frozen, successor_fault_trials=256,
                successor_max_faults_per_trial=256,
                bounded_snapshot_manifest=frozen / "bounded-snapshot-manifest.json")
            successor["predecessor_campaign"] = pins
            state = {**source, "budget": successor["budget"]}
            receipt, queue, _, seen = core._predecessor_snapshot(
                successor, root / "successor", state)
            tested = {core._plan_key(core._load(frozen / item["result"])["faults"])
                      for item in source["trials"]}
            self.assertEqual("bounded_prefix_snapshot_v1", receipt["source_kind"])
            self.assertEqual(2, receipt["tested_plan_count"])
            self.assertTrue(tested.issubset(seen))
            retries = [item for item in queue if item["key"] in tested]
            self.assertEqual(1, len(retries))
            self.assertEqual(1, retries[0]["attempt"])
            self.assertEqual(1, receipt["imported_unmatched_retry_count"])
            self.assertEqual(256, receipt["successor_fault_depth_limit"])

    def test_anchored_unmatched_retry_keeps_exact_key_and_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_config, frozen, source, successor = self.fixture(
                root, anchored=True)
            pins = core.build_predecessor_pins(
                source_config, frozen, successor_fault_trials=256,
                successor_max_faults_per_trial=256,
                bounded_snapshot_manifest=frozen / "bounded-snapshot-manifest.json")
            successor["predecessor_campaign"] = pins
            state = {**source, "budget": successor["budget"]}
            receipt, queue, _, _ = core._predecessor_snapshot(
                successor, root / "successor", state)
            old_result = core._load(frozen / "trials/r0002/result.json")
            key = core._plan_key(old_result["faults"],
                                 old_result["anchor_address"])
            retry = [item for item in queue if item["key"] == key]
            self.assertEqual(1, len(retry))
            self.assertEqual(1, retry[0]["attempt"])
            self.assertEqual(old_result["anchor_address"],
                             retry[0]["anchor_address"])
            self.assertEqual(1, receipt["imported_unmatched_retry_count"])
            self.assertNotIn(core._plan_key(core._load(
                frozen / "trials/r0001/result.json")["faults"],
                old_result["anchor_address"]),
                {item["key"] for item in queue})

    def test_strict_applied_target_lost_retry_is_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_config, frozen, source, successor = self.fixture(
                root, strict_lost=True)
            pins = core.build_predecessor_pins(
                source_config, frozen, successor_fault_trials=256,
                successor_max_faults_per_trial=256,
                bounded_snapshot_manifest=frozen / "bounded-snapshot-manifest.json")
            successor["predecessor_campaign"] = pins
            state = {**source, "budget": successor["budget"]}
            receipt, queue, _, _ = core._predecessor_snapshot(
                successor, root / "successor", state)
            lost = core._load(frozen / "trials/r0002/result.json")
            self.assertNotIn(core._plan_key(lost["faults"]),
                             {item["key"] for item in queue})
            self.assertEqual(0, receipt["imported_unmatched_retry_count"])
            self.assertEqual(1, receipt["discarded_tested_retry_count"])

    def test_import_only_seals_prefix_without_running_healthy_or_fault(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_config, frozen, source, successor = self.fixture(root)
            successor["predecessor_campaign"] = core.build_predecessor_pins(
                source_config, frozen, successor_fault_trials=256,
                successor_max_faults_per_trial=256,
                bounded_snapshot_manifest=frozen / "bounded-snapshot-manifest.json")
            successor_file = root / "successor-config.json"
            core._atomic(successor_file, successor)
            initial = {**source, "case_id": successor["case_id"],
                       "config_sha256": sha(successor_file),
                       "budget": successor["budget"], "healthy": None,
                       "trials": [], "completed_fault_trials": 0,
                       "next_trial_index": 1, "queue": [],
                       "seen_plan_keys": [], "active": None,
                       "status": "running", "terminal": False,
                       "elapsed_seconds": 0.0}
            with (mock.patch.object(core, "_validate_config"),
                  mock.patch.object(core, "_validate_local_work_root"),
                  mock.patch.object(core, "_validate_local_artifact_root"),
                  mock.patch.object(core, "_admit") as admit,
                  mock.patch.object(core, "_new_state", return_value=initial),
                  mock.patch.object(core, "_resume_active") as run_trial):
                state = core.run_campaign(successor_file, root / "successor",
                                          import_only=True)
            admit.assert_called_once()
            self.assertTrue(admit.call_args.kwargs["no_child"])
            run_trial.assert_not_called()
            self.assertEqual(0, state["completed_fault_trials"])
            self.assertEqual(2, state["imported_completed_fault_trials"])
            self.assertEqual(10.0, state["imported_elapsed_seconds"])
            self.assertEqual(3, state["next_trial_index"])
            self.assertIsNone(state["healthy"])
            self.assertFalse((root / "successor/trials").exists())
            self.assertEqual(1, state["predecessor_import"][
                "imported_unmatched_retry_count"])

    def test_explicit_case_transition_allows_only_isolated_local_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_config, frozen, source, successor = self.fixture(root)
            new_case = source["case_id"] + "-V17"
            pins = core.build_predecessor_pins(
                source_config, frozen, successor_fault_trials=256,
                successor_max_faults_per_trial=256,
                bounded_snapshot_manifest=frozen / "bounded-snapshot-manifest.json",
                successor_case_id=new_case)
            successor["case_id"] = new_case
            successor["runner"]["local_work_root"] = str(root / "new-work")
            successor["runner"]["local_artifact_root"] = str(root / "new-raw")
            successor["predecessor_campaign"] = pins
            state = {**source, "budget": successor["budget"]}
            receipt, _, _, _ = core._predecessor_snapshot(
                successor, root / "successor", state)
            self.assertEqual(source["case_id"], receipt["source_case_id"])
            self.assertEqual(new_case, receipt["successor_case_id"])
            changed = core._load(source_config)["runner"]
            successor["runner"]["main_class"] = "OtherMain"
            with self.assertRaisesRegex(ValueError, "runner differs beyond"):
                core._predecessor_snapshot(successor, root / "successor", state)
            successor["runner"] = changed
            successor["case_id"] = "unreviewed-case"
            with self.assertRaisesRegex(ValueError, "completed campaign"):
                core._predecessor_snapshot(successor, root / "successor", state)

    def test_changed_result_or_missing_raw_archive_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_config, frozen, source, successor = self.fixture(root)
            pins = core.build_predecessor_pins(
                source_config, frozen, successor_fault_trials=256,
                successor_max_faults_per_trial=256,
                bounded_snapshot_manifest=frozen / "bounded-snapshot-manifest.json")
            successor["predecessor_campaign"] = pins
            state = {**source, "budget": successor["budget"]}
            result = frozen / "trials/r0001/result.json"
            result.write_bytes(result.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "copied file changed"):
                core._predecessor_snapshot(successor, root / "successor", state)
            result.write_bytes(result.read_bytes()[:-1])
            (root / "raw-r0001.tar.gz").unlink()
            with self.assertRaisesRegex(ValueError, "raw archive is missing"):
                core._predecessor_snapshot(successor, root / "successor", state)

    def test_active_checkpoint_and_missing_lock_claim_are_rejected(self) -> None:
        for kwargs, message in (({"active": True}, "stopped, frozen prefix"),
                                ({"lock_claim": False}, "stopped, frozen prefix")):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source_config, frozen, _, _ = self.fixture(root, **kwargs)
                with self.assertRaisesRegex(ValueError, message):
                    core.build_predecessor_pins(
                        source_config, frozen, successor_fault_trials=256,
                        successor_max_faults_per_trial=256,
                        bounded_snapshot_manifest=frozen /
                        "bounded-snapshot-manifest.json")

    def test_live_source_race_or_advance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_config, frozen, source, successor = self.fixture(root)
            pins = core.build_predecessor_pins(
                source_config, frozen, successor_fault_trials=256,
                successor_max_faults_per_trial=256,
                bounded_snapshot_manifest=frozen / "bounded-snapshot-manifest.json")
            successor["predecessor_campaign"] = pins
            state = {**source, "budget": successor["budget"]}
            executed = Path(core._load(frozen /
                "bounded-snapshot-manifest.json")["source_output_root"])
            with (executed / ".campaign.lock").open("rb") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, "source is still active"):
                    core._predecessor_snapshot(successor, root / "successor", state)
            (executed / "checkpoint.json").write_bytes(b"advanced checkpoint")
            with self.assertRaisesRegex(ValueError, "live checkpoint advanced"):
                core._predecessor_snapshot(successor, root / "successor", state)


if __name__ == "__main__":
    unittest.main()
