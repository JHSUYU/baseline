"""Audit and dispatch the 102 original checks using native GraphChecker receipts.

Legacy Mallory/graphchecker_port checkpoints are deliberately never read here.
The native campaign owns its own trial lock and resume logic; this module only
assigns cases, audits closed receipts, and refuses to replay terminal cases.
"""

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import re
import shlex
import socket
import subprocess
from pathlib import Path
from typing import Any

from Mallory.native_graphchecker_campaign import campaign as native
from Mallory.native_graphchecker_feedback.feedback import _session_digest, delta
from Mallory.native_graphchecker_feedback.region_state_graph import (
    _closed_inputs, _fatal_unplanned, delta_region_state,
    summarize_region_state,
)
from Mallory.instrumentation.graphchecker_port.native_original_weave import (
    class_tree_digest, dependency_digests, file_tree_digest,
)

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
DEFAULT_INVENTORY = BASE / "Mallory/cases/inventory.json"
DEFAULT_OWNERSHIP = BASE / "Mallory/dispatch/shards/ownership.json"
CASE_ID = re.compile(r"^(HDFS|HBASE|SOLR|ZOOKEEPER)-[0-9]{2}$")
HEX_SHA = re.compile(r"^[0-9a-f]{64}$")
NATIVE_METHOD = "original-graphchecker-corpus-closureplanner"
PREP_MODE = "original_graphchecker_native_preparation"
FINISHED = {"complete_trial_budget", "complete_time_budget", "complete_queue"}
FIELDS = (
    "case_id", "system", "system_version", "owner", "terminal_disposition",
    "native_tested_complete", "target_source_path", "target_class",
    "target_method", "target_line", "target_check_code", "target_exception",
    "junit_workload", "native_config", "native_target_site", "status",
    "fault_trials", "strict_fault_trials", "target_retained_fault_trials",
    "strict_target_retained_fault_trials", "target_throw_trials",
    "candidate_trials", "elapsed_seconds", "elapsed_basis", "evidence",
    "reason",
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX_SHA.fullmatch(value):
        raise ValueError(f"invalid {label} SHA-256")
    return value


def _inside(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe native result path: {relative}")
    return root / path


def _same_checkpoint_summary(checkpoint: dict, summary: dict) -> None:
    expected = {key: value for key, value in checkpoint.items()
                if key not in ("queue", "seen_plan_keys", "active")}
    if summary != expected:
        raise ValueError("native summary differs from terminal checkpoint")


def _native_case_files(item: dict, config_root: Path,
                       state_root: Path) -> tuple[Path, Path]:
    """Resolve an explicit, pinned inventory-to-native campaign binding."""
    case_id = item["case_id"]
    entry = config_root / f"{case_id}.json"
    if not entry.is_file():
        return entry, state_root / case_id
    document = _object(entry)
    if document.get("mode") != "native_region_state_case_binding":
        return entry, state_root / case_id
    native_id = document.get("native_case_id")
    config = Path(document.get("native_config_path", ""))
    root = Path(document.get("native_state_path", ""))
    row_sha = hashlib.sha256(json.dumps(
        item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (document.get("schema_version") != 1 or
            document.get("inventory_case_id") != case_id or
            document.get("inventory_row_sha256") != row_sha or
            not isinstance(native_id, str) or
            not native_id.startswith(case_id + "-native-") or
            not config.is_absolute() or not root.is_absolute() or
            config.is_symlink() or root.is_symlink() or
            _sha(config) != document.get("native_config_sha256") or
            _object(config).get("case_id") != native_id or
            _object(config).get("runner", {}).get("mode") != "region_state"):
        raise ValueError("native REGION_STATE case binding changed identity or inputs")
    return config, root


def verify_preparation_receipt(item: dict, config_file: Path,
                               case_root: Path) -> dict:
    """Verify the one-time static/recording/concolic preparation receipt."""
    case_id = item["case_id"]
    receipt_file = config_file.with_suffix(".prep.json")
    if config_file.is_symlink() or receipt_file.is_symlink():
        raise ValueError("native preparation uses a symlink")
    receipt = _object(receipt_file)
    if (receipt.get("schema_version") != 1 or receipt.get("mode") != PREP_MODE or
            receipt.get("case_id") != case_id or
            receipt.get("inventory_row_sha256") != hashlib.sha256(json.dumps(
                item, sort_keys=True, separators=(",", ":")).encode()).hexdigest() or
            receipt.get("config_sha256") != _sha(config_file) or
            receipt.get("original_cluster_junit_verified") is not True):
        raise ValueError("native preparation receipt/config identity mismatch")
    prep_state = _object(case_root / "preparation/state.json")
    if (prep_state.get("status") != "complete" or
            prep_state.get("cache_key") != receipt.get("cache_key") or
            hashlib.sha256(json.dumps(receipt, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
            != prep_state.get("receipt_sha256")):
        raise ValueError("native preparation cache identity changed")
    for path_key, sha_key in (("recipe_file_path", "recipe_file_sha256"),
                              ("engine_jar_path", "engine_jar_sha256")):
        path = Path(receipt.get(path_key, ""))
        if not path.is_file() or path.is_symlink() or _sha(path) != receipt.get(sha_key):
            raise ValueError(f"native preparation input changed: {path_key}")
    pins = receipt.get("input_pins")
    if not isinstance(pins, list) or not pins:
        raise ValueError("native preparation has no pinned inputs")
    for pin in pins:
        if not isinstance(pin, dict) or set(pin) != {"path", "sha256", "kind"}:
            raise ValueError("invalid native preparation input pin")
        path = Path(pin["path"])
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("native preparation input uses unpinned path")
        kind = pin["kind"]
        if kind == "class_tree":
            actual = class_tree_digest(path)
        elif kind == "tree":
            actual = file_tree_digest(path)
        elif kind == "file_or_tree":
            actual = _sha(path) if path.is_file() else file_tree_digest(path)
        elif kind == "file":
            actual = _sha(path)
        else:
            raise ValueError("invalid native preparation input kind")
        if actual != pin["sha256"]:
            raise ValueError(f"native preparation source/classpath/mapping changed: {path}")
    prep_root = (case_root / "preparation").resolve()
    for path_key, sha_key in (
        ("request_path", "request_sha256"),
        ("recipe_snapshot_path", "recipe_snapshot_sha256"),
        ("adapter_proof_path", "adapter_proof_sha256"),
        ("source_config_path", "config_sha256"),
        ("static_scope_receipt_path", "static_scope_receipt_sha256"),
        ("recording_weave_receipt_path", "recording_weave_receipt_sha256"),
        ("target_occurrence_receipt_path", "target_occurrence_receipt_sha256"),
    ):
        path = Path(receipt.get(path_key, "")).resolve(strict=True)
        if not path.is_relative_to(prep_root) or path.is_symlink() or (
                _sha(path) != receipt.get(sha_key)):
            raise ValueError(f"native preparation artifact changed: {path_key}")
    request = _object(Path(receipt["request_path"]))
    proof = _object(Path(receipt["adapter_proof_path"]))
    canonical_sha = hashlib.sha256(json.dumps(request, sort_keys=True,
                                              separators=(",", ":")).encode()).hexdigest()
    target, workload = item["target"], item["workload"]
    if (request.get("mode") != PREP_MODE or request.get("case_id") != case_id or
            request.get("inventory_row_sha256") != receipt["inventory_row_sha256"] or
            request.get("target", {}).get("site_id") != target["site_id"] or
            request.get("original_junit", {}).get("class") != workload.get("test_class") or
            request.get("original_junit", {}).get("method") != workload.get("test_method") or
            proof.get("mode") != "original_graphchecker_native_adapter" or
            proof.get("case_id") != case_id or proof.get("request_sha256") != canonical_sha or
            proof.get("original_cluster_junit_verified") is not True):
        raise ValueError("native preparation request/proof differs from inventory")
    admission = case_root / "recording-admission.json"
    if (not admission.is_file() or
            _sha(admission) != receipt.get("recording_admission_sha256")):
        raise ValueError("native recording-derived admission changed")
    config = _object(config_file)
    weave = _object(Path(config["native_weave_config"]))
    native_receipt_path = (Path(weave["output_classes"]) /
                           "native-original-weave-receipt.json")
    if _sha(native_receipt_path) != receipt.get("native_weave_receipt_sha256"):
        raise ValueError("native concolic weave receipt changed")
    static = _object(Path(receipt["static_scope_receipt_path"]))
    recording = _object(Path(receipt["recording_weave_receipt_path"]))
    concolic = _object(native_receipt_path)
    preimage = static.get("process_classes_sha256")
    if (not isinstance(preimage, str) or not HEX_SHA.fullmatch(preimage) or
            recording.get("input_classes_sha256") != preimage or
            concolic.get("input_classes_sha256") != preimage):
        raise ValueError("native static/recording/concolic class preimages differ")
    return receipt


def _verify_region_weave(config_file: Path) -> dict:
    """Check the immutable source-built REGION_STATE weave without rerunning it."""
    config = _object(config_file)
    weave_file = Path(config["native_weave_config"])
    weave = _object(weave_file)
    output = Path(weave["output_classes"])
    receipt = _object(output / "native-original-weave-receipt.json")
    engine = Path(receipt["engine_jar"])
    engine_root = engine.parent.parent
    engine_receipt = _object(engine.parent / "native-original-engine-receipt.json")
    sources = [engine_root / "pom.xml", engine_root / "UPSTREAM_SOURCES.json"]
    sources.extend(sorted((engine_root / "src/main/java").rglob("*.java")))
    sources.extend(sorted((engine_root / "vendor/src/main/java").rglob("*.java")))
    sources.extend(sorted((engine_root / "vendor/src/main/resources").rglob("*")))
    sources.extend(sorted((engine_root / "src/main/resources").rglob("*")))
    source_hash = hashlib.sha256()
    for path in sources:
        if path.is_file():
            source_hash.update(path.relative_to(engine_root).as_posix().encode())
            source_hash.update(b"\0")
            source_hash.update(bytes.fromhex(_sha(path)))
    if (engine_receipt.get("schema_version") != 1 or
            engine_receipt.get("upstream_revision") != receipt.get(
                "upstream_revision") or
            engine_receipt.get("source_tree_sha256") != source_hash.hexdigest() or
            engine_receipt.get("engine_jar_sha256") != _sha(engine) or
            engine_receipt.get("dependency_artifacts") != dependency_digests(
                engine_receipt["dependency_classpath"])):
        raise ValueError("source-built original REGION_STATE engine changed")
    checks = {
        "config_sha256": _sha(weave_file),
        "engine_jar_sha256": _sha(engine),
        "engine_receipt_sha256": _sha(engine.parent /
                                      "native-original-engine-receipt.json"),
        "input_classes_sha256": class_tree_digest(Path(weave["input_classes"])),
        "output_classes_sha256": class_tree_digest(output),
        "region_skeletons_sha256": _sha(Path(weave["region_skeletons"])),
        "native_fault_manifest_sha256": _sha(Path(weave["native_fault_manifest"])),
        "recording_artifacts_sha256": file_tree_digest(
            Path(weave["recording_artifacts"])),
        "dependency_classpath_sha256": hashlib.sha256(
            weave["dependency_classpath"].encode()).hexdigest(),
    }
    for field, value in checks.items():
        if receipt.get(field) != value:
            raise ValueError(f"native REGION_STATE weave pin changed: {field}")
    if (receipt.get("schema_version") != 1 or
            receipt.get("mode") !=
            "mallory_vendored_original_graphchecker_region_state_weave" or
            receipt.get("output_classes") != str(output) or
            receipt.get("input_classes") != weave["input_classes"] or
            receipt.get("dependency_artifacts") != dependency_digests(
                weave["dependency_classpath"])):
        raise ValueError("native REGION_STATE weave identity/dependencies changed")
    for optional, field in (("task_plan", "task_plan_sha256"),
                            ("communication_mappings", "communication_mappings_sha256")):
        if optional in weave and receipt.get(field) != _sha(Path(weave[optional])):
            raise ValueError(f"native REGION_STATE weave pin changed: {field}")
    return receipt


def _verified_native_summary(path: Path, iteration: Path, result: dict,
                             config: dict, admission: dict) -> dict:
    summary = _object(path)
    if (summary.get("schemaVersion") != 1 or
            summary.get("method") != NATIVE_METHOD or
            summary.get("targetSetMode") is not True or
            summary.get("targetSiteId") != config["target_site"]):
        raise ValueError("trial lacks original SessionReader/ClosurePlanner target summary")
    fingerprint = admission["recording_fingerprint"]
    for key, expected in (
        ("engineJarSha256", fingerprint["engine_jar_sha256"]),
        ("staticScopeMapSha256", fingerprint["static_scope_map_sha256"]),
        ("bridgeSourceSha256", _sha(BASE / "Mallory/native_graphchecker_feedback/NativeFeedbackMain.java")),
    ):
        if summary.get(key) != _digest(expected, key):
            raise ValueError(f"native summary provenance mismatch: {key}")
    session_sha = _session_digest(iteration)
    if (summary.get("nativeSessionSha256") != session_sha or
            result.get("native_session_sha256") != session_sha):
        raise ValueError("native session bytes changed since analysis")
    ids = summary.get("targetOccurrenceIds")
    rows = summary.get("targetRows")
    if (not isinstance(ids, list) or not ids or
            not all(isinstance(item, str) and item for item in ids) or
            not isinstance(rows, list) or not rows or
            not all(isinstance(item, dict) and item.get("reachedAnchor") is True
                    and item.get("occurrenceId") in ids for item in rows) or
            result.get("native_target_occurrence_ids") != ids):
        raise ValueError("native target occurrence/reach receipt is inconsistent")
    members = summary.get("closureMembers")
    if (not isinstance(members, list) or
            not set(ids).issubset({item.get("occurrenceId") for item in members
                                   if isinstance(item, dict)})):
        raise ValueError("target absent from original GraphChecker closure")
    if summary.get("maxTasks") != 256 and (not isinstance(summary.get("maxTasks"), int)
                                          or summary["maxTasks"] <= 0):
        raise ValueError("native closure planning limit is invalid")
    return summary


def _verified_region_summary(trial: Path, result: dict, config: dict,
                             engine: Path) -> dict | None:
    path = trial / "native-summary.json"
    if not path.is_file():
        if result.get("native_session_sha256") is not None:
            raise ValueError("REGION_STATE summary hash without summary")
        return None
    summary = _object(path)
    if (summary != _object(trial / "original-graph/summary.json") or
            result.get("native_session_sha256") != _sha(path) or
            summary.get("schemaVersion") != 1 or
            summary.get("backend") != "original_region_state" or
            summary.get("targetSiteId") != config["target_site"]):
        raise ValueError("original REGION_STATE summary identity changed")
    iteration = trial / "iteration-native"
    trace = iteration / "trace"
    recording = config["recording"]
    scope = Path(recording["static_scope_map"])
    graph = Path(recording["candidate_graph"])
    skeletons = Path(recording["region_skeletons"])
    events = iteration / "fault-events.jsonl"
    pins = _closed_inputs(trace, scope, graph, skeletons)
    lineage = _object(trial / "schedule-lineage.json")
    source = Path(lineage["source"])
    expected_sources = ([trace / "schedule.jsonl"] if lineage.get("copied") is False
                        else sorted((iteration / "sessions").glob("*/schedule.jsonl")))
    if (source not in expected_sources or
            (lineage.get("copied") is True and len(expected_sources) != 1) or
            lineage.get("source_sha256") != _sha(source) or
            lineage.get("destination_sha256") != _sha(trace / "schedule.jsonl") or
            lineage["source_sha256"] != lineage["destination_sha256"]):
        raise ValueError("original REGION_STATE schedule lineage changed")
    original = trial / "original-graph"
    if summary.get("status") == "recorded":
        recomputed = summarize_region_state(
            trace, original / "recorded/concolic_region_plan.jsonl",
            original / "target-occurrence.json", events, scope, graph,
            skeletons, config["target_site"], engine_jar=engine,
            target_throw=config["target_throw"])
        recomputed["provenance"]["extractor"] = (
            "invoked_original_resolver_and_recorder")
    elif summary.get("status") == "target_throw_unplanned":
        recomputed = _fatal_unplanned(trace, events, config["target_site"],
                                      config["target_throw"], pins, engine)
    elif summary.get("status") == "target_absent":
        recomputed = {"schemaVersion": 1, "backend": "original_region_state",
                      "targetSiteId": config["target_site"],
                      "targetReached": False, "targetThrowObserved": False,
                      "status": "target_absent", "nodeFamilies": [],
                      "edgeFamilies": [], "closureEdgeFamilies": [],
                      "branchOutcomeIds": [], "provenance": pins}
    else:
        raise ValueError("unknown original REGION_STATE summary status")
    if summary != recomputed:
        raise ValueError("original REGION_STATE graph or target receipt changed")
    ids = summary.get("targetEvidence", {}).get("targetCheckOccurrenceIds", [])
    if result.get("native_target_occurrence_ids") != ids:
        raise ValueError("REGION_STATE target occurrence IDs changed")
    return summary


def _audit_region_terminal(case_id: str, config_path: Path, root: Path,
                           checkpoint: dict, summary: dict) -> dict[str, Any]:
    config = _object(config_path)
    if (config.get("case_id") != case_id or
            checkpoint.get("schema_version") != 1 or
            checkpoint.get("case_id") != case_id or
            checkpoint.get("terminal") is not True or
            checkpoint.get("config_sha256") != _sha(config_path) or
            checkpoint.get("budget") != config.get("budget")):
        raise ValueError("native REGION_STATE checkpoint identity/config mismatch")
    _same_checkpoint_summary(checkpoint, summary)
    weave_receipt = _verify_region_weave(config_path)
    weave = _object(Path(config["native_weave_config"]))
    receipt_path = Path(weave["output_classes"]) / "native-original-weave-receipt.json"
    recording = config["recording"]
    admission = _object(root / "recording-admission.json")
    fingerprint = admission.get("recording_fingerprint", {})
    origin = admission.get("origin", {})
    expected = {
        "engine_jar_sha256": weave_receipt["engine_jar_sha256"],
        "weave_config_sha256": _sha(Path(config["native_weave_config"])),
        "weave_receipt_sha256": _sha(receipt_path),
        "static_scope_map_sha256": _sha(Path(recording["static_scope_map"])),
        "candidate_graph_sha256": _sha(Path(recording["candidate_graph"])),
        "region_skeletons_sha256": _sha(Path(recording["region_skeletons"])),
    }
    if (admission.get("schema_version") != 1 or not isinstance(origin, dict) or
            checkpoint.get("origin") != origin or
            checkpoint.get("weave_receipt_sha256") != _sha(receipt_path) or
            any(fingerprint.get(key) != value for key, value in expected.items()) or
            origin.get("recording_manifest_sha256") != _sha(
                Path(recording["trace_dir"]) / "streaming_trace_manifest.json") or
            origin.get("static_scope_map_sha256") != expected[
                "static_scope_map_sha256"] or
            origin.get("scheduler_source_sha256") != fingerprint.get(
                "scheduler_source_sha256")):
        raise ValueError("REGION_STATE admission differs from original pinned inputs")
    for field in ("recording_plan_sha256", "scheduler_source_sha256"):
        _digest(origin.get(field), field)
    for field in ("engine_jar_sha256", "trace_tree_sha256",
                  "scheduler_source_sha256"):
        _digest(fingerprint.get(field), field)
    trials = checkpoint.get("trials")
    healthy_ref = checkpoint.get("healthy")
    if (not isinstance(trials, list) or
            checkpoint.get("completed_fault_trials") != len(trials) or
            not isinstance(healthy_ref, dict) or healthy_ref.get("name") != "r0000"):
        raise ValueError("REGION_STATE healthy seed or trial count missing")
    rows = [healthy_ref, *trials]
    results = []
    for index, record in enumerate(rows):
        name = f"r{index:04d}"
        path = _inside(root, record.get("result", ""))
        if record.get("name") != name or path != root / "trials" / name / "result.json":
            raise ValueError("REGION_STATE trial order/path changed")
        result = _object(path)
        if (result.get("schema_version") != 1 or result.get("case_id") != case_id or
                result.get("runner_mode") != "region_state" or
                result.get("status") != record.get("status") or
                (index and any(result.get(key) != record.get(key) for key in
                               ("strict_injection", "native_target_retained",
                                "target_exception_triggered", "elapsed_seconds")))):
            raise ValueError("REGION_STATE trial differs from checkpoint")
        faults = result.get("faults")
        if not isinstance(faults, list) or (index == 0 and faults) or (
                index > 0 and not faults):
            raise ValueError("REGION_STATE trial fault plan missing")
        iteration = path.parent / "iteration-native"
        if _object(iteration / "fault-plan.json").get("faults") != faults:
            raise ValueError("REGION_STATE fault plan changed")
        events_path = iteration / "fault-events.jsonl"
        if result.get("fault_events_sha256") != (
                _sha(events_path) if events_path.is_file() else None):
            raise ValueError("REGION_STATE native event bytes changed")
        events = native._rows(events_path)
        strict, _ = native._strict_faults(faults, events)
        if result.get("strict_injection") is not bool(faults and strict):
            raise ValueError("REGION_STATE exact fault receipt changed")
        results.append((result, path.parent, events))
    elapsed = checkpoint.get("elapsed_seconds")
    if (not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or
            elapsed < 0 or round(sum(float(row[0]["elapsed_seconds"])
                                     for row in results), 3) != elapsed):
        raise ValueError("REGION_STATE elapsed time differs from trial receipts")
    engine = Path(weave_receipt["engine_jar"])
    healthy, healthy_root, _ = results[0]
    healthy_summary = _verified_region_summary(healthy_root, healthy, config, engine)
    if (healthy.get("status") != "healthy_seed" or
            healthy.get("junit_passed") is not True or
            healthy.get("return_code") != 0 or healthy.get("timed_out") is not False or
            not healthy.get("native_target_retained") or
            healthy_summary is None or not healthy_summary.get("targetReached") or
            healthy_summary.get("targetThrowObserved")):
        raise ValueError("REGION_STATE healthy original JUnit/target is unverified")
    strict_count = retained = strict_retained = throws = candidates = 0
    for result, trial_root, events in results[1:]:
        is_strict = result["strict_injection"] is True
        strict_count += is_strict
        trial_summary = _verified_region_summary(trial_root, result, config, engine)
        if trial_summary is None:
            if (result.get("native_target_retained") or
                    result.get("target_exception_triggered") or
                    result.get("status") not in ("unmatched", "invalid_native_session")):
                raise ValueError("REGION_STATE missing graph claimed as result")
            continue
        if not is_strict and result.get("status") != "unmatched":
            raise ValueError("unmatched REGION_STATE injection claimed graph result")
        if is_strict:
            expected_delta = delta_region_state(healthy_summary, trial_summary)
            target_retained = bool(trial_summary.get("targetReached") and
                                   expected_delta["targetRetained"])
            if result.get("native_target_retained") is not target_retained:
                raise ValueError("REGION_STATE target/graph retention changed")
            if target_retained:
                if result.get("native_delta") != expected_delta:
                    raise ValueError("REGION_STATE graph delta changed")
                retained += 1
                strict_retained += 1
                applied = [row for row in events if row.get("kind") == "FAULT_APPLIED"]
                last = applied[-1] if applied else None
                checks = {row.get("occurrenceId") for row in events if
                          row.get("kind") == "TARGET_CHECK" and
                          row.get("siteId") == config["target_site"]}
                if result.get("fault_in_target_closure") is not bool(
                        last and last.get("occurrenceId") in checks):
                    raise ValueError("REGION_STATE fault/target membership changed")
                exact, admitted, reason, evidence = native._region_throw_evidence(
                    events, config["target_site"], config["target_throw"], last)
                if (result.get("target_throw_rows") != exact or
                        result.get("target_exception_triggered") is not bool(exact) or
                        result.get("target_temporal_admitted") is not admitted or
                        result.get("target_temporal_reason") != reason or
                        result.get("target_temporal_evidence") != evidence or
                        result.get("status") != ("candidate" if exact and admitted
                                                else "needs_causal_review" if exact
                                                else "checked")):
                    raise ValueError("REGION_STATE exact target throw/order changed")
                throws += bool(exact)
                candidates += result["status"] == "candidate"
            elif (result.get("status") != "target_lost" or
                  result.get("target_exception_triggered") or
                  (trial_summary.get("targetReached") and
                   result.get("native_delta") != expected_delta) or
                  (not trial_summary.get("targetReached") and
                   result.get("native_delta") is not None)):
                raise ValueError("REGION_STATE target loss claimed as coverage")
    status = checkpoint.get("status")
    if status not in FINISHED or len(trials) < 1:
        raise ValueError("REGION_STATE terminal campaign lacks completed fault budget")
    disposition = ("tested_candidate" if candidates else
                   "tested_inconclusive" if strict_retained == 0 else
                   "tested_no_target_throw")
    return {"terminal_disposition": disposition, "native_tested_complete": True,
            "fault_trials": len(trials), "strict_fault_trials": strict_count,
            "target_retained_fault_trials": retained,
            "strict_target_retained_fault_trials": strict_retained,
            "target_throw_trials": throws, "candidate_trials": candidates,
            "elapsed_seconds": elapsed, "status": status,
            "evidence": str(root / "summary.json")}


def _audit_terminal(case_id: str, config_path: Path, root: Path,
                    checkpoint: dict, summary: dict) -> dict[str, Any]:
    """Fail closed unless all reported native results have real pinned receipts."""
    config = _object(config_path)
    if (config.get("case_id") != case_id or
            checkpoint.get("schema_version") != 1 or
            checkpoint.get("case_id") != case_id or
            checkpoint.get("terminal") is not True or
            checkpoint.get("config_sha256") != _sha(config_path) or
            checkpoint.get("budget") != config.get("budget")):
        raise ValueError("native checkpoint identity/config mismatch")
    _same_checkpoint_summary(checkpoint, summary)
    admission = _object(root / "recording-admission.json")
    if (admission.get("schema_version") != 1 or
            not isinstance(admission.get("recording_fingerprint"), dict) or
            not isinstance(admission.get("origin"), dict) or
            checkpoint.get("origin") != admission["origin"]):
        raise ValueError("missing recording-derived native admission")
    fingerprint = admission["recording_fingerprint"]
    weave = _object(Path(config["native_weave_config"]))
    weave_receipt = Path(weave["output_classes"]) / "native-original-weave-receipt.json"
    origin = admission["origin"]
    recording = config["recording"]
    if (checkpoint.get("weave_receipt_sha256") != _sha(weave_receipt) or
            fingerprint.get("weave_receipt_sha256") != _sha(weave_receipt) or
            fingerprint.get("weave_config_sha256") != _sha(Path(config["native_weave_config"])) or
            fingerprint.get("static_scope_map_sha256") != _sha(
                Path(recording["static_scope_map"])) or
            fingerprint.get("candidate_graph_sha256") != _sha(
                Path(recording["candidate_graph"])) or
            fingerprint.get("region_skeletons_sha256") != _sha(
                Path(recording["region_skeletons"])) or
            origin.get("recording_manifest_sha256") != _sha(
                Path(recording["trace_dir"]) / "streaming_trace_manifest.json") or
            origin.get("recording_plan_sha256") != _sha(Path(weave["task_plan"])) or
            origin.get("scheduler_source_sha256") != fingerprint.get(
                "scheduler_source_sha256") or
            origin.get("static_scope_map_sha256") != fingerprint.get(
                "static_scope_map_sha256")):
        raise ValueError("native weave/static scope differs from admitted inputs")
    for field in ("engine_jar_sha256", "static_scope_map_sha256",
                  "candidate_graph_sha256", "region_skeletons_sha256",
                  "scheduler_source_sha256", "trace_tree_sha256"):
        _digest(fingerprint.get(field), field)
    if (not isinstance(checkpoint.get("elapsed_seconds"), (int, float)) or
            isinstance(checkpoint["elapsed_seconds"], bool) or
            checkpoint["elapsed_seconds"] < 0):
        raise ValueError("native elapsed time absent")
    healthy_ref = checkpoint.get("healthy")
    if not isinstance(healthy_ref, dict) or healthy_ref.get("name") != "r0000":
        raise ValueError("native healthy seed receipt absent")
    healthy_path = _inside(root, healthy_ref.get("result", ""))
    if healthy_path != root / "trials/r0000/result.json":
        raise ValueError("healthy result path is not r0000")
    healthy = _object(healthy_path)
    if (healthy.get("case_id") != case_id or healthy.get("faults") != [] or
            healthy.get("status") != healthy_ref.get("status") or
            not isinstance(healthy.get("elapsed_seconds"), (int, float)) or
            (healthy.get("status") == "healthy_seed" and
             (healthy.get("junit_passed") is not True or
              healthy.get("return_code") != 0 or
              healthy.get("timed_out") is not False))):
        raise ValueError("native healthy seed identity mismatch")
    trials = checkpoint.get("trials")
    if (not isinstance(trials, list) or checkpoint.get("completed_fault_trials") != len(trials)
            or any(not isinstance(item, dict) for item in trials)):
        raise ValueError("native trial count mismatch")
    all_rows = [(healthy_ref, healthy, healthy_path.parent)]
    for index, record in enumerate(trials, 1):
        name = f"r{index:04d}"
        if record.get("name") != name:
            raise ValueError("native trial order changed")
        path = _inside(root, record.get("result", ""))
        result = _object(path)
        if (path.parent != root / "trials" / name or result.get("case_id") != case_id
                or result.get("status") != record.get("status") or
                any(result.get(key) != record.get(key) for key in
                    ("strict_injection", "native_target_retained",
                     "target_exception_triggered", "elapsed_seconds"))):
            raise ValueError("native trial result differs from checkpoint")
        all_rows.append((record, result, path.parent))
    if round(sum(float(item[1]["elapsed_seconds"]) for item in all_rows), 3) != (
            checkpoint["elapsed_seconds"]):
        raise ValueError("native elapsed sum differs from trial receipts")
    strict = retained = strict_retained = throws = candidates = 0
    healthy_summary: dict[str, Any] | None = None
    for index, (_, result, trial_root) in enumerate(all_rows):
        faults = result.get("faults")
        if not isinstance(faults, list) or (index == 0 and faults) or (
                index > 0 and not faults):
            raise ValueError("native trial fault plan missing")
        iteration = trial_root / "iteration-native"
        plan = _object(iteration / "fault-plan.json")
        if plan.get("faults") != faults:
            raise ValueError("native applied fault plan changed")
        event_path = iteration / "fault-events.jsonl"
        if result.get("fault_events_sha256") != (_sha(event_path)
                                                 if event_path.is_file() else None):
            raise ValueError("native fault event bytes changed")
        events = native._rows(event_path)
        verified, last_fault_seq = native._strict_faults(faults, events)
        if result.get("strict_injection") is not bool(faults and verified):
            raise ValueError("native exact fault receipt mismatch")
        if not result.get("native_target_retained") and (
                result.get("target_temporal_admitted") is True or
                result.get("target_temporal_evidence") is not None):
            raise ValueError("temporal target claim without retained target")
        if index and verified:
            strict += 1
        if result.get("native_target_retained"):
            target_summary = _verified_native_summary(
                trial_root / "native-summary.json", iteration, result,
                config, admission)
            if index == 0:
                delta(target_summary, target_summary)
                healthy_summary = target_summary
            elif healthy_summary is None or result.get("native_delta") != delta(
                    healthy_summary, target_summary):
                raise ValueError("native graph delta differs from original closure summaries")
            if index:
                retained += 1
                if verified:
                    strict_retained += 1
            exact = native._exact_throws(events, target_summary,
                                         config["target_throw"], last_fault_seq)
            if result.get("target_throw_rows", []) != exact or (
                    result.get("target_exception_triggered") is not bool(exact)):
                raise ValueError("native target throw receipt mismatch")
            if index and exact:
                throws += 1
            if index and verified:
                applied = [item for item in events if item.get("kind") == "FAULT_APPLIED"]
                closure = {member.get("occurrenceId") for member in
                           target_summary["closureMembers"]}
                inside = bool(applied and applied[-1].get("occurrenceId") in closure)
                if result.get("fault_in_target_closure") is not inside:
                    raise ValueError("fault/target closure attribution differs from native graph")
                admitted, reason, evidence = native._temporal_target(
                    events, target_summary, config["target_site"])
                if (result.get("target_temporal_admitted") is not admitted or
                        result.get("target_temporal_reason") != reason or
                        result.get("target_temporal_evidence") != evidence):
                    raise ValueError("target temporal admission differs from receipts")
                linked_throw = bool(exact and evidence and any(
                    row["occurrenceId"] == evidence["targetOccurrenceId"] and
                    row["seq"] > evidence["checkSeq"] for row in exact))
                if not admitted:
                    expected_status = (
                        "needs_causal_review" if exact or reason in (
                            "cross_occurrence_order_unproved",
                            "target_check_not_recorded") else
                        "unrelated_target")
                elif exact and not linked_throw:
                    expected_status = "needs_causal_review"
                else:
                    expected_status = "candidate" if linked_throw else "checked"
                if result.get("status") != expected_status:
                    raise ValueError("native trial disposition disagrees with receipts")
            if result.get("status") == "candidate":
                applied = [item for item in events
                           if item.get("kind") == "FAULT_APPLIED"]
                if (not verified or not exact or not result.get("fault_in_target_closure")
                        or result.get("target_temporal_admitted") is not True
                        or not applied or applied[-1].get("occurrenceId") not in {
                            member.get("occurrenceId") for member in
                            target_summary["closureMembers"]}):
                    raise ValueError("candidate lacks closure-linked fault and throw")
                candidates += 1
        elif result.get("target_exception_triggered") or result.get("status") == "candidate":
            raise ValueError("target throw claimed without native retained target")
    status = checkpoint.get("status")
    terminal_fuzz = status in FINISHED and healthy.get("status") == "healthy_seed" and (
        healthy.get("native_target_retained") is True and healthy_summary is not None
        and len(trials) >= 1)
    if status in FINISHED and not terminal_fuzz:
        raise ValueError("completed native budget lacks reached healthy seed or fault trial")
    disposition = ("tested_candidate" if candidates else
                   "tested_inconclusive" if strict_retained == 0 else
                   "tested_no_target_throw") if terminal_fuzz else "native_blocked"
    return {"terminal_disposition": disposition,
            "native_tested_complete": terminal_fuzz,
            "fault_trials": len(trials), "strict_fault_trials": strict,
            "target_retained_fault_trials": retained,
            "strict_target_retained_fault_trials": strict_retained,
            "target_throw_trials": throws, "candidate_trials": candidates,
            "elapsed_seconds": checkpoint["elapsed_seconds"],
            "status": status,
            "evidence": str(root / "summary.json")}


def load_inventory(path: Path) -> tuple[list[dict], dict[str, str]]:
    document = _object(path)
    cases = document.get("cases")
    if document.get("count") != 102 or not isinstance(cases, list) or len(cases) != 102:
        raise ValueError("expected exact 102-check original inventory")
    seen = set()
    for row in cases:
        case_id = row.get("case_id")
        if (not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id) or
                case_id in seen or case_id.split("-", 1)[0].lower() != row.get("system")):
            raise ValueError("invalid/duplicate original inventory case")
        seen.add(case_id)
    return cases, {row["case_id"]: row["system"] for row in cases}


def load_ownership(path: Path, case_ids: set[str]) -> dict[str, str]:
    document = _object(path)
    owners = document.get("owner")
    if (not isinstance(owners, dict) or set(owners) != case_ids or
            any(host not in ("node0", "node1", "node2") for host in owners.values())):
        raise ValueError("three-host ownership does not cover exactly 102 cases")
    return owners


def load_reviews(path: Path | None, case_ids: set[str]) -> dict[str, dict]:
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(path)
    document = _object(path)
    reviews = document.get("no_eligible_original_cluster_junit", {})
    if document.get("schema_version") != 1 or not isinstance(reviews, dict) or (
            set(reviews) - case_ids):
        raise ValueError("invalid native no-JUnit review map")
    for case_id, item in reviews.items():
        if (not isinstance(item, dict) or not isinstance(item.get("reason"), str) or
                not item["reason"].strip() or not isinstance(item.get("evidence_paths"), list)
                or not item["evidence_paths"] or not all(
                    isinstance(entry, str) and Path(entry).is_file()
                    for entry in item["evidence_paths"])):
            raise ValueError(f"no-JUnit review lacks source evidence: {case_id}")
    return reviews


def inspect_case(item: dict, owner: str, config_root: Path, state_root: Path,
                 no_junit: dict | None = None) -> dict[str, Any]:
    case_id = item["case_id"]
    target, workload = item["target"], item["workload"]
    try:
        config_file, case_root = _native_case_files(item, config_root, state_root)
    except (OSError, ValueError, KeyError, TypeError) as failure:
        return {"case_id": case_id, "owner": owner,
                "terminal_disposition": "receipt_error",
                "native_tested_complete": False, "reason": str(failure),
                "status": "blocked", "evidence": str(config_root / f"{case_id}.json")}
    native_state_exists = any((case_root / name).exists() for name in
                              ("checkpoint.json", "summary.json",
                               "recording-admission.json", "trials"))
    row: dict[str, Any] = {
        "case_id": case_id, "system": item["system"],
        "system_version": item["system_version"], "owner": owner,
        "target_source_path": target.get("source_path", ""),
        "target_class": target.get("function", "").split("(", 1)[0].rsplit(".", 1)[0],
        "target_method": target.get("function", ""),
        "target_line": target.get("source_line", ""),
        "target_check_code": target.get("check_code", ""),
        "target_exception": target.get("target_exception", ""),
        "junit_workload": workload.get("selected_selector", ""),
        "native_config": str(config_file) if config_file.is_file() else "",
        "native_target_site": "", "status": "",
        "terminal_disposition": "needs_native_preparation",
        "native_tested_complete": False, "fault_trials": 0,
        "strict_fault_trials": 0, "target_retained_fault_trials": 0,
        "strict_target_retained_fault_trials": 0,
        "target_throw_trials": 0, "candidate_trials": 0,
        "elapsed_seconds": "", "elapsed_basis": "cumulative_junit_seconds",
        "evidence": "", "reason": "",
    }
    if no_junit and not native_state_exists:
        row.update(terminal_disposition="no_eligible_original_cluster_junit",
                   evidence=";".join(no_junit["evidence_paths"]),
                   reason=no_junit["reason"])
        return row
    checkpoint_file = case_root / "checkpoint.json"
    if not config_file.is_file():
        if native_state_exists:
            row.update(terminal_disposition="receipt_error",
                       reason="native state exists without its case config")
        else:
            prep_state = case_root / "preparation/state.json"
            if prep_state.is_file():
                try:
                    state = _object(prep_state)
                    phase = state.get("status")
                    if phase in ("running", "failed"):
                        row.update(terminal_disposition=(
                            "native_preparing" if phase == "running" else
                            "native_preparation_failed"),
                            status=phase, evidence=str(prep_state),
                            reason=state.get("reason", ""))
                except (OSError, ValueError) as failure:
                    row.update(terminal_disposition="receipt_error",
                               reason=str(failure))
        return row
    try:
        config = _object(config_file)
        bound = config_file != config_root / f"{case_id}.json"
        if ((not bound and config.get("case_id") != case_id) or
                config.get("junit") != {
                "class": workload.get("test_class"),
                "method": workload.get("test_method")}):
            raise ValueError("native config does not use inventory's original JUnit")
        native._validate_config(config)
        inventory_method = target.get("site_id", "").split("#", 1)[0]
        native_method = config["target_site"].split("#", 1)[0]
        if not inventory_method or inventory_method != native_method:
            raise ValueError("native target site is outside the inventory check method")
        if (target.get("target_exception") and
                config["target_throw"]["exceptionClass"] != target[
                    "target_exception"]):
            raise ValueError("native target exception differs from inventory")
        region = config["runner"].get("mode") == "region_state"
        if region:
            _verify_region_weave(config_file)
        else:
            verify_preparation_receipt(item, config_file, case_root)
        row["native_target_site"] = config["target_site"]
        if not checkpoint_file.exists():
            if any((case_root / name).exists() for name in
                   ("summary.json", "trials")):
                raise ValueError("native trial/admission state exists without checkpoint")
            row["terminal_disposition"] = "ready"
            return row
        checkpoint = _object(checkpoint_file)
        if (checkpoint.get("schema_version") != 1 or
                checkpoint.get("case_id") != config["case_id"] or
                checkpoint.get("config_sha256") != _sha(config_file)):
            raise ValueError("native checkpoint changed identity/config")
        if checkpoint.get("terminal") is False:
            if checkpoint.get("status") != "running":
                raise ValueError("nonterminal native checkpoint has invalid status")
            row.update(terminal_disposition="resumable", status="running",
                       fault_trials=checkpoint.get("completed_fault_trials", 0),
                       elapsed_seconds=checkpoint.get("elapsed_seconds", ""),
                       evidence=str(checkpoint_file))
            return row
        if checkpoint.get("terminal") is not True:
            raise ValueError("native checkpoint terminal field is invalid")
        auditor = _audit_region_terminal if region else _audit_terminal
        audited = auditor(config["case_id"], config_file, case_root, checkpoint,
                          _object(case_root / "summary.json"))
        row.update(audited)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as failure:
        row.update(terminal_disposition="receipt_error", status="blocked",
                   reason=str(failure), evidence=str(checkpoint_file))
    return row


def build_checklist(inventory: Path, ownership: Path, config_root: Path,
                    state_root: Path, reviews: Path | None = None,
                    host_filter: str | None = None) -> list[dict]:
    cases, by_id = load_inventory(inventory)
    owners = load_ownership(ownership, set(by_id))
    no_junit = load_reviews(reviews, set(by_id))
    if host_filter is not None and host_filter not in ("node0", "node1", "node2"):
        raise ValueError("unknown checklist owner host")
    return [inspect_case(item, owners[item["case_id"]], config_root, state_root,
                         no_junit.get(item["case_id"])) for item in cases
            if host_filter is None or owners[item["case_id"]] == host_filter]


def build_distributed_checklist(inventory: Path, ownership: Path,
                                config_root: Path, state_root: Path,
                                reviews: Path | None = None,
                                ssh_key: Path | None = None) -> list[dict]:
    """Read each owner host; never infer remote completion from local files."""
    if socket.gethostname().split(".")[0] != "node0":
        raise ValueError("distributed checklist aggregation runs on node0")
    cases, systems = load_inventory(inventory)
    owners = load_ownership(ownership, set(systems))
    local = {row["case_id"]: row for row in build_checklist(
        inventory, ownership, config_root, state_root, reviews, "node0")}
    key = ssh_key or (Path.home() / ".ssh/id_ed25519_nodes")
    for host in ("node1", "node2"):
        command = ["python3", "-m", "Mallory.native_graphchecker_dispatch",
                   "status", "--inventory", str(inventory), "--ownership",
                   str(ownership), "--config-root", str(config_root),
                   "--state-root", str(state_root), "--host", host,
                   "--format", "json"]
        if reviews is not None:
            command.extend(("--reviews", str(reviews)))
        remote = f"cd {shlex.quote(str(BASE))} && {shlex.join(command)}"
        completed = subprocess.run([
            "ssh", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o",
            "BatchMode=yes", f"ZhenyuLi@{host}", remote],
            capture_output=True, text=True, timeout=300)
        if completed.returncode:
            raise RuntimeError(f"native status unavailable on {host}: "
                               f"{completed.stderr[:500]}")
        payload = json.loads(completed.stdout)
        if (payload.get("schema_version") != 1 or
                payload.get("inventory_sha256") != _sha(inventory) or
                payload.get("ownership_sha256") != _sha(ownership) or
                payload.get("dispatcher_source_sha256") != _sha(Path(__file__)) or
                not isinstance(payload.get("rows"), list)):
            raise ValueError(f"native status provenance mismatch on {host}")
        for row in payload["rows"]:
            if (not isinstance(row, dict) or row.get("owner") != host or
                    row.get("case_id") not in owners or
                    owners[row["case_id"]] != host or row["case_id"] in local):
                raise ValueError(f"invalid or duplicate native status row on {host}")
            local[row["case_id"]] = row
    if set(local) != set(systems):
        raise ValueError("distributed native status does not cover all 102 checks")
    return [local[item["case_id"]] for item in cases]


def tsv(rows: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS, delimiter="\t",
                            extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: value.replace("\t", "\\t").replace("\r", "\\r")
                         .replace("\n", "\\n") if isinstance(value, str) else value
                         for key, value in row.items()})
    return output.getvalue()


def run_next(inventory: Path, ownership: Path, config_root: Path,
             state_root: Path, host: str, reviews: Path | None = None,
             *, runner=native.run_campaign) -> dict[str, Any]:
    """Run at most one host-owned case; native campaign resumes its own trials."""
    if host not in ("node0", "node1", "node2") or socket.gethostname().split(".")[0] != host:
        raise ValueError("run-next must execute on the physical owner host")
    state_root.mkdir(parents=True, exist_ok=True)
    with (state_root / f".host-{host}.lock").open("a+") as host_lock:
        fcntl.flock(host_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cases, by_id = load_inventory(inventory)
        owners = load_ownership(ownership, set(by_id))
        no_junit = load_reviews(reviews, set(by_id))
        for item in cases:
            case_id = item["case_id"]
            if owners[case_id] != host:
                continue
            row = inspect_case(item, host, config_root, state_root,
                               no_junit.get(case_id))
            if row["terminal_disposition"] not in ("ready", "resumable"):
                continue
            config_file, root = _native_case_files(item, config_root, state_root)
            root.mkdir(parents=True, exist_ok=True)
            with (root / ".dispatch.lock").open("a+") as case_lock:
                try:
                    fcntl.flock(case_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                # Re-read under the case lock: another worker may have closed it.
                now = inspect_case(item, host, config_root, state_root,
                                   no_junit.get(case_id))
                if now["terminal_disposition"] not in ("ready", "resumable"):
                    continue
                runner(config_file, root)
                return inspect_case(item, host, config_root, state_root,
                                    no_junit.get(case_id))
        return {"host": host, "status": "no_runnable_native_case"}
