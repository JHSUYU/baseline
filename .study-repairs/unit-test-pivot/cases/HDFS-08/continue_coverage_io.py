"""Resume HDFS-08 using production coverage and observed I/O.

The first 48 completed runs used a GraphChecker-prewoven recorder with a
runtime region skeleton. Runs 49+ use discovery mode without loading that
skeleton; both segments retain the prewoven low-level probe artifact. No
runtime selection or feedback reads a graph, static slice, or closure plan.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

import coverage_io_feedback as feedback
from audit_legacy_coverage_io import (HERE, METHOD, GUARD,
                                      production_coverage, target)


CHECKPOINT = HERE / "coverage-io-checkpoint.json"
RESULT = HERE / "result.json"
NEW = HERE / "coverage-io-new"
REMOTE = "ZhenyuLi@node1"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", REMOTE]
RSYNC = ["rsync", "-a", "-e",
         "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes"]
POLICY = target("target-runtime-multiwriter.json")
DISCOVERY_POLICY = {
    **POLICY,
    "occurrence": None,
    "runtime_identity": {
        "source_key": "jn2#epoch0",
        "request_api": "QuorumJournalManager.recoverUnfinalizedSegments(phase=2)",
        "parent_method": "<org.apache.hadoop.hdfs.qjournal.server.Journal: void finalizeLogSegment(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo,long,long)>",
    },
}
SEED_TRACE = HERE / "evidence/healthy-multiwriter/runtime_trace.jsonl"

# Five I/O classes not yet injected in this original second-writer workload.
# These are observed event sequence numbers in the immutable healthy trace.
SINGLE_SEED_SEQS = [11656, 13376, 10539, 12093, 13743]


def run_command(args: list[str], log: Path | None = None) -> None:
    if log is None:
        subprocess.run(args, check=True)
    else:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as stream:
            subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=True)


def remote_exists(path: Path) -> bool:
    return subprocess.run(SSH + ["test", "-f", str(path)],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def observed_points(path: Path) -> list[tuple[int, dict]]:
    seen: set[str] = set()
    result = []
    for row in feedback.rows(path):
        if row.get("event") != "FAULT_POINT_OBSERVED":
            continue
        point = feedback.point_from_event(row)
        if point is None:
            continue
        key = feedback.fingerprint(point)
        if key not in seen:
            seen.add(key)
            result.append((row.get("seq", -1), point))
    return result


def policy_for_trace(path: Path) -> dict:
    for row in feedback.rows(path):
        if row.get("event") == "METHOD_ENTER" and row.get("method") == METHOD:
            return POLICY if row.get("occurrenceAddress") else DISCOVERY_POLICY
    # A fault may prevent every checkRequest call; the trial must then be
    # recorded as target-lost instead of aborting the resumable campaign.
    name = path.parent.name
    if name.startswith("coverage-io-") and int(name.rsplit("-", 1)[1]) >= 49:
        return DISCOVERY_POLICY
    if "discovery-validation" in str(path):
        return DISCOVERY_POLICY
    return POLICY


def selected_target_guard_seq(path: Path, applied_seq: int) -> int:
    target_calls = set(feedback.trace_feedback(path, policy_for_trace(path))[
        "target_call_ids"])
    hits = [row["seq"] for row in feedback.rows(path)
            if row.get("event") == "BRANCH" and row.get("siteId") == GUARD
            and row.get("callId") in target_calls and row.get("seq", -1) > applied_seq]
    if not hits:
        raise RuntimeError(f"no selected post-fault guard in {path}")
    return min(hits)


def legacy_trace(name: str) -> Path:
    if not name.startswith("multiwriter-"):
        raise ValueError(name)
    return HERE / "evidence" / ("legacy-" + name) / "runtime_trace.jsonl"


def completed_sequences(checkpoint: dict) -> set[str]:
    return {feedback.sequence_id(row["requested_selectors"])
            for row in (checkpoint["legacy_completed"] +
                        checkpoint["continuation_completed"])}


def healthy_single(seq: int) -> tuple[list[dict], str]:
    matches = [point for number, point in observed_points(SEED_TRACE)
               if number == seq]
    if len(matches) != 1:
        raise RuntimeError(f"healthy I/O seq {seq} missing or ambiguous")
    point = matches[0]
    if "phase=2" not in point["occurrence"]:
        raise RuntimeError(f"point {seq} is outside second-writer recovery")
    return [point], f"healthy second-writer observed I/O seq {seq}"


def mutation_options(path: Path, prefix: list[dict]) -> list[tuple[tuple, dict, int]]:
    assessment = feedback.trace_feedback(path, policy_for_trace(path))
    if not assessment["target_reached_after_fault"]:
        return []
    lower = assessment["last_applied_seq"]
    upper = selected_target_guard_seq(path, lower)
    used = {feedback.fingerprint(point) for point in prefix}
    healthy_addresses = {point["occurrence"]
                         for _, point in observed_points(SEED_TRACE)}
    options = []
    for seq, point in observed_points(path):
        if not (lower < seq < upper and "phase=2" in point["occurrence"]):
            continue
        if feedback.fingerprint(point) in used:
            continue
        marker = point["marker"]
        if not (marker.startswith("FAULT:HADOOP_IPC:RESPONSE") or
                marker.startswith("FAULT:HDFS_EPOCH_FILE:") or
                marker == "FAULT:HDFS_JOURNAL_FILE:SCAN_LOG"):
            continue
        address = point["occurrence"]
        new_address = address not in healthy_addresses
        # Retry-time epoch promise writes are new behavior caused by fault 1.
        if new_address and marker.startswith("FAULT:HDFS_EPOCH_FILE:") and \
                "Journal: void checkRequest(" in address:
            group = 0
        elif marker == "FAULT:HDFS_JOURNAL_FILE:SCAN_LOG" and \
                "AcceptRecovery" in address:
            group = 1
        elif marker == "FAULT:HDFS_JOURNAL_FILE:SCAN_LOG" and \
                "PrepareRecovery" in address:
            group = 2
        elif marker.startswith("FAULT:HADOOP_IPC:RESPONSE") and \
                "acceptRecovery(" in address:
            group = 3
        elif marker.startswith("FAULT:HDFS_EPOCH_FILE:"):
            group = 4
        else:
            group = 5
        options.append(((group, 0 if new_address else 1, seq), point, seq))
    return sorted(options, key=lambda item: item[0])


def choose_mutation(checkpoint: dict, trial_number: int) -> tuple[list[dict], str]:
    seen = completed_sequences(checkpoint)
    # The first continuation is the CrashFuzz-style new epoch write exposed
    # by the already completed OPEN_WRITE trial, not a repeated old selector.
    if trial_number == 41:
        seed = next(row for row in checkpoint["legacy_completed"]
                    if row["trial"] == "multiwriter-01")
        prefix = seed["requested_selectors"]
        options = mutation_options(legacy_trace(seed["trial"]), prefix)
        for _, point, seq in options:
            if point["marker"] == "FAULT:HDFS_EPOCH_FILE:OPEN_WRITE" and \
                    "PrepareRecovery" in point["occurrence"]:
                sequence = prefix + [point]
                if feedback.sequence_id(sequence) not in seen:
                    return sequence, f"new promise-file I/O at seq {seq} after prior OPEN fault"
        raise RuntimeError("faulted seed has no observed prepareRecovery promise-file I/O")
    max_faults = checkpoint["budget"]["max_faults"]
    parents = [row for row in checkpoint["continuation_completed"]
               if row["status"] == "checked" and
               1 <= len(row["requested_selectors"]) < max_faults]
    parents.sort(key=lambda row: (-len(row["requested_selectors"]),
                                  -row.get("new_production_coverage_vs_prior", 0),
                                  row["trial"]))
    for name in ("multiwriter-02", "multiwriter-03", "multiwriter-01"):
        parents.append(next(row for row in checkpoint["legacy_completed"]
                            if row["trial"] == name))
    for parent in parents:
        prefix = parent["requested_selectors"]
        if len(prefix) >= max_faults:
            continue
        trace = (Path(parent["local_trace"]) if "local_trace" in parent else
                 legacy_trace(parent["trial"]))
        if not trace.is_file():
            continue
        for _, point, seq in mutation_options(trace, prefix):
            sequence = prefix + [point]
            if feedback.sequence_id(sequence) not in seen:
                return sequence, f"mutated {parent['trial']} with observed post-fault I/O seq {seq}"
    raise RuntimeError(f"no new observed post-fault sequence within {max_faults}-fault cap")


def choose_discovery_sequence(checkpoint: dict) -> tuple[list[dict], str]:
    """Grow only from trials recorded in discovery mode.

    Healthy selectors stayed identical across the mode switch, but the first
    four attempts demonstrated that fault-induced retry addresses did not.
    Reusing a legacy post-fault selector as a later fault therefore wastes a
    trial. New seeds come from the healthy trace; extensions come from an
    actual discovery-mode faulted trace.
    """
    seen = completed_sequences(checkpoint)
    max_faults = checkpoint["budget"]["max_faults"]
    parents = [row for row in checkpoint["continuation_completed"]
               if row.get("runtime_trace_mode") == "discovery" and
               row["status"] == "checked" and
               len(row["requested_selectors"]) < max_faults]
    parents.sort(key=lambda row: (-row.get("new_production_coverage_vs_prior", 0),
                                  -row.get("new_io_families_vs_prior", 0),
                                  -len(row["requested_selectors"]), row["trial"]))
    for parent in parents:
        prefix = parent["requested_selectors"]
        direct_lost = sum(
            row["status"] == "lost_target" and
            len(row["requested_selectors"]) == len(prefix) + 1 and
            row["requested_selectors"][:len(prefix)] == prefix
            for row in checkpoint["continuation_completed"])
        if direct_lost >= 2:
            continue
        for _, point, seq in mutation_options(Path(parent["local_trace"]), prefix):
            sequence = prefix + [point]
            if feedback.sequence_id(sequence) not in seen:
                return sequence, (f"mutated discovery trial {parent['trial']} with "
                                  f"observed post-fault I/O seq {seq}")
    preferred_healthy = (10143, 10149, 10210, 10222, 11677, 13395,
                         9351, 9365, 10506, 10522, 12075, 12085,
                         13748, 13753)
    points = {seq: point for seq, point in observed_points(SEED_TRACE)}
    for seq in preferred_healthy:
        point = points.get(seq)
        if point and feedback.sequence_id([point]) not in seen:
            return [point], f"new discovery seed from observed healthy phase-2 I/O seq {seq}"
    for seq, point in observed_points(SEED_TRACE):
        if ("phase=2" in point["occurrence"] and
                feedback.sequence_id([point]) not in seen and
                (point["marker"].startswith("FAULT:HDFS_EPOCH_FILE:") or
                 point["marker"] == "FAULT:HDFS_JOURNAL_FILE:SCAN_LOG" or
                 point["marker"].startswith("FAULT:HADOOP_IPC:RESPONSE"))):
            return [point], f"new discovery seed from observed healthy phase-2 I/O seq {seq}"
    raise RuntimeError("no new discovery-mode mutation or healthy I/O seed")


def plan(checkpoint: dict, trial_number: int) -> tuple[list[dict], str]:
    if trial_number == 41:
        return choose_mutation(checkpoint, trial_number)
    if 42 <= trial_number <= 46:
        sequence, reason = healthy_single(SINGLE_SEED_SEQS[trial_number - 42])
        if feedback.sequence_id(sequence) in completed_sequences(checkpoint):
            raise RuntimeError(f"planned trial {trial_number} repeats a completed selector")
        return sequence, reason
    if trial_number >= 49:
        return choose_discovery_sequence(checkpoint)
    return choose_mutation(checkpoint, trial_number)


def get_trial_artifacts(trial_number: int, sequence: list[dict]) -> tuple[Path, Path, dict, float]:
    name = f"coverage-io-{trial_number:02d}"
    local = NEW / name
    local.mkdir(parents=True, exist_ok=True)
    local_plan = local / "fault-trial.json"
    if not local_plan.exists():
        feedback.write_trial(local_plan, sequence, POLICY)
    remote_dir = HERE / name
    remote_plan = HERE / "coverage-io-new" / name / "fault-trial.json"
    run_command(SSH + ["mkdir", "-p", str(remote_plan.parent)])
    run_command(RSYNC + [str(local_plan), REMOTE + ":" + str(remote_plan)])
    started = time.monotonic()
    if not remote_exists(remote_dir / "manifest.json"):
        cmd = (SSH + ["python3", str(HERE / "run_state_case.py"), "run",
                      "--ipc", "--door", "--control", "--no-aggregate",
                      "--test-method", "testChangeWritersLogsInSync",
                      "--trial", str(remote_plan), "--run-name", name])
        run_command(cmd, local / "driver.log")
    for remote_file, local_file in (
            (remote_dir / "manifest.json", local / "manifest.json"),
            (remote_dir / "trace/runtime_trace.jsonl", local / "runtime_trace.jsonl"),
            (remote_dir / "runtime.log", local / "runtime.log")):
        run_command(RSYNC + [REMOTE + ":" + str(remote_file), str(local_file)])
    manifest = json.loads((local / "manifest.json").read_text())
    elapsed = max(time.monotonic() - started,
                  manifest["compile"]["elapsed_seconds"] +
                  manifest["runtime"]["elapsed_seconds"])
    return local, local / "runtime_trace.jsonl", manifest, elapsed


def summarize_trial(checkpoint: dict, trial_number: int, sequence: list[dict],
                    reason: str, local: Path, trace: Path, manifest: dict,
                    elapsed: float) -> dict:
    assessed = feedback.trace_feedback(trace, policy_for_trace(trace))
    strict = feedback.strict_injection(assessed, sequence)
    retained = assessed["target_reached_after_fault"]
    candidate = bool(strict and retained and assessed["oracle"] and
                     assessed["target_fatal_exception_count"] > 0)
    status = ("unmatched" if not strict else "lost_target" if not retained else
              "target_exception_candidate" if candidate else "checked")
    covered = production_coverage(assessed["coverage"])
    prior = set(checkpoint["seed"]["multi_writer_recovery"]["production_coverage"])
    prior_io = set(checkpoint["seed"]["multi_writer_recovery"]["io_families"])
    for old in checkpoint["legacy_completed"] + checkpoint["continuation_completed"]:
        if old["phase"] == "multi_writer_recovery" and old["status"] == "checked":
            prior.update(old["production_coverage"])
            prior_io.update(old["observed_io_families"])
    families = set(feedback.fault_family(point) for point in assessed["points"])
    row = {
        "phase": "multi_writer_recovery", "trial": f"coverage-io-{trial_number:02d}",
        "test_method": "testChangeWritersLogsInSync",
        "trace": str(HERE / row_name(trial_number) / "trace/runtime_trace.jsonl"),
        "local_trace": str(trace),
        "result": str(local / "trial-result.json"),
        "requested_selectors": sequence,
        "selector_ids": [feedback.fingerprint(point) for point in sequence],
        "sequence_id": feedback.sequence_id(sequence),
        "selection_reason": reason,
        "seconds": round(elapsed, 3),
        "junit_seconds": manifest["runtime"]["elapsed_seconds"],
        "junit_exit": manifest["runtime"]["exit"],
        "runtime_trace_mode": manifest.get("trace_mode", "region-state"),
        "region_skeletons_loaded": manifest.get("region_skeletons_loaded", True),
        "instrumentation_artifact": "graphchecker_preweave_state_door",
        "strict_injection": strict, "matched_faults": assessed["matched_count"],
        "applied_faults": assessed["applied_count"],
        "target_guard_after_last_fault": retained,
        "target_outcomes_after_fault": assessed["target_outcomes_after_fault"],
        "target_fatal_exception_count": assessed["target_fatal_exception_count"],
        "target_exception_after_fault": assessed["target_after_fault"],
        "production_coverage": sorted(covered),
        "new_production_coverage_vs_prior": len(covered - prior) if retained and strict else 0,
        "observed_io_families": sorted(families),
        "new_io_families_vs_prior": len(families - prior_io) if retained and strict else 0,
        "observed_io_points": len(assessed["points"]),
        "status": status,
        "bug_mark": "candidate" if candidate else "none",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    feedback.atomic_json(local / "trial-result.json", row)
    return row


def row_name(number: int) -> str:
    return f"coverage-io-{number:02d}"


def case_record(checkpoint: dict) -> dict:
    result = json.loads(RESULT.read_text())
    new = checkpoint["continuation_completed"]
    all_rows = checkpoint["legacy_completed"] + new
    by_phase = {}
    for phase, seed in checkpoint["seed"].items():
        base = set(seed["production_coverage"])
        union = set(base)
        for row in all_rows:
            if row["phase"] == phase and row["status"] == "checked":
                union.update(row["production_coverage"])
        by_phase[phase] = {"healthy_ids": len(base),
                           "fault_union_ids": len(union),
                           "gain_ids": len(union - base)}
    new_seconds = sum(row["seconds"] for row in new)
    budget_reached = len(all_rows) >= checkpoint["budget"]["max_trials"]
    recent = new[-8:]
    recent_novelty = any(row.get("new_production_coverage_vs_prior", 0) or
                         row.get("new_io_families_vs_prior", 0) for row in recent)
    has_candidate = any(row["bug_mark"] == "candidate" for row in all_rows)
    status = ("candidate_review" if has_candidate else
              "pending_budget_expansion" if budget_reached and recent_novelty else
              "quality_complete" if budget_reached else "fuzzing")
    result.update({
        "methodology": "coverage_io_no_graph_decisions_mixed_recorder_provenance",
        "status": status,
        "fault_trials": len(all_rows),
        "requested_fault_events": sum(len(row["requested_selectors"]) for row in all_rows),
        "matched_fault_events": sum(row["matched_faults"] for row in all_rows),
        "applied_fault_events": sum(row["applied_faults"] for row in all_rows),
        "strict_injection_trials": sum(bool(row["strict_injection"]) for row in all_rows),
        "strict_target_after_fault_trials": sum(row["strict_injection"] and
              row["target_guard_after_last_fault"] for row in all_rows),
        "post_fault_target_reach_trials": sum(row["strict_injection"] and
              row["target_guard_after_last_fault"] for row in all_rows),
        "target_lost_trials": sum(row["status"] == "lost_target" for row in all_rows),
        "target_fatal_trials": sum(row["strict_injection"] and
              row["target_fatal_exception_count"] > 0 for row in all_rows),
        "target_exception_after_fault_trials": sum(row["strict_injection"] and
              row["bug_mark"] == "candidate" for row in all_rows),
        "oracle_candidates": sum(row["strict_injection"] and
              row["bug_mark"] == "candidate" for row in all_rows),
        "bug_mark": "candidate" if any(row["bug_mark"] == "candidate" for row in all_rows)
                    else "none",
        "coverage_type": "HDFS production method entry and branch outcome IDs; instrumented PersistentLongFile.writeFile branches excluded",
        "production_coverage_by_workload": by_phase,
        "coverage_gain": {key: value["gain_ids"] for key, value in by_phase.items()},
        "new_coverage_io_trials": len(new),
        "multi_writer_recovery_trials": sum(row["phase"] == "multi_writer_recovery"
                                             for row in all_rows),
        "maximum_requested_faults_in_a_trial": max(
            len(row["requested_selectors"]) for row in all_rows),
        "maximum_strict_target_retaining_faults_in_a_trial": max(
            (len(row["requested_selectors"]) for row in all_rows
             if row["strict_injection"] and row["target_guard_after_last_fault"]),
            default=0),
        "legacy_region_state_trials": sum(row.get("region_skeletons_loaded", True)
                                          for row in all_rows),
        "discovery_without_runtime_skeleton_trials": sum(
            not row.get("region_skeletons_loaded", True) for row in all_rows),
        "instrumentation_note": "All trials load a GraphChecker-prewoven HDFS recorder. Trials 1-48 additionally loaded a runtime region skeleton; trials 49+ use discovery mode with no runtime skeleton or graph aggregation. The fault selection and feedback use observed I/O and production coverage, not a closure graph. This is not a fully graph-independent instrumentation result.",
        "baseline_trial_budget": checkpoint["budget"]["max_trials"],
        "baseline_max_faults_per_sequence": checkpoint["budget"]["max_faults"],
        "measured_phase_execution_seconds": round(603.381 + new_seconds, 3),
        "elapsed_seconds": round(975.095 + new_seconds, 3),
        "timing_note": "Original 975.095 s wall campaign plus separately resumed new trial wall time; gap between sessions excluded. Per-trial seconds are in coverage-io-checkpoint.json.",
        "evidence": {**result.get("evidence", {}),
                     "coverage_io_checkpoint": "coverage-io-checkpoint.json",
                     "discovery_validation": "discovery-validation-healthy/validation.json",
                     "trial_table": "coverage-io-trials.csv",
                     "new_trials": "coverage-io-new/"},
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stop_reason": ("Exact target exception candidate requires source review and replay."
                        if has_candidate else
                        "Reached 64-trial budget; the final eight trials produced no new HDFS production method/branch outcome or I/O family, so the conditional 128-trial extension is not triggered."
                        if budget_reached and not recent_novelty else
                        "Recent production coverage or I/O novelty meets the conditional 128-trial extension rule."
                        if budget_reached else
                        "No exact target exception yet; 64-trial budget in progress."),
    })
    if status == "quality_complete":
        result["completed_at_utc"] = new[-1]["completed_at_utc"]
    return result


def persist(checkpoint: dict) -> dict:
    feedback.atomic_json(CHECKPOINT, checkpoint)
    result = case_record(checkpoint)
    feedback.atomic_json(RESULT, result)
    # The existing node0 checklist watcher atomically renders checklist102
    # from each case result.json within five seconds of this update.
    return result


def main() -> None:
    checkpoint = json.loads(CHECKPOINT.read_text())
    if len(checkpoint["legacy_completed"]) != 40:
        raise RuntimeError("the 40 legacy trials must be audited first")
    if checkpoint["budget"] != {"max_trials": 64, "max_faults": 6}:
        raise RuntimeError("unexpected continuation budget")
    for row in checkpoint["legacy_completed"] + checkpoint["continuation_completed"][:8]:
        row.setdefault("runtime_trace_mode", "region-state")
        row.setdefault("region_skeletons_loaded", True)
        row.setdefault("instrumentation_artifact", "graphchecker_preweave_state_door")
    NEW.mkdir(parents=True, exist_ok=True)
    persist(checkpoint)
    while len(checkpoint["legacy_completed"]) + len(checkpoint["continuation_completed"]) < checkpoint["budget"]["max_trials"]:
        number = 41 + len(checkpoint["continuation_completed"])
        existing_plan = NEW / row_name(number) / "fault-trial.json"
        if existing_plan.is_file():
            raw = json.loads(existing_plan.read_text())
            sequence = [{key: value for key, value in point.items()
                         if key not in {"faultId", "value"}}
                        for point in raw["faults"]]
            reason = "resumed previously planned selector sequence"
        else:
            sequence, reason = plan(checkpoint, number)
        if len(sequence) > checkpoint["budget"]["max_faults"]:
            raise RuntimeError("mutation exceeds configured fault cap")
        local, trace, manifest, elapsed = get_trial_artifacts(number, sequence)
        row_path = local / "trial-result.json"
        row = json.loads(row_path.read_text()) if row_path.is_file() else \
            summarize_trial(checkpoint, number, sequence, reason, local, trace,
                            manifest, elapsed)
        checkpoint["continuation_completed"].append(row)
        result = persist(checkpoint)
        print(json.dumps({key: row[key] for key in (
            "trial", "status", "strict_injection", "target_guard_after_last_fault",
            "new_production_coverage_vs_prior", "new_io_families_vs_prior", "seconds")}),
            flush=True)
        if row["bug_mark"] == "candidate":
            print("Exact exception candidate: stop for source review and same-selector replay",
                  flush=True)
            break
    print("campaign checkpoint count", result["fault_trials"], flush=True)


if __name__ == "__main__":
    main()
