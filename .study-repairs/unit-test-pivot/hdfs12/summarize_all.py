"""Rebuild the HDFS-12 checklist row from original JUnit trace artifacts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from summarize_trials import GUARD, HERE, RESULT, branch_pairs, rows

ROOT = HERE.parents[2]
SERVER = HERE / "server-door"
PRODUCER = HERE / "producer-heartbeat-door"
TARGET_REGION = "REGION.61e62f41-34c6-3a5d-b610-b639dc3f4838"


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def entry_methods(trace: Path) -> set[str]:
    return {r["method"] for r in rows(trace) if r.get("event") == "METHOD_ENTER"}


def family(campaign: str, name: str) -> str:
    if campaign == "server_sasl":
        return "SASL_SERVER_READ"
    if name.startswith("ipc-first-key-update-response"):
        return "HADOOP_IPC_RESPONSE"
    if name.startswith("ipc-first-key-update-request"):
        return "HADOOP_IPC_REQUEST"
    return "HDFS_HEARTBEAT_RESPONSE_LOST"


def summarize_trial(path: Path, campaign: str) -> dict:
    manifest = json.loads((path / "manifest.json").read_text())
    trace = path / "trace/runtime_trace.jsonl"
    trace_rows = list(rows(trace))
    summary, = [r for r in trace_rows if r.get("event") == "FAULT_TRIAL_SUMMARY"]
    fatal = json.loads((path / "trace/summary.json").read_text())
    return {
        "sequence": path.name,
        "campaign": campaign,
        "fault_family": family(campaign, path.name),
        "elapsed_seconds": round(
            manifest["runtime"]["seconds"] + manifest["aggregate"]["seconds"], 3),
        "junit_exit": manifest["runtime"]["exit"],
        "requested_faults": summary["requested"],
        "matched_faults": summary["matched"],
        "applied_faults": summary["applied"],
        "target_after_fault": summary["targetAfterFault"],
        "target_guard_outcomes": [
            r["outcome"] for r in trace_rows
            if r.get("event") == "BRANCH" and r.get("siteId") == GUARD],
        "target_fatal_exceptions": len(
            fatal["targets"]["HDFS-12"]["fatalOccurrences"]),
        "fault_marker": summary["marker"],
        "fault_site": summary["siteId"],
        "source_key": summary["sourceKey"],
        "evidence": relative(trace),
    }


def campaign(name: str, healthy: list[Path], roots: list[Path]) -> tuple[dict, list[dict]]:
    baseline_branches: set[tuple[str, bool]] = set()
    baseline_entries: set[str] = set()
    healthy_seconds = 0.0
    for path in healthy:
        manifest = json.loads((path / "manifest.json").read_text())
        healthy_seconds += (
            manifest["runtime"]["seconds"] + manifest["aggregate"]["seconds"])
        trace = path / "trace/runtime_trace.jsonl"
        baseline_branches.update(branch_pairs(trace))
        baseline_entries.update(entry_methods(trace))
    all_branches = set(baseline_branches)
    all_entries = set(baseline_entries)
    trials = []
    for root in roots:
        for path in sorted(root.iterdir()):
            if not path.is_dir() or path.name == "healthy":
                continue
            trial = summarize_trial(path, name)
            trials.append(trial)
            if trial["target_after_fault"]:
                trace = path / "trace/runtime_trace.jsonl"
                all_branches.update(branch_pairs(trace))
                all_entries.update(entry_methods(trace))
    return {
        "healthy_replays": len(healthy),
        "healthy_junit_and_aggregate_seconds": round(healthy_seconds, 3),
        "fault_trials": len(trials),
        "fault_jvms_and_aggregates_seconds": round(
            sum(r["elapsed_seconds"] for r in trials), 3),
        "retained_target_trials": sum(r["target_after_fault"] for r in trials),
        "new_branch_pairs": len(all_branches - baseline_branches),
        "new_method_entries": len(all_entries - baseline_entries),
    }, trials


def closure_metrics() -> tuple[int, int, int]:
    spec = importlib.util.spec_from_file_location(
        "closure_fuzzer", HERE.parent / "core-fuzzer/fuzzer.py")
    fuzzer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fuzzer)
    trace = PRODUCER / "record-start/healthy/trace"
    closure = fuzzer.read_closure(
        trace / "concolic_region_plan.jsonl",
        "<org.apache.hadoop.hdfs.server.datanode.DataXceiver: void run()>",
        target_region_id=TARGET_REGION)
    if closure["blocking_gaps"] or len(closure["target_addresses"]) != 4:
        raise ValueError("healthy target identity gate failed")
    selected = [
        r for r in rows(trace / "runtime_trace.jsonl")
        if r.get("event") == "FAULT_POINT_OBSERVED"
        and r.get("occurrenceAddress") in closure["addresses"]]
    return len(closure["addresses"]), len(selected), len(closure["blocking_gaps"])


def main() -> None:
    result = json.loads(RESULT.read_text())
    server, server_trials = campaign(
        "server_sasl", [SERVER / "record/healthy"], [SERVER / "record"])
    producer, producer_trials = campaign(
        "key_update",
        [PRODUCER / "record-start/healthy", PRODUCER / "record-replay/healthy"],
        [PRODUCER / "trials", PRODUCER / "trials-retry"])
    trials = server_trials + producer_trials
    closure_addresses, closure_points, blocking = closure_metrics()
    server_build = json.loads((SERVER / "manifest.json").read_text())
    producer_build = json.loads((PRODUCER / "manifest.json").read_text())
    server_build_seconds = sum(
        server_build[p]["seconds"] for p in ("seed", "weave"))
    producer_build_seconds = sum(
        producer_build[p]["seconds"] for p in ("seed", "lineage", "weave"))
    if any(r["target_fatal_exceptions"] or False in r["target_guard_outcomes"]
           for r in trials):
        raise ValueError("Target exception appeared; source review required")
    elapsed = sum((
        server_build_seconds, producer_build_seconds,
        server["healthy_junit_and_aggregate_seconds"],
        server["fault_jvms_and_aggregates_seconds"],
        producer["healthy_junit_and_aggregate_seconds"],
        producer["fault_jvms_and_aggregates_seconds"]))
    result.update({
        "status": "target_reached_pending_exact_key_state_edge",
        "tmux_session": "hdfs12-case",
        "checkpoint": ".study-repairs/unit-test-pivot/cases/HDFS-12/result.json",
        "cluster_test": (
            "org.apache.hadoop.hdfs.TestEncryptedTransfer#testLongLivedClient[0] "
            "(key rotation), plus testEncryptedReadDefaultAlgorithmCipherSuite[0] "
            "(SASL read)"),
        "cluster_nodes": (
            "Original JUnit MiniDFSCluster.Builder(conf) default: one NameNode "
            "and one DataNode; testLongLivedClient restarts its encrypted cluster"),
        "target_reached": True,
        "healthy_target_guard_hits": 4,
        "healthy_target_branch_outcomes": [True] * 4,
        "healthy_target_fatal": False,
        "healthy_target_occurrence_count": 4,
        "target_region_id": TARGET_REGION,
        "graph_gap": (
            "Four distinct DataXceiver target occurrences have hdfs/datanode/0#epoch0 "
            "identity and no BLOCKING gaps. Heartbeat, BPOfferService key imports, "
            "RPC, and SASL SERVER_READ are target-closure members. Shared Map state "
            "membership is CANDIDATE/SHARED_LOCATION_DEMAND_V1 with "
            "edgeEvidence=UNAVAILABLE; exact Map.put-to-Map.get read-from and "
            "NameNode command payload identity remain unproved."),
        "observed_fault_points": json.loads((
            PRODUCER / "record-start/healthy/manifest.json").read_text()
        )["trace"]["observedFaultPoints"],
        "healthy_closure_addresses": closure_addresses,
        "healthy_closure_fault_events": closure_points,
        "healthy_closure_blocking_gaps": blocking,
        "healthy_target_closure_server_read_fault_selectors": 4,
        "fault_trials": len(trials),
        "strict_injections": sum(r["applied_faults"] for r in trials),
        "fully_applied_trials": sum(
            r["requested_faults"] == r["matched_faults"] == r["applied_faults"]
            for r in trials),
        "target_after_fault": sum(r["target_after_fault"] for r in trials),
        "lost_target_trials": sum(not r["target_after_fault"] for r in trials),
        "target_exception_count": 0,
        "target_fatal_branch_count": 0,
        "coverage_gain": {
            "server_sasl_new_branch_pairs": server["new_branch_pairs"],
            "key_update_new_branch_pairs": producer["new_branch_pairs"],
            "server_sasl_new_method_entries": server["new_method_entries"],
            "key_update_new_method_entries": producer["new_method_entries"]},
        "coverage_gain_definition": (
            "Distinct instrumented BRANCH (site,outcome) pairs in target-retaining "
            "fault runs versus each campaign's healthy trace union. Different "
            "static scopes are reported separately; timing effects may contribute."),
        "bug_mark": "none",
        "elapsed_seconds": round(elapsed, 3),
        "elapsed_breakdown_seconds": {
            "server_sasl_static_and_weave": round(server_build_seconds, 3),
            "server_sasl_healthy": server["healthy_junit_and_aggregate_seconds"],
            "server_sasl_fault_trials": server["fault_jvms_and_aggregates_seconds"],
            "key_update_static_lineage_and_weave": round(producer_build_seconds, 3),
            "key_update_two_healthy_replays":
                producer["healthy_junit_and_aggregate_seconds"],
            "key_update_fault_trials":
                producer["fault_jvms_and_aggregates_seconds"]},
        "timing_note": (
            "Sum of measured process durations in the two final original-JUnit "
            "campaigns; earlier feasibility probes and source review excluded."),
        "campaigns": {"server_sasl": server, "key_update": producer},
        "status_scope": (
            "Bounded HDFS-12 fault subcampaign complete: original encrypted-read and "
            "short-rotation JUnit methods, stable closure identity, SASL read, "
            "heartbeat response loss through five faults, direct Hadoop IPC "
            "request/response exceptions; no target InvalidToken observed."),
        "stop_reason": (
            "Equivalent fault families covered for this subcampaign. Six "
            "heartbeat response losses removed the DataNode/target, so that "
            "case is excluded by the target-after-fault oracle. Checklist "
            "remains pending exact producer-to-target key-state identity."),
        "remaining_work": (
            "Optional precision work: capture exact NameNode KeyUpdateCommand "
            "payload and DataNode Map.put/Map.get read-from edge; CANDIDATE "
            "closure edges were not promoted to EXACT."),
        "trial_results": trials,
        "evidence": "; ".join(relative(p) for p in (
            SERVER / "record",
            PRODUCER / "record-start/healthy/trace/concolic_region_plan.jsonl",
            PRODUCER / "record-replay/healthy/trace/concolic_region_plan.jsonl",
            PRODUCER / "trial-plans/manifest.json",
            PRODUCER / "trials", PRODUCER / "trials-retry")),
    })
    RESULT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in (
        "status", "fault_trials", "strict_injections", "fully_applied_trials",
        "target_after_fault", "lost_target_trials", "target_exception_count",
        "coverage_gain", "elapsed_seconds", "bug_mark")}, indent=2))


if __name__ == "__main__":
    main()
