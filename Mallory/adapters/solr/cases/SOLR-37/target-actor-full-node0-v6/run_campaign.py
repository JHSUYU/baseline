#!/usr/bin/env python3
"""Resume the sealed SOLR-37 pilot with an actor-aware strict frontier."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import gzip
import hashlib
import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V5 = HERE.parent / "target-actor-fault-pilot-node0-v5"
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
OUT = ROOT / "data/mallory/solr37_target_actor_full_v6_node0/SOLR-37/full"
sys.path.insert(0, str(V5))
sys.path.insert(0, str(RELEASE))
sys.path.insert(0, str(HERE))
_pilot_spec = importlib.util.spec_from_file_location("solr37_pilot_v5", V5 / "run_campaign.py")
assert _pilot_spec is not None and _pilot_spec.loader is not None
pilot = importlib.util.module_from_spec(_pilot_spec)
_pilot_spec.loader.exec_module(pilot)
from audit_exact_path import DOOR, EXCEPTION, REGION, RESOURCE, audit_trial, evaluate  # noqa: E402
from Mallory.core import campaign, scheduler  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def preflight() -> dict:
    pilot.preflight()
    manifest = read(HERE / "sha-manifest.json")
    if manifest.get("case_id") != "SOLR-37":
        raise ValueError("wrong case manifest")
    for name, expected in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != expected["bytes"]
                or sha(path) != expected["sha256"]):
            raise ValueError(f"staged file changed: {name}")
    config_path = HERE / "config-full-node0.json"
    config = read(config_path)
    if (config.get("case_id") != "SOLR-37" or config.get("site_file") != str(HERE / "sites.json")
            or config.get("core_release") != str(RELEASE)
            or config.get("explore_outside_closure") is not False
            or config.get("require_event_time_paths") is not True
            or config.get("reject_coarse_roots") is not True
            or config.get("fault_types") != ["EXCEPTION"]
            or config.get("budget") != {"trials": 17, "seconds": 3600,
                                        "max_faults_per_trial": 3,
                                        "trial_timeout_seconds": 360}):
        raise ValueError("unexpected full campaign config")
    for row in config["runtime_artifacts"]:
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    parent = config["v5_parent"]
    receipt = read(Path(parent["receipt"]))
    members = read(Path(parent["member_manifest"]))
    if (receipt.get("status") != "budget_exhausted" or
            receipt.get("strict_effective_target_retaining_trials") != [1, 2] or
            receipt.get("strict_missing_receipt_trials") != [3, 4, 5, 6] or
            receipt.get("archive_sha256") != sha(Path(parent["archive"])) or
            members.get("archive_sha256") != receipt["archive_sha256"] or
            members.get("member_count") != len(members.get("members", []))):
        raise ValueError("sealed v5 parent changed")
    alt = config["v5_shard2_alternate_healthy"]
    alt_proof = read(HERE / "shard2-observed-closure.json")
    parent_rows = {row["path"]: row for row in members["members"]}
    trace_row = parent_rows.get("solr37_target_actor_fault_pilot_v5_node0/SOLR-37/pilot/"
                                "trials/r0003/events.jsonl.gz", {})
    if (alt.get("trial_id") != 3 or alt.get("target_actor") != "shard-2" or
            alt.get("qualified_ordinals") != [22, 26, 29, 31, 33] or
            alt.get("strict_witness_count") != 164 or alt.get("resource") != RESOURCE or
            alt_proof.get("v5_events_gzip_sha256") != trace_row.get("sha256") or
            alt_proof.get("strict_witness_count") != 164 or
            alt_proof.get("candidate_state_edges") != 0 or
            [row["door_ordinal"] for row in alt_proof.get("qualified_points", [])]
            != [22, 26, 29, 31, 33] or
            {row["node"] for row in alt_proof["qualified_points"]} != {"shard-2"}):
        raise ValueError("shard-2 observed frontier changed")
    campaign.validate_config(config)
    request = read(HERE / "admission-request.json")
    if (request.get("go") is not False or request.get("execution_status") != "not_launched"
            or request.get("host") != "node0" or request.get("case_id") != "SOLR-37"
            or request.get("mode") != "full" or
            request.get("runner_sha256") != sha(Path(__file__)) or
            request.get("config_sha256") != sha(config_path) or
            request.get("intended_output") != str(OUT)):
        raise ValueError("staged admission request changed")
    return {"runner_sha256": sha(Path(__file__)), "config_sha256": sha(config_path),
            "parent_archive_sha256": receipt["archive_sha256"]}


def point(node: str, ordinal: int) -> dict:
    return {"site": DOOR, "node": node, "epoch": 0, "door_ordinal": ordinal,
            "resource": RESOURCE, "region": REGION,
            "occurrence_kind": "watcher_region"}


def candidate(node: str, ordinal: int, priority: float, reason: str) -> dict:
    p = point(node, ordinal)
    fault = {"fault_id": "f" + scheduler.digest([0, p, "EXCEPTION"]),
             "point": p, "fault_type": "EXCEPTION", "exception_class": EXCEPTION}
    faults = [fault]
    return {"faults": faults, "signature": scheduler.sequence_signature(faults),
            "priority": priority, "queued_at": 6, "selection_reason": reason}


def _verified_parent_member(archive: tarfile.TarFile, members: dict,
                            relative: str) -> bytes:
    full = "solr37_target_actor_fault_pilot_v5_node0/SOLR-37/pilot/" + relative
    rows = [row for row in members["members"] if row["path"] == full]
    if len(rows) != 1:
        raise ValueError(f"parent archive member absent: {relative}")
    stream = archive.extractfile(full)
    if stream is None:
        raise ValueError(f"parent archive member unreadable: {relative}")
    data = stream.read()
    if len(data) != rows[0]["bytes"] or hashlib.sha256(data).hexdigest() != rows[0]["sha256"]:
        raise ValueError(f"parent archive member digest mismatch: {relative}")
    return data


def reconstruct_parent(config: dict, *, dry_run: bool = False) -> dict:
    """Import v5 once; all completed IDs and valid signatures remain consumed."""
    parent = config["v5_parent"]
    members = read(Path(parent["member_manifest"]))
    with tarfile.open(parent["archive"], "r:gz") as archive:
        checkpoint = json.loads(_verified_parent_member(archive, members, "checkpoint.json"))
        old_config = json.loads(_verified_parent_member(archive, members, "config.json"))
        if (checkpoint.get("status") != "budget_exhausted" or
                checkpoint.get("completed_trials") != list(range(7)) or
                checkpoint.get("next_trial") != 7 or
                checkpoint.get("config_digest") != campaign.digest(old_config)):
            raise ValueError("v5 checkpoint is not terminal and complete")
        prior = []
        for trial_id in range(7):
            base = f"trials/r{trial_id:04d}/"
            result = json.loads(_verified_parent_member(archive, members, base + "result.json"))
            strict = json.loads(_verified_parent_member(archive, members, base + "strict-audit.json"))
            if result.get("trial_id") != trial_id or bool(strict.get("valid")) != (trial_id in (0, 1, 2)):
                raise ValueError("v5 trial strict status changed")
            prior.append(result)
        if any(not prior[n]["feedback"]["all_faults_effective"] for n in (1, 2)):
            raise ValueError("v5 valid trials lost their injection receipts")
        valid_signatures = {scheduler.sequence_signature(prior[n]["plan"]) for n in (1, 2)}
        frontier = [candidate("shard-2", n, 54.0 - i, "v5_shard2_observed_closure")
                    for i, n in enumerate((33, 31, 29, 26, 22))]
        frontier += [candidate("shard-4", n, 46.0 - i, "v5_unmatched_retry")
                     for i, n in enumerate((29, 27, 23))]
        existing = list(checkpoint["queue"])
        queue = frontier + existing
        signatures = [row["signature"] for row in queue]
        if len(signatures) != len(set(signatures)) or valid_signatures.intersection(signatures):
            raise ValueError("queued a duplicate or replayed valid v5 fault")
        checkpoint["queue"] = queue
        checkpoint["seen_sequences"] = sorted(set(checkpoint["seen_sequences"]) | set(signatures))
        # r0003-r0006 were unmatched actor-drift attempts. Their raw evidence
        # remains in the sealed parent, but they cannot seed v6 novelty or depth.
        checkpoint["completed_trials"] = [0, 1, 2]
        checkpoint["elapsed_seconds"] = sum(prior[n]["elapsed_seconds"] for n in (0, 1, 2))
        checkpoint["coverage_ids"] = sorted({value for n in (0, 1, 2)
                                               for value in prior[n]["feedback"].get("coverage_ids", [])})
        checkpoint["closure_coverage_ids"] = sorted({value for n in (0, 1, 2)
                                                       for value in prior[n]["feedback"].get("closure_coverage_ids", [])})
        checkpoint["edge_fingerprints"] = sorted({campaign.digest(
            [edge["source"], edge["target"], edge["kind"], edge["certainty"]])
            for n in (0, 1, 2) for edge in prior[n]["feedback"].get("closure_edges", [])})
        checkpoint["target_exception_candidates"] = []
        checkpoint["reproduced_candidates"] = []
        checkpoint["config_digest"] = campaign.digest(config)
        checkpoint["status"] = "running"
        checkpoint["out"] = str(OUT)
        checkpoint["running"] = None
        checkpoint["updated_at"] = checkpoint["created_at"]
        summary = {"schema_version": 1, "case_id": "SOLR-37", "parent_archive": parent["archive"],
                   "parent_archive_sha256": members["archive_sha256"],
                   "imported_trials": [0, 1, 2],
                   "excluded_unmatched_parent_trials": [3, 4, 5, 6],
                   "valid_v5_fault_trials_not_requeued": [1, 2],
                   "v5_alternate_actor_healthy_trial": 3,
                   "new_frontier": [{"node": row["faults"][0]["point"]["node"],
                                      "ordinal": row["faults"][0]["point"]["door_ordinal"]}
                                     for row in frontier],
                   "queued_signatures": signatures,
                   "next_trial": checkpoint["next_trial"]}
        if dry_run:
            return summary
        if OUT.exists():
            raise ValueError("v6 output already exists; resume from its checkpoint instead")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".solr37-v6-bootstrap-", dir=OUT.parent))
        try:
            campaign.atomic_json(temporary / "config.json", config)
            for trial_id in (0, 1, 2):
                base = f"trials/r{trial_id:04d}/"
                target = temporary / base
                target.mkdir(parents=True)
                for name in ("result.json", "plan.json", "strict-audit.json",
                             "events.jsonl.gz", "junit-receipt.json", "sites.jsonl",
                             "stdout.log", "stderr.log"):
                    (target / name).write_bytes(_verified_parent_member(
                        archive, members, base + name))
            campaign.atomic_json(temporary / "parent-import.json", summary)
            campaign.atomic_json(temporary / "checkpoint.json", checkpoint)
            temporary.rename(OUT)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return summary


def install_v6_runtime() -> None:
    """Keep strict v5 receipts, but resolve the actual target actor on each run."""
    original_core_apply = campaign._apply_result

    def sanitize_core_apply(state: dict, config: dict, result: dict, item: dict | None) -> None:
        audit = result.get("strict_audit", {})
        feedback = result["feedback"]
        if audit.get("valid"):
            feedback["strict_qualified_points"] = audit.get("qualified_points", [])
            if result["plan"] and feedback.get("target_exception_candidate") and not audit.get(
                    "exact_postfault_target_throws"):
                feedback["target_exception_candidate"] = False
        else:
            # Invalid plans consume trial budget but cannot contribute novelty or descendants.
            feedback.update(status="strict_" + audit.get("reason", "audit_missing"),
                            target_reached=False, all_faults_effective=False,
                            target_exception_candidate=False, doors=[], coverage_ids=[],
                            closure_coverage_ids=[], closure_edges=[],
                            strict_qualified_points=[])
        original_core_apply(state, config, result, item)

    campaign._apply_result = sanitize_core_apply
    pilot_original_audit = audit_trial

    def deep_audit(events: tuple[dict, ...], plan: list[dict]) -> dict:
        result = pilot_original_audit(events, plan)
        if result.get("valid") and plan:
            actor = (plan[-1]["point"]["node"], plan[-1]["point"]["epoch"])
            last_apply = max(row.get("seq", -1) for row in events
                             if row.get("type") == "FAULT_APPLIED" and
                             row.get("fault_id") == plan[-1]["fault_id"])
            reader_ref = result["fault_receipts"][-1]["reader_ref"]
            proof = evaluate(events, min_target_seq=last_apply, actor=actor,
                             reader_ref=reader_ref)
            result["exact_postfault_target_throws"] = [row["id"] for row in events
                if row.get("type") == "TARGET_THROW" and
                row.get("site") == "org.apache.solr.update.processor.DistributedZkUpdateProcessor"
                    "#doDefensiveChecks(Lorg/apache/solr/update/processor/"
                    "DistributedUpdateProcessor$DistribPhase;)V@995:throw:1" and
                (row.get("node"), row.get("epoch")) == actor and
                row.get("seq", -1) > last_apply]
            result["qualified_points"] = proof["qualified_points"]
            result["strict_witness_count"] = proof["strict_witness_count"]
            result["candidate_state_edges"] = proof["candidate_state_edges"]
            if proof["strict_witness_count"] == 0:
                result.update(valid=False, reason="postfault_exact_reference_path_missing")
        return result

    pilot.audit_trial = deep_audit
    pilot.install_strict_runtime()
    v5_mutate = campaign.mutate

    def strict_mutate(parent: list, feedback: dict, config: dict) -> list:
        qualified = {(row["node"], row["epoch"], row["door_ordinal"])
                     for row in feedback.get("strict_qualified_points", [])}
        filtered = [door for door in feedback.get("doors", [])
                    if (door.get("point", {}).get("node"),
                        door.get("point", {}).get("epoch"),
                        door.get("point", {}).get("door_ordinal")) in qualified]
        return v5_mutate(parent, {**feedback, "doors": filtered}, config)

    campaign.mutate = strict_mutate
    original_run_trial = campaign._run_trial

    def actor_aware_run_trial(config: dict, out: Path, trial_id: int, plan: list,
                              save_running, target_binding: dict | None) -> dict:
        # v5's shard-4 healthy binding blinded r0003-r0006: their raw targets
        # were all shard-2. The strict audit below binds a fault to the actual
        # named target actor after each new trial, so core feedback must be unbound.
        return original_run_trial(config, out, trial_id, plan, save_running, None)

    campaign._run_trial = actor_aware_run_trial


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--dry-run-reconstruct", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    config = read(HERE / "config-full-node0.json")
    if args.preflight_only or args.dry_run_reconstruct:
        if args.dry_run_reconstruct:
            metadata["reconstruction"] = reconstruct_parent(config, dry_run=True)
        print(json.dumps({"preflight": "passed", **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None or args.admission_receipt.resolve() != HERE / "admission-full-node0.json":
        parser.error("case-local dispatch GO receipt required before starting a JVM")
    go = read(args.admission_receipt)
    if (go.get("go") is not True or go.get("host") != "node0" or
            go.get("case_id") != "SOLR-37" or go.get("mode") != "full" or
            go.get("config_sha256") != metadata["config_sha256"] or
            go.get("runner_sha256") != metadata["runner_sha256"] or
            go.get("intended_output") != str(OUT)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    if socket.gethostname().split(".", 1)[0] != "node0":
        raise ValueError("node0 execution only")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    locks = []
    try:
        for name in ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks.append(handle)
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("insufficient free disk")
        available_kib = next(int(row.split()[1]) for row in
                             Path("/proc/meminfo").read_text().splitlines()
                             if row.startswith("MemAvailable:"))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available RAM")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"] for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node0")
        if not OUT.exists():
            reconstruct_parent(config)
        elif not (OUT / "checkpoint.json").is_file():
            raise ValueError("existing v6 output has no resumable checkpoint")
        install_v6_runtime()
        state = campaign.run(HERE / "config-full-node0.json", OUT)
    finally:
        for handle in reversed(locks):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
