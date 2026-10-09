#!/usr/bin/env python3
"""Admit only a fresh, named, typed, event-time HBASE-31 healthy trace."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

from preflight import HERE, REPO, check, main as preflight, require, sha


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binding-v2", action="store_true")
    args = parser.parse_args()
    if args.binding_v2:
        from preflight_v2 import main as preflight_v2
        preflight_v2(allow_detached_source=True)
    else:
        preflight(allow_detached_source=True)
    admission = load(HERE / "admission.json")
    v2 = load(HERE / "admission-v2.json") if args.binding_v2 else None
    campaign = args.campaign.resolve()
    require(args.out.resolve().parent == campaign, "verdict must be in campaign directory")
    release = REPO / "Mallory/dispatch/releases" / admission["core_release_id"]
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(release))
    import Mallory.core.graph as graph_module

    require(Path(graph_module.__file__).resolve().is_relative_to(release.resolve()),
            "graph did not load from pinned core")
    core = load(release / "manifest.json")
    check(Path(graph_module.__file__), core["files"]["Mallory/core/graph.py"])

    config_path = campaign / "config.json"
    expected_config = (HERE / "HBASE-31.dispatch-binding-v2.healthy.json" if v2 else
                       HERE.parent / "HBASE-31-37-typed-door-v1" / "HBASE-31.healthy.json")
    check(config_path, v2["config_sha256"] if v2 else admission["campaign_config_sha256"])
    require(load(config_path) == load(expected_config),
            "campaign configuration changed from the staged version")
    summary_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    trial = campaign / "trials/r0000"
    summary, audit, result = load(summary_path), load(audit_path), load(trial / "result.json")
    require(summary["case_id"] == result["case_id"] == audit["case_id"] == "HBASE-31" and
            summary["calibration_only"] is True and
            summary["status"] == "calibration_complete" and
            summary["fault_trials_completed"] == 0 and
            summary["healthy_seed_valid"] is True, "healthy campaign incomplete")
    require(summary["healthy_junit_validation"]["status"] == "passed" and
            result["junit_validation"]["status"] == "passed" and
            result["junit_validation"]["tests"] == 1 and
            result["junit_validation"]["succeeded"] == 1 and
            result["junit_validation"]["failures"] == 0 and
            result["junit_validation"]["errors"] == 0, "exact selected JUnit failed")
    attestation = summary["runtime_attestation"]
    catalog = result["site_catalog_validation"]
    require(attestation["valid"] is True and not attestation["reasons"] and
            set(attestation["bound_nodes"]) <= {"rs0", "rs1"} and
            attestation["bound_nodes"] and
            attestation["observed_target_class_sha256"] ==
            admission["compiled_target_class_sha256"] and
            len(attestation["target_class_loader_ids"]) == 1 and
            catalog["valid"] is True and catalog["class_hash_match"] is True and
            catalog["observed_target_class_sha256"] ==
            admission["compiled_target_class_sha256"] and
            len(catalog["target_class_loader_ids"]) == 1,
            "loaded target class or actor attestation failed")
    feedback = result["feedback"]
    require(feedback["status"] == "observed" and feedback["target_reached"] is True and
            feedback["target_threw"] is False and
            feedback["require_event_time_paths"] is True and
            feedback["reject_coarse_roots"] is True and
            not feedback["target_identity_gaps"], "exact target was not cleanly reached")
    require(audit["report_gate_passed"] is True and
            audit["healthy_closure_proven"] is True and
            audit["healthy_target_nonthrowing"] is True and
            audit["archive_integrity_valid"] is True and
            audit["target_claims_reverified"] is True and
            audit["guidance_consistent"] is True and
            audit["require_event_time_paths"] is True and
            audit["reject_coarse_roots"] is True and
            audit["allow_local_timeline_doors"] is False and
            audit["healthy_observed_path_doors"] > 0 and
            audit["trial_count"] == 1 and
            audit["campaign_result_sha256"] == sha(summary_path),
            "strict offline causal audit failed")

    raw = gzip.decompress((trial / "events.jsonl.gz").read_bytes())
    require(hashlib.sha256(raw).hexdigest() == result["events_sha256"],
            "raw trace hash mismatch")
    events = [json.loads(line) for line in raw.splitlines() if line]
    by_id = {event["id"]: event for event in events}
    require(len(by_id) == len(events) and
            not any(event["type"] in {"FAULT_MATCHED", "FAULT_APPLIED"} for event in events),
            "healthy trace has duplicate IDs or a fault")
    site_rows = [json.loads(line) for line in (trial / "sites.jsonl").read_text().splitlines()]
    door_rows = [row for row in site_rows if row.get("type") == "DOOR_OBSERVED"]
    require(len(door_rows) == 1 and door_rows[0]["site"] == admission["typed_door"] and
            door_rows[0]["bytecode_sha256"] == admission["compiled_dispatcher_class_sha256"],
            "runtime instrumented door does not match pinned dispatcher")
    graph = graph_module.OccurrenceGraph(events, reject_coarse_roots=True)
    witness = None
    for sample in audit["healthy_event_time_path_sample"]:
        door = by_id[sample["door_event_id"]]
        target = by_id[sample["target_check_event_id"]]
        if not (door["type"] == "DOOR_OBSERVED" and
                door["site"] == admission["typed_door"] and door["node"] == "master0" and
                target["type"] == "TARGET_CHECK" and
                target["site"] == admission["target_check"] and
                target["node"] in {"rs0", "rs1"} and
                target["outcome"] == "TAKEN" and
                isinstance(door.get("thread_id"), int) and
                isinstance(target.get("thread_id"), int) and
                door["seq"] == sample["door_seq"] < sample["target_check_seq"] ==
                target["seq"]):
            continue
        path = graph.event_path(door, target, require_edge=True)
        if path is None:
            continue
        edges = [{"producer_event": edge.producer_event,
                  "consumer_event": edge.consumer_event, "kind": edge.kind} for edge in path]
        if edges != sample["edges"]:
            continue
        if not all(edge.certainty == "observed" and
                   door["seq"] < by_id[edge.producer_event]["seq"] <
                   by_id[edge.consumer_event]["seq"] < target["seq"] for edge in path):
            continue
        if not any(edge.kind == "rpc" and
                   by_id[edge.producer_event]["node"] == "master0" and
                   by_id[edge.consumer_event]["node"] in {"rs0", "rs1"} for edge in path):
            continue
        witness = {"door_event_id": door["id"], "door_node": door["node"],
                   "door_seq": door["seq"], "target_check_event_id": target["id"],
                   "target_node": target["node"], "target_check_seq": target["seq"],
                   "observed_edges": edges}
        break
    require(witness is not None, "no named typed RPC-to-guard event-time path")
    require(not any(event["type"] == "TARGET_THROW" and
                    event.get("site") == admission["target_throw"] for event in events),
            "healthy target threw")
    verdict = {"schema_version": 1, "case_id": "HBASE-31",
               "status": "healthy_typed_path_admitted_fault_still_blocked",
               "binding_stage": "v2" if v2 else "v1",
               "config_sha256": sha(config_path), "result_sha256": sha(summary_path),
               "audit_sha256": sha(audit_path),
               "trace_gzip_sha256": sha(trial / "events.jsonl.gz"),
               "adapter_jar_sha256": admission["adapter_jar_sha256"],
               "binding_overlay_jar_sha256": v2["overlay_jar_sha256"] if v2 else None,
               "target_class_sha256": admission["compiled_target_class_sha256"],
               "witness": witness, "fault_admission_blocked": True,
               "bug_claim_blocked_without_replay": True}
    args.out.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    print(f"PASS HBASE-31 healthy: {witness['door_event_id']} -> "
          f"{witness['target_check_event_id']} on {witness['target_node']}")


if __name__ == "__main__":
    main()
