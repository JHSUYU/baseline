#!/usr/bin/env python3
"""Read-only sealed v5 re-audit and checkpoint-safe SOLR-39 continuation staging."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tarfile

from audit_trial import audit, events_from

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
CASE = HERE.parent
V5 = CASE / "preemptive-fault-v5"
RAW = ROOT / "data/mallory/pilot_observations/SOLR-39-preemptive-fault-node1-v5"
EVIDENCE = ROOT / "data/mallory/evidence_archives"
ARCHIVE = EVIDENCE / "SOLR-39-preemptive-fault-node1-v5.tar.gz"
MEMBERS = EVIDENCE / "SOLR-39-preemptive-fault-node1-v5.members.json"
RECEIPT = EVIDENCE / "SOLR-39-preemptive-fault-node1-v5.receipt.json"
POINTS = V5 / "selected-doors.json"
CONFIG = V5 / "config.json"
EXPECTED = {
    "archive_sha256": "41ff0b4069d0155905ee82d582114b0b0cf1e938d0d9ff54cf23e5457a124c86",
    "members_sha256": "07e85c2f756abc0d8a249e1472a50ae439ad12834a99330caf98bd6367b56cfa",
    "receipt_go_sha256": "687c3a7669f8cdae0a03e22433724137705d476272d9d74aee6067804cd6a613",
    "v5_config_sha256": "2c51305290ac442288583142a247eec3600c2eeeb37c135ebbad69d0c036cc17",
    "v5_selected_sha256": "9b0396eafaed2838267b2686dea703b261f3b5074951299dded9a703b7445d0c",
    "healthy_archive_sha256": "ac92251f6c58567f17019a4f69a0a87068a824a627e4fd9e7e01f806f2d10566",
    "v4_offline_proof_sha256": "804d1224f0466b5b3c98eb658a9554e12685fbf6e2083977b0f74708275ea4c2",
    "v4_overlay_code_sha256": "4034229963de149ba903cb0f9e4ee87141967529bdc3dd9c4aeee14219e81eec",
    "v2_reference_code_sha256": "8d40095d2878535c2b9ddd6b3ada0cb33ba60bd4aefe3af4705e1a27b0129bfc",
    "graph_code_sha256": "b3375c52d8f69f52420b3e374cfc9c6a6aeec0d9f7182df63284d52b0140477d",
    "zk_reader_source_sha256": "83e14eadfcc4896ff05f9ac77706fdb683e0c181caeee21802f8861f68ac373d",
    "target_source_sha256": "6ed4337435f68d00ba85d7b05eeb324cea9a14298c34cabd137756d682f24590",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def require(value: bool, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def signature(plan: list[dict]) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def selected_points() -> list[dict]:
    return load(POINTS)["selected_healthy_points"]


def expected_single_plan(point: dict) -> list[dict]:
    p = point["point"]
    return [{"fault_id": f"solr39_v5_{p['node']}_{p['epoch']}_{p['door_ordinal']}",
             "point": p, "fault_type": "EXCEPTION",
             "exception_class": point["exception_class"]}]


def verify_sealed() -> dict:
    """Verify archive, manifest, local raw members, GO and v5 input pins."""
    receipt, members = load(RECEIPT), load(MEMBERS)["files"]
    require(sha(ARCHIVE) == receipt["archive_sha256"] == EXPECTED["archive_sha256"],
            "sealed v5 archive SHA mismatch")
    require(sha(MEMBERS) == receipt["manifest_sha256"] == EXPECTED["members_sha256"],
            "sealed v5 member manifest SHA mismatch")
    require(receipt["member_count"] == len(members) == 323 and
            receipt["fault_trials_completed"] == 3 and receipt["status"] == "queue_exhausted" and
            receipt["raw_exact_target_throw_count"] == 0 and
            receipt["admission_go_sha256"] == EXPECTED["receipt_go_sha256"],
            "v5 terminal receipt changed")
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        names = set()
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name.split("/", 1)[1]
            names.add(name)
            stream = archive.extractfile(member)
            require(stream is not None and
                    hashlib.sha256(stream.read()).hexdigest() == members.get(name),
                    f"sealed archive member digest changed: {name}")
    require(names == set(members), "archive member list differs from seal")
    # Local scratch/core.properties can change when tests run.  Only the
    # archived byte stream and the local files actually consumed by this
    # offline auditor must match the seal.
    consumed = {"admission-go.json", "checkpoint.json"}
    for trial_id in (1, 2, 3):
        prefix = f"trials/r{trial_id:04d}/"
        consumed.update(prefix + name for name in
                        ("result.json", "events.jsonl.gz", "junit.log"))
        require(not (RAW / prefix / "events.jsonl").exists(),
                "unsealed plain trace would shadow sealed gzip trace")
    for name in consumed:
        require((RAW / name).is_file() and sha(RAW / name) == members.get(name),
                f"consumed local v5 evidence differs from seal: {name}")
    require(sha(RAW / "admission-go.json") == EXPECTED["receipt_go_sha256"] and
            sha(CONFIG) == EXPECTED["v5_config_sha256"] and
            sha(POINTS) == EXPECTED["v5_selected_sha256"] and
            sha(CASE / "preemptive-graph-gap-v4/offline-proof.json") ==
            EXPECTED["v4_offline_proof_sha256"] and
            sha(ROOT / "data/mallory/evidence_archives/SOLR-39-preemptive-healthy-node1-v3.tar.gz") ==
            EXPECTED["healthy_archive_sha256"],
            "v5 input or healthy/overlay lineage SHA mismatch")
    extra_pins = {
        CASE / "preemptive-graph-gap-v4/audit_graph_gap.py": "v4_overlay_code_sha256",
        CASE / "exact-alias-reference-offline-v2/audit_identity.py": "v2_reference_code_sha256",
        ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4/Mallory/core/graph.py": "graph_code_sha256",
        Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"): "zk_reader_source_sha256",
        Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java"): "target_source_sha256",
    }
    for path, key in extra_pins.items():
        require(sha(path) == EXPECTED[key], f"pinned graph or source changed: {key}")
    checkpoint = load(RAW / "checkpoint.json")
    go = load(RAW / "admission-go.json")
    require(checkpoint["completed_fault_trials"] == [1, 2, 3] and
            checkpoint["next_trial"] == 4 and checkpoint["running"] is None and
            checkpoint["status"] == "queue_exhausted" and go["go"] is True and
            go["attempt_id"] == "solr39-v5-8b913e273f6f4067bcf4aa3da46a1558" and
            go["stage_commit"] == "16c4bc13974dce9bef610f5ef7a337dc0a6b8ad7",
            "v5 checkpoint or admission identity changed")
    require(load(CONFIG)["budget"] == {"trials": 12, "seconds": 2400,
                                          "max_faults_per_trial": 3,
                                          "trial_timeout_seconds": 480},
            "cumulative campaign budget changed")
    return {"archive_sha256": sha(ARCHIVE), "member_manifest_sha256": sha(MEMBERS),
            "member_count": len(members), "v5_admission_go_sha256": sha(RAW / "admission-go.json"),
            "v5_checkpoint_sha256": sha(RAW / "checkpoint.json"),
            "healthy_archive_sha256": EXPECTED["healthy_archive_sha256"],
            "v4_offline_proof_sha256": EXPECTED["v4_offline_proof_sha256"],
            **{key: EXPECTED[key] for key in extra_pins.values()}}


def rebuild_state(audits: list[dict], results: list[dict], rows_by_trial: list[list[dict]]) -> dict:
    """Reclassify v5 exactly once and mutate only later observed selected doors."""
    config = load(CONFIG)
    points = selected_points()
    healthy = load(ROOT / "data/mallory/pilot_observations/SOLR-39-preemptive-healthy-node1-v3/trials/r0000/result.json")
    baseline = healthy["feedback"]
    coverage = set(baseline.get("coverage_ids", []))
    closure = set(baseline.get("closure_coverage_ids", []))
    seen = set()
    queue, trials = [], []
    edge_keys = set()
    elapsed = 0.0
    for index, (post, result, rows) in enumerate(zip(audits, results, rows_by_trial, strict=True)):
        trial_id = index + 1
        expected = expected_single_plan(points[index])
        require(result["trial_id"] == trial_id and result["plan"] == expected and
                result["dispatch_attempt_id"] ==
                "solr39-v5-8b913e273f6f4067bcf4aa3da46a1558",
                f"r{trial_id:04d} plan or attempt changed")
        sig = signature(expected)
        require(sig not in seen, "duplicate v5 plan")
        seen.add(sig)
        elapsed += result["elapsed_seconds"]
        novelty = {"coverage": 0, "closure_coverage": 0,
                   "observed_reference_edges": 0}
        if post["valid"]:
            feedback = result.get("feedback", {})
            cov = set(feedback.get("coverage_ids", []))
            clo = set(feedback.get("closure_coverage_ids", []))
            novelty["coverage"] = len(cov - coverage)
            novelty["closure_coverage"] = len(clo - closure)
            coverage |= cov
            closure |= clo
            keys = {f"{p['cache_write_seq']}:{p['target_read_seq']}:{p['target_check_seq']}"
                    for p in post["retained_reference_paths"]}
            novelty["observed_reference_edges"] = len(keys - edge_keys)
            edge_keys |= keys
            last = post["faults"][-1]
            for point in points[index + 1:]:
                p = point["point"]
                if not any(r.get("type") == "DOOR_OBSERVED" and
                           r["seq"] > last["applied_seq"] and
                           all(r.get(k) == p[k] for k in
                               ("site", "node", "epoch", "door_ordinal"))
                           for r in rows):
                    continue
                plan = expected + expected_single_plan(point)
                if len(plan) > config["budget"]["max_faults_per_trial"]:
                    continue
                child = signature(plan)
                if child not in seen:
                    queue.append({"plan": plan, "signature": child,
                                  "parent_trial": trial_id,
                                  "selection_reason": "strict_retained_reference_mutation"})
                    seen.add(child)
        trials.append({"trial_id": trial_id, "plan_signature": sig,
                       "qualification": post["qualification"],
                       "valid": post["valid"], "novelty_eligible": post["novelty_eligible"],
                       "workload_outcome": post["workload_outcome"],
                       "exact_target_throw_candidates": post["exact_target_throw_candidates"],
                       "faults": post["faults"],
                       "retained_reference_paths": post["retained_reference_paths"],
                       "novelty": novelty, "elapsed_seconds": result["elapsed_seconds"]})
    require(round(elapsed, 3) == 142.739, "v5 cumulative elapsed time changed")
    valid = [t["trial_id"] for t in trials if t["valid"]]
    candidates = [t["trial_id"] for t in trials if t["exact_target_throw_candidates"]]
    remaining = {"trials": config["budget"]["trials"] - len(trials),
                 "seconds": round(config["budget"]["seconds"] - elapsed, 3),
                 "max_faults_per_trial": config["budget"]["max_faults_per_trial"]}
    return {"schema_version": 1, "case_id": "SOLR-39", "mode": "preemptive_fault_v6",
            "source_v5_commit": "7ccd90d9", "status":
            "queue_exhausted_after_strict_reclassification" if not queue else "staged_no_go",
            "go": False, "jvm_run": False, "new_bug_confirmed": False,
            "completed_fault_trials": [1, 2, 3], "next_trial": 4,
            "cumulative_elapsed_seconds": round(elapsed, 3),
            "remaining_budget": remaining, "valid_trials": valid,
            "invalid_trials": [t["trial_id"] for t in trials if not t["valid"]],
            "exact_target_exception_candidates": candidates,
            "queue": queue, "seen_sequences": sorted(seen),
            "coverage_ids": sorted(coverage),
            "closure_coverage_ids": sorted(closure),
            "edge_keys": sorted(edge_keys), "trials": trials,
            "terminal_reason": ("only strict-valid r0003 is the last qualified selected door; "
                                "r0001/r0002 lose the bound actor target and cannot seed children"
                                if not queue else None)}


def reclassify() -> tuple[dict, dict]:
    pins = verify_sealed()
    audits, results, rows = [], [], []
    for trial_id in (1, 2, 3):
        trial = RAW / "trials" / f"r{trial_id:04d}"
        result = load(trial / "result.json")
        post = audit(trial, result["plan"])
        audits.append(post)
        results.append(result)
        rows.append(events_from(trial))
    state = rebuild_state(audits, results, rows)
    require([t["valid"] for t in state["trials"]] == [False, False, True] and
            state["trials"][2]["retained_reference_paths"][0]["cache_write_seq"] == 32094 and
            state["trials"][2]["retained_reference_paths"][0]["target_read_seq"] == 32892 and
            state["trials"][2]["retained_reference_paths"][0]["target_check_seq"] == 32895 and
            state["trials"][2]["retained_reference_paths"][0]["aliases_ref"] == 81 and
            state["trials"][2]["retained_reference_paths"][0]["zk_version"] == 15 and
            not state["queue"] and not state["exact_target_exception_candidates"],
            "sealed v5 reclassification did not match raw evidence")
    return pins, state


def canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, indent=2) + "\n"


def terminal_receipt(pins: dict, state: dict) -> dict:
    witness = state["trials"][2]["retained_reference_paths"][0]
    return {"schema_version": 1, "case_id": "SOLR-39",
            "kind": "deterministic_sealed_terminal_replay",
            "source_v5_commit": "7ccd90d9", "source_v5_archive_sha256": pins["archive_sha256"],
            "source_v5_member_manifest_sha256": pins["member_manifest_sha256"],
            "source_v5_admission_go_sha256": pins["v5_admission_go_sha256"],
            "v6_audit_sha256": sha(HERE / "audit_trial.py"),
            "source_pins_sha256": sha(HERE / "source-pins.json"),
            "continuation_checkpoint_sha256": sha(HERE / "continuation-checkpoint.json"),
            "trial_qualifications": [{"trial_id": t["trial_id"],
                                      "valid": t["valid"],
                                      "qualification": t["qualification"],
                                      "workload_outcome": t["workload_outcome"]}
                                     for t in state["trials"]],
            "strict_valid_trials": state["valid_trials"],
            "r0003_exact_prior_reference_witness": {
                key: witness[key] for key in
                ("node", "epoch", "manager_object", "owner_ref", "aliases_ref",
                 "zk_version", "cache_write_seq", "fault_applied_seq",
                 "target_read_seq", "target_check_seq", "observed_edge_kinds")},
            "exact_target_exception_candidates": [], "new_bug_confirmed": False,
            "fault_trials_completed": 3,
            "elapsed_seconds": state["cumulative_elapsed_seconds"],
            "remaining_budget": state["remaining_budget"],
            "queue_size": len(state["queue"]), "status": state["status"],
            "go": False, "jvm_run": False}


def canonical_import_proposal(state: dict) -> dict:
    """Exact dispatch mapping; only dispatch may write the canonical table."""
    config = load(CONFIG)
    test = config["cluster_test"]
    return {"schema_version": 1, "case_id": "SOLR-39",
            "status": "proposal_only_not_imported",
            "canonical_destination": "data/mallory/cases/SOLR-39",
            "source_paths": {
                "config": "Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v5/config.json",
                "checkpoint": "Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v6/continuation-checkpoint.json",
                "terminal_receipt": "Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v6/terminal-replay-receipt.json",
                "raw_archive": "data/mallory/evidence_archives/SOLR-39-preemptive-fault-node1-v5.tar.gz"},
            "config_sha256": sha(CONFIG),
            "checkpoint_sha256": sha(HERE / "continuation-checkpoint.json"),
            "terminal_receipt_sha256": sha(HERE / "terminal-replay-receipt.json"),
            "result_fields": {"schema_version": 1, "case_id": "SOLR-39",
                              "system": "solr", "cluster_test": test,
                              "status": "queue_exhausted",
                              "healthy_seed_valid": True,
                              "fault_trials_completed": 3,
                              "duration_seconds": 142.739,
                              "strict_injected_trials": 3,
                              "strict_target_trials": 1,
                              "target_reached_trials": 1,
                              "exact_exception_trials": 0,
                              "target_exception_candidate_trials": [],
                              "new_bug": None,
                              "source_review_status": "no_exact_target_throw_observed",
                              "quality_status": "strict_postfault_prior_reference_path_verified",
                              "v6_valid_trials": [3],
                              "v6_invalid_trials": [1, 2],
                              "v6_terminal_receipt":
                              "terminal-replay-receipt.json"},
            "checklist_row_updates": {
                "cluster_test": test, "campaign_cluster_test": test,
                "report_status": "completed_campaign",
                "quality_status": "strict_postfault_prior_reference_path_verified",
                "campaign_status": "queue_exhausted",
                "result_path": "data/mallory/cases/SOLR-39/result.json",
                "duration_seconds": 142.739,
                "fault_trials_completed": 3,
                "strict_injected_trials": 3,
                "strict_target_trials": 1,
                "target_reached_trials": 1,
                "exact_exception_trials": 0,
                "new_bug": None},
            "import_guard": "verify pinned archive and v6 terminal receipt; do not rerun any of the three seen plans"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-proof", action="store_true",
                        help="write case-local deterministic offline proof and checkpoint")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    pins, state = reclassify()
    if args.write_proof:
        (HERE / "source-pins.json").write_text(canonical(pins))
        (HERE / "continuation-checkpoint.json").write_text(canonical(state))
        (HERE / "terminal-replay-receipt.json").write_text(
            canonical(terminal_receipt(pins, state)))
        (HERE / "canonical-import-proposal.json").write_text(
            canonical(canonical_import_proposal(state)))
    if args.preflight_only:
        require(load(HERE / "source-pins.json") == pins and
                load(HERE / "continuation-checkpoint.json") == state and
                load(HERE / "terminal-replay-receipt.json") ==
                terminal_receipt(pins, state) and
                load(HERE / "canonical-import-proposal.json") ==
                canonical_import_proposal(state),
                "offline proof or checkpoint differs from sealed replay")
        manifest = load(HERE / "sha-manifest.json")
        for name, digest in manifest["files"].items():
            require(sha(HERE / name) == digest, f"v6 package SHA changed: {name}")
        stage = load(HERE / "stage-request.json")
        require(stage["case_id"] == "SOLR-39" and
                stage["mode"] == "preemptive_fault_v6" and
                stage["go"] is False and stage["runtime_ready"] is False and
                stage["jvm_run"] is False and stage["queue_size"] == 0 and
                stage["manifest_sha256"] == sha(HERE / "sha-manifest.json") and
                stage["audit_sha256"] == sha(HERE / "audit_trial.py") and
                stage["reconcile_sha256"] == sha(Path(__file__)) and
                stage["continuation_checkpoint_sha256"] ==
                sha(HERE / "continuation-checkpoint.json"),
                "v6 GO=false handoff or SHA pins changed")
    print(json.dumps({"status": state["status"], "go": False, "jvm_run": False,
                      "v5_archive_sha256": pins["archive_sha256"],
                      "valid_trials": state["valid_trials"],
                      "queue_size": len(state["queue"]),
                      "remaining_budget": state["remaining_budget"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
