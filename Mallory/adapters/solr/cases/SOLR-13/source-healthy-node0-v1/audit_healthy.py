#!/usr/bin/env python3
"""Audit a fresh SOLR-13 healthy run without promoting it to fault testing."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
ORIGINAL = HERE.parent / "source-admission-v1"
RELEASE = ROOT / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

CHECK = "org.apache.solr.cloud.api.collections.RoutedAlias#doSynchronous(Lorg/apache/solr/update/AddUpdateCommand;Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;Lorg/apache/solr/core/CoreContainer;)Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;@348:branch:1"
THROW = "org.apache.solr.cloud.api.collections.RoutedAlias#doSynchronous(Lorg/apache/solr/update/AddUpdateCommand;Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;Lorg/apache/solr/core/CoreContainer;)Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;@350:throw:1"
DOOR = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#applyModificationAndExportToZk(Ljava/util/function/UnaryOperator;)V@2259:door:1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def attest(output: Path) -> dict:
    summary = read(output / "result.json")
    trial_root = output / "trials/r0000"
    trial = read(trial_root / "result.json")
    plan = read(trial_root / "plan.json")
    pilot = read(trial_root / "pilot-result.json")
    source_manifest = read(ORIGINAL / "manifest.json")
    catalog = [json.loads(line) for line in (trial_root / "sites.jsonl").read_text().splitlines()
               if line]
    with gzip.open(trial_root / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream]
    checks = [e for e in events if e.get("type") == "TARGET_CHECK" and e.get("site") == CHECK]
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and e.get("site") == DOOR]
    throws = [e for e in events if e.get("type") == "TARGET_THROW" and e.get("site") == THROW]
    target_catalog = [e for e in catalog if e.get("type") == "TARGET_CHECK" and e.get("site") == CHECK]
    door_catalog = [e for e in catalog if e.get("type") == "DOOR_OBSERVED" and e.get("site") == DOOR]
    junit = trial.get("junit_validation") or {}
    validation = trial.get("site_catalog_validation") or {}
    feedback = trial.get("feedback") or {}
    reasons = []
    if (summary.get("status") != "calibration_complete" or
            summary.get("calibration_only") is not True or
            summary.get("fault_trials_completed") != 0 or
            summary.get("runtime_attestation", {}).get("valid") is not True):
        reasons.append("not_terminal_fault_free_healthy_calibration")
    if (junit.get("status") != "passed" or junit.get("tests") != 1 or
            junit.get("failures") != 0 or junit.get("errors") != 0 or
            junit.get("skipped") != 0):
        reasons.append("original_cluster_junit_not_1_0_0")
    if (trial.get("plan") != [] or plan.get("faults") != [] or trial.get("timed_out") is not False or
            any(e.get("type") in ("FAULT_MATCHED", "FAULT_APPLIED") for e in events)):
        reasons.append("healthy_trial_has_fault_or_timeout")
    if (feedback.get("status") != "observed" or feedback.get("target_reached") is not True or
            feedback.get("target_threw") is not False or feedback.get("trace_truncated") is not False or
            throws):
        reasons.append("target_or_trace_status_invalid")
    if (validation.get("valid") is not True or validation.get("class_hash_match") is not True or
            len(target_catalog) != 1 or len(door_catalog) != 1 or
            not all(e.get("node") and re.fullmatch(r"node[1-9][0-9]*", e["node"])
                    for e in checks + doors)):
        reasons.append("exact_catalog_or_named_actor_missing")
    target_hash = source_manifest["compiled_classes"]["solr-core-8.11.4.jar"][
        "org/apache/solr/cloud/api/collections/RoutedAlias.class"]
    door_hash = source_manifest["compiled_classes"]["solr-solrj-8.11.4.jar"][
        "org/apache/solr/common/cloud/ZkStateReader$AliasesManager.class"]
    if (not target_catalog or target_catalog[0].get("bytecode_sha256") != target_hash or
            not door_catalog or door_catalog[0].get("bytecode_sha256") != door_hash or
            target_catalog[0].get("class_loader_id") != door_catalog[0].get("class_loader_id")):
        reasons.append("loaded_target_or_door_bytecode_mismatch")
    if (not checks or not doors or not all(e.get("outcome") == "TAKEN" for e in checks) or
            not all(e.get("exception_class") ==
                    "org.apache.zookeeper.KeeperException$BadVersionException" for e in doors) or
            pilot.get("target_check_count") != len(checks) or
            pilot.get("target_throw_count") != 0):
        reasons.append("exact_target_or_typed_door_not_observed")
    trace_bytes = (trial_root / "events.jsonl.gz").read_bytes()
    if (trial.get("events_evidence", {}).get("gzip_sha256") !=
            hashlib.sha256(trace_bytes).hexdigest() or
            trial.get("events_sha256") !=
            hashlib.sha256(gzip.decompress(trace_bytes)).hexdigest() or
            trial.get("site_catalog_sha256") != sha(trial_root / "sites.jsonl")):
        reasons.append("raw_trace_or_catalog_digest_mismatch")
    ids = [e["id"] for e in events if e.get("id")]
    if len(ids) != len(set(ids)):
        reasons.append("duplicate_event_ids")
    paths = []
    if checks and doors and not reasons:
        graph = OccurrenceGraph(events, reject_coarse_roots=True)
        for door in doors:
            for check in checks:
                if door["seq"] >= check["seq"]:
                    continue
                path = graph.event_path(door, check, require_edge=True)
                if path is not None:
                    paths.append({"door_event_id": door["id"],
                                  "target_event_id": check["id"],
                                  "door_node": door["node"],
                                  "target_node": check["node"]})
    return {"schema_version": 1, "case_id": "SOLR-13",
            "variant": "source-healthy-node0-v1",
            "status": "passed" if not reasons else "failed", "reasons": reasons,
            "target_check_site": CHECK, "target_throw_site": THROW, "typed_io_site": DOOR,
            "target_check_count": len(checks), "target_throw_count": len(throws),
            "typed_door_count": len(doors), "target_actors": sorted({e.get("node") for e in checks}),
            "typed_door_actors": sorted({e.get("node") for e in doors}),
            "observed_event_time_paths": paths,
            "full_campaign_admitted": False,
            "note": "A typed alias write and target check are not causally paired by temporal proximity alone."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    receipt = attest(args.output)
    (args.output / "source-healthy-node0-gate.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
