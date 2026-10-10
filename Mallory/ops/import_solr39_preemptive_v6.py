#!/usr/bin/env python3
"""Import the sealed SOLR-39 fault run after deterministic offline reclassification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


BASE = Path(__file__).resolve().parents[2]
DATA = BASE / "data/mallory"
PACKAGE = BASE / "Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v6"
V5 = BASE / "Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v5"
RAW = DATA / "pilot_observations/SOLR-39-preemptive-fault-node1-v5"
NAME = "SOLR-39-preemptive-fault-node1-v5"
ARCHIVE = DATA / "evidence_archives" / f"{NAME}.tar.gz"
MANIFEST = DATA / "evidence_archives" / f"{NAME}.members.json"
SEAL = DATA / "evidence_archives" / f"{NAME}.receipt.json"
DEST = DATA / "cases/SOLR-39"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    if DEST.exists():
        raise RuntimeError("SOLR-39 canonical destination already exists")
    check = subprocess.run(
        ["python3", "-B", str(PACKAGE / "reconcile.py"), "--preflight-only"],
        cwd=BASE, capture_output=True, text=True, timeout=90, check=False)
    if check.returncode:
        raise RuntimeError(f"sealed v6 replay failed: {check.stderr[-500:]}")
    observed = json.loads(check.stdout)
    checkpoint = read(PACKAGE / "continuation-checkpoint.json")
    proposal = read(PACKAGE / "canonical-import-proposal.json")
    terminal = read(PACKAGE / "terminal-replay-receipt.json")
    stage = read(PACKAGE / "stage-request.json")
    seal = read(SEAL)
    if not (
        observed["status"] == checkpoint["status"] == terminal["status"]
        == "queue_exhausted_after_strict_reclassification"
        and observed["go"] is False and observed["jvm_run"] is False
        and observed["queue_size"] == len(checkpoint["queue"]) == 0
        and observed["valid_trials"] == checkpoint["valid_trials"] == [3]
        and checkpoint["invalid_trials"] == [1, 2]
        and checkpoint["completed_fault_trials"] == [1, 2, 3]
        and checkpoint["exact_target_exception_candidates"] == []
        and checkpoint["cumulative_elapsed_seconds"] == 142.739
        and checkpoint["remaining_budget"]["trials"] == 9
        and terminal["new_bug_confirmed"] is False
        and terminal["r0003_exact_prior_reference_witness"] == {
            "aliases_ref": 81, "cache_write_seq": 32094, "epoch": 0,
            "fault_applied_seq": 32106, "manager_object": "o10", "node": "node2",
            "observed_edge_kinds": ["program_return", "state_exact_ref"],
            "owner_ref": 1, "target_check_seq": 32895,
            "target_read_seq": 32892, "zk_version": 15}
        and proposal["status"] == "proposal_only_not_imported"
        and proposal["checkpoint_sha256"] == digest(PACKAGE / "continuation-checkpoint.json")
        and proposal["terminal_receipt_sha256"] == digest(PACKAGE / "terminal-replay-receipt.json")
        and stage["go"] is False and stage["jvm_run"] is False
        and stage["queue_size"] == 0
        and stage["canonical_import_proposal_sha256"] == digest(PACKAGE / "canonical-import-proposal.json")
        and seal["archive_sha256"] == digest(ARCHIVE)
        and seal["manifest_sha256"] == digest(MANIFEST)
        and seal["fault_trials_completed"] == 3
        and seal["status"] == "queue_exhausted"
        and seal["raw_exact_target_throw_count"] == 0
    ):
        raise RuntimeError("SOLR-39 terminal replay, source seal, or proposal differs")
    trials = checkpoint["trials"]
    if ([(item["trial_id"], item["valid"], item["qualification"])
         for item in trials] != [
             (1, False, "postfault_bound_actor_prior_reference_target_missing"),
             (2, False, "postfault_bound_actor_prior_reference_target_missing"),
             (3, True, "strict_prior_reference_target_retained")]
            or any(item["exact_target_throw_candidates"] for item in trials)
            or trials[0]["workload_outcome"]["junit_status"] != "failed"
            or trials[1]["workload_outcome"]["junit_status"] != "passed"
            or trials[2]["workload_outcome"]["junit_status"] != "passed"):
        raise RuntimeError("trial quality or independent JUnit outcomes changed")
    result = {**proposal["result_fields"], "new_bug": False,
              "target_node_named": True,
              "source_review_status": "no_exact_target_throw_observed",
              "provenance": "sealed_v5_faults_with_v6_offline_reclassification",
              "v5_archive_sha256": digest(ARCHIVE),
              "v6_terminal_replay_receipt_sha256": digest(PACKAGE / "terminal-replay-receipt.json")}
    if (result["case_id"] != "SOLR-39" or result["status"] != "queue_exhausted"
            or result["fault_trials_completed"] != 3 or result["strict_injected_trials"] != 3
            or result["strict_target_trials"] != 1 or result["exact_exception_trials"] != 0
            or result["cluster_test"] !=
            "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation"):
        raise RuntimeError("canonical result proposal changed")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".solr39-import-", dir=DEST.parent) as tmp:
        root = Path(tmp)
        write(root / "result.json", result)
        shutil.copyfile(V5 / "config.json", root / "config.json")
        shutil.copyfile(PACKAGE / "continuation-checkpoint.json", root / "checkpoint.json")
        shutil.copyfile(PACKAGE / "terminal-replay-receipt.json", root / "case-local-causal-audit.json")
        shutil.copyfile(PACKAGE / "canonical-import-proposal.json", root / "import-proposal.json")
        shutil.copyfile(RAW / "campaign-summary.json", root / "v5-campaign-summary.json")
        for number in (1, 2, 3):
            trial = root / "trials" / f"r{number:04d}"
            trial.mkdir(parents=True)
            shutil.copyfile(RAW / "trials" / f"r{number:04d}" / "result.json",
                            trial / "result.json")
            write(trial / "v6-reclassification.json", trials[number - 1])
        write(root / "fault-depth-review.json", {
            "schema_version": 1, "case_id": "SOLR-39",
            "campaign_result_sha256": digest(root / "result.json"),
            "archive_sha256": digest(ARCHIVE), "depth_distribution": {"1": 3},
            "trial_plan_sha256": {f"r{n:04d}": digest(root / "trials" / f"r{n:04d}" / "result.json")
                                  for n in (1, 2, 3)}})
        write(root / "canonical-import-receipt.json", {
            "schema_version": 1, "case_id": "SOLR-39", "status": "queue_exhausted",
            "completion_criterion": "finite_strict_queue_exhausted_after_sealed_reclassification",
            "result_sha256": digest(root / "result.json"),
            "config_sha256": digest(root / "config.json"),
            "checkpoint_sha256": digest(root / "checkpoint.json"),
            "causal_audit_sha256": digest(root / "case-local-causal-audit.json"),
            "depth_review_sha256": digest(root / "fault-depth-review.json"),
            "proposal_sha256": digest(root / "import-proposal.json"),
            "v5_archive_sha256": digest(ARCHIVE),
            "v5_manifest_sha256": digest(MANIFEST),
            "v5_seal_sha256": digest(SEAL),
            "v6_reconciler_sha256": digest(PACKAGE / "reconcile.py"),
            "v6_auditor_sha256": digest(PACKAGE / "audit_trial.py"),
            "v6_stage_sha256": digest(PACKAGE / "stage-request.json"),
            "valid_trials": [3], "invalid_trials": [1, 2],
            "junit_failed_trials": [1], "exact_target_exception_trials": [],
            "new_bug": False})
        root.rename(DEST)
    print(json.dumps({"case_id": "SOLR-39", "fault_trials_completed": 3,
                      "canonical_result_sha256": digest(DEST / "result.json")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
