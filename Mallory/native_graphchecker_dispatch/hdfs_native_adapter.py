"""Prepare an HDFS inventory check with the original GraphChecker pipeline.

The request fixes the throw, mapped guard lines, and unchanged JUnit. Soot
discovers the I/O frontier. A distinct, source-pinned attestation is required
when the executed JUnit differs from the inventory's selected selector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from Mallory.instrumentation.graphchecker_port import native_original_weave as weave
from Mallory.native_graphchecker_campaign import campaign as native
from .preparation import _atomic, _digest, _sha


MODE = "original_graphchecker_native_preparation"
PROOF_MODE = "original_graphchecker_native_adapter"
CHECK = re.compile(r"@(\d+):branch:(\d+)$")
FORBIDDEN_PROFILE = {"doors", "fault_sites", "io_points", "target_site",
                     "check_line", "throw_line", "junit", "case_id"}


def _object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _selector(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or value.count("#") != 1:
        raise ValueError("JUnit selector must name one original method")
    clazz, method = value.split("#")
    if not clazz or not method or not re.fullmatch(r"[\w$]+", method):
        raise ValueError("invalid original JUnit selector")
    return clazz, method


def _source_file(root: Path, relative: str, digest: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("source path must be repository relative")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve(strict=True)) or _sha(path) != digest:
        raise ValueError(f"original source changed: {relative}")
    return path


def request_from_inventory(inventory: Path, case_id: str,
                           alternate_attestation: Path | None = None,
                           selected_check_mapping: str | None = None) -> dict:
    """Bind the inventory check and selected source JUnit, with explicit override."""
    document = _object(inventory)
    matches = [row for row in document.get("cases", [])
               if row.get("case_id") == case_id and row.get("system") == "hdfs"]
    if len(matches) != 1 or not matches[0].get("eligibility", {}).get(
            "may_attempt_seed"):
        raise ValueError("HDFS inventory case has no eligible original seed")
    row = matches[0]
    target, workload = row["target"], row["workload"]
    function = target["function"].split("(", 1)[0]
    if "." not in function:
        raise ValueError("target function is not qualified")
    clazz, method = function.rsplit(".", 1)
    checks = target.get("runtime_mapping", {}).get("check_sites", [])
    mapped = []
    for check in checks:
        match = CHECK.search(check)
        if not match:
            raise ValueError("inventory guard has no compiled branch mapping")
        mapped.append({"source_line": int(match.group(1)),
                       "branch_ordinal": int(match.group(2)),
                       "mapping": check})
    if not mapped or len({x["mapping"] for x in mapped}) != len(mapped):
        raise ValueError("HDFS check mapping is empty or duplicated")
    if selected_check_mapping is None:
        selected_check_mapping = mapped[0]["mapping"]
    selected_checks = [x for x in mapped if x["mapping"] ==
                       selected_check_mapping]
    if len(selected_checks) != 1:
        raise ValueError("selected HDFS guard is absent from the inventory")
    selector = workload["selected_selector"]
    junit_source = workload["test_source_path"]
    candidates = [x for x in workload.get("candidates", [])
                  if x.get("selector") == selector and
                  x.get("source_path") == junit_source]
    if len(candidates) != 1:
        raise ValueError("inventory JUnit source is not uniquely mapped")
    junit_sha = candidates[0]["source_sha256"]
    alternate = None
    if alternate_attestation is not None:
        att = _object(alternate_attestation)
        if (att.get("case_id") != case_id or
                att.get("inventory_recorded_selector") != selector):
            raise ValueError("alternate JUnit lacks matching inventory attestation")
        source_root = Path(att["source_root"]).resolve(strict=True)
        if att.get("binding_type") == "alternate_unchanged_original_junit":
            healthy_root = Path(att["resolver_receipt_path"]).parent
            trace = healthy_root / "healthy-trace"
            if (att.get("executed_selector") == selector or
                    att.get("healthy_junit_exit_code") != 0 or
                    att.get("healthy_target_reached_event_count", 0) < 1 or
                    att.get("target_throw_site_id") != target["site_id"] or
                    _sha(trace / "runtime_trace.jsonl") != att[
                        "healthy_runtime_trace_sha256"] or
                    _sha(trace / "streaming_trace_manifest.json") != att[
                        "healthy_trace_manifest_sha256"] or
                    att.get("source_commit") != subprocess.check_output(
                        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
                        text=True).strip() or
                    _sha(Path(att["native_official_healthy_result_path"])) != att[
                        "native_official_healthy_result_sha256"] or
                    _sha(Path(att["resolver_receipt_path"])) != att[
                        "resolver_receipt_sha256"]):
                raise ValueError("alternate JUnit official attestation is incomplete")
            receipt = _object(Path(att["resolver_receipt_path"]))
            result = _object(Path(att["native_official_healthy_result_path"]))
            if (receipt.get("checkSiteId") != att.get("target_site_id") or
                    receipt.get("test") != att.get("executed_selector") or
                    receipt.get("fatalOutcome") is not False or
                    receipt.get("reachedEventCount", 0) < 1 or
                    result.get("case_id") != case_id or
                    result.get("status") != "healthy_seed" or
                    result.get("junit_passed") is not True):
                raise ValueError("alternate JUnit resolver attestation is invalid")
            selector = att["executed_selector"]
            junit_source = att["source_path"]
            junit_sha = att["source_sha256"]
        elif att.get("status") == "provisional_prior_case_diagnostic":
            if (att.get("proposed_executed_selector") == selector or
                    att.get("target_source_sha256") != target["source_sha256"] or
                    att.get("target_throw_source_line") != target["source_line"] or
                    att.get("target_exception") != target["target_exception"] or
                    att.get("diagnostic_original_junit_exit_code") != 0 or
                    not any(x.get("siteId") == att.get("expected_guard_site_id")
                            for x in att.get("diagnostic_observed_branch_rows", [])) or
                    _sha(Path(att["target_source_path"])) !=
                    target["source_sha256"] or
                    not Path(att["target_source_path"]).resolve().is_relative_to(
                        source_root) or
                    _sha(Path(att["diagnostic_trace_path"])) != att[
                        "diagnostic_trace_sha256"] or
                    _sha(Path(att["diagnostic_trace_manifest_path"])) != att[
                        "diagnostic_trace_manifest_sha256"]):
                raise ValueError("alternate JUnit source/guard attestation changed")
            selector = att["proposed_executed_selector"]
            junit_source = att["test_source_path"]
            junit_sha = att["test_source_sha256"]
        else:
            raise ValueError("alternate JUnit lacks accepted attestation type")
        if (_sha(Path(junit_source)) != junit_sha or
                not Path(junit_source).resolve().is_relative_to(source_root) or
                _sha(Path(att["compiled_test_class_path"])) != att[
                    "compiled_test_class_sha256"]):
            raise ValueError("alternate JUnit source or compiled class changed")
        junit_source = str(Path(junit_source).resolve().relative_to(source_root))
        alternate = {"path": str(alternate_attestation.resolve(strict=True)),
                     "sha256": _sha(alternate_attestation),
                     "inventory_selector": workload["selected_selector"]}
    junit_class, junit_method = _selector(selector)
    throw_line = target["runtime_mapping"].get("selected_source_line") or target[
        "source_line"]
    if not isinstance(throw_line, int) or throw_line <= 0:
        raise ValueError("target throw line is invalid")
    return {"schema_version": 1, "mode": MODE, "case_id": case_id,
            "system": "hdfs", "system_version": row["system_version"],
            "inventory_sha256": _sha(inventory),
            "inventory_row_sha256": _digest(row),
            "target": {"site_id": target["site_id"],
                       "class": clazz, "method": method,
                       "check_sites": mapped,
                       "selected_check_mapping": selected_check_mapping,
                       "throw_line": throw_line,
                       "source_path": target["source_path"],
                       "source_sha256": target["source_sha256"],
                       "target_exception": target["target_exception"]},
            "original_junit": {"selector": selector, "class": junit_class,
                               "method": junit_method,
                               "source_path": junit_source,
                               "source_sha256": junit_sha},
            "alternate_junit_attestation": alternate}


def _target_sites(request: dict, scope: Path) -> tuple[str, str, dict]:
    manifest = _object(scope / "weave_manifest.json")
    analysis = _object(scope / "analysis.json")
    target = request["target"]
    sites = manifest.get("targets", [])
    chosen = [row for row in target["check_sites"] if row["mapping"] ==
              target["selected_check_mapping"]]
    if len(chosen) != 1 or sum(row["source_line"] == chosen[0]["source_line"]
                               for row in target["check_sites"]) != 1:
        raise ValueError("inventory guard mapping is ambiguous at one source line")
    selected = [row for row in sites if row.get("kind") == "BRANCH" and
                row.get("clazz") == target["class"] and
                row.get("method") == target["method"] and
                row.get("line") == chosen[0]["source_line"]]
    if len(selected) != 1:
        raise ValueError("original Soot did not uniquely resolve an inventory guard")
    throws = [row for row in sites if row.get("kind") == "THROW" and
              row.get("clazz") == target["class"] and
              row.get("method") == target["method"] and
              row.get("line") == target["throw_line"] and
              row.get("exceptionClass") == target["target_exception"]]
    if (len(throws) != 1 or throws[0]["siteId"] != target["site_id"] or
            analysis.get("targetSiteId") != selected[0]["siteId"] or
            analysis.get("throwSiteId") != target["site_id"] or
            analysis.get("analysisKind") != "original_graphchecker_seed_backward" or
            not isinstance(manifest.get("doors"), list) or
            not manifest["doors"]):
        raise ValueError("original Soot guard, throw, or I/O frontier is incomplete")
    return analysis["targetSiteId"], throws[0]["siteId"], manifest


def verify_existing(request: dict, static_root: Path, healthy_root: Path) -> dict:
    """Read-only gate for already frozen original GraphChecker evidence."""
    if request.get("mode") != MODE or request.get("system") != "hdfs":
        raise ValueError("not an HDFS native preparation request")
    scope = static_root / "static-scope"
    check, throw, manifest = _target_sites(request, scope)
    static = _object(static_root / "static-prep-receipt.json")
    if (static.get("case_id") != request["case_id"] or
            static.get("scope", {}).get("manual_door_sites") is not False or
            static.get("scope", {}).get("original_graphchecker_seed") is not True or
            static.get("target", {}).get("check_site_id") != check or
            static.get("target", {}).get("throw_site_id") != throw or
            _sha(scope / "weave_manifest.json") != static["artifacts"][
                "manifest"]["sha256"]):
        raise ValueError("static GraphChecker provenance or target mapping changed")
    for artifact, expected in (("target_source", request["target"][
            "source_sha256"]), ("original_junit_source", request[
                "original_junit"]["source_sha256"])):
        pinned = static["artifacts"].get(artifact, {})
        if pinned.get("sha256") != expected or _sha(Path(
                pinned.get("path", ""))) != expected:
            raise ValueError(f"original HDFS {artifact} source changed")
    alternate = request.get("alternate_junit_attestation")
    if alternate and _sha(Path(alternate["path"])) != alternate["sha256"]:
        raise ValueError("alternate original JUnit attestation changed")
    weave_config = _object(healthy_root / "native-weave-config.json")
    weave_receipt = _object(healthy_root / "weave-verify.json")
    if (weave_config.get("weave_mode") != "region_state" or
            _sha(Path(weave_config["native_fault_manifest"])) != _sha(
                scope / "weave_manifest.json") or
            weave_receipt.get("mode") !=
            "mallory_vendored_original_graphchecker_region_state_weave" or
            weave_receipt.get("native_fault_manifest_sha256") != _sha(
                scope / "weave_manifest.json") or
            weave_receipt.get("config_sha256") != _sha(
                healthy_root / "native-weave-config.json") or
            weave_receipt.get("recording_artifacts_sha256") !=
            weave.file_tree_digest(Path(weave_config["recording_artifacts"]))):
        raise ValueError("native REGION_STATE weave is not source aligned")
    for name in ("candidate_dataflow_edges.jsonl.gz", "static_scope_map.jsonl",
                 "region_skeletons.jsonl.gz"):
        if _sha(static_root / "original-scope" / name) != _sha(
                Path(weave_config["recording_artifacts"]) / name):
            raise ValueError("native weave changed an original static artifact")
    run = _object(healthy_root / "healthy-run.json")
    occurrence = _object(healthy_root / "target-occurrence.json")
    junit = request["original_junit"]["selector"]
    trace = healthy_root / "healthy-trace"
    trace_manifest = _object(trace / "streaming_trace_manifest.json")
    with (trace / "runtime_trace.jsonl").open(encoding="utf-8") as stream:
        root_event = json.loads(stream.readline())
    rows = [json.loads(line) for line in (
        healthy_root / "healthy-fault-events.jsonl").read_text(
            encoding="utf-8").splitlines() if line.strip()]
    door_count = sum(row.get("kind") == "FAULT_DOOR" for row in rows)
    check_count = sum(row.get("kind") == "TARGET_CHECK" and
                      row.get("siteId") == check for row in rows)
    if (run.get("status") != 0 or run.get("junit") != junit or
            trace_manifest.get("status") != "CLOSED" or
            root_event.get("event") != "SOURCE_REGISTER" or
            root_event.get("sourceId") != junit or
            door_count < 1 or check_count < 1 or
            any(row.get("kind") in ("FAULT_APPLIED", "TARGET_THROW")
                for row in rows) or
            occurrence.get("test") != junit or
            occurrence.get("checkSiteId") != check or
            occurrence.get("fatalOutcome") is not False or
            occurrence.get("reachedEventCount", 0) < 1 or
            occurrence.get("selectedOccurrenceAddress") in (None, "") or
            occurrence.get("runtimeTraceSha256") != _sha(
                trace / "runtime_trace.jsonl")):
        raise ValueError("unchanged JUnit or original target resolver did not close")
    for stage in ("recorder", "scheduler"):
        if _object(healthy_root / f"{stage}-run.json").get("status") != 0:
            raise ValueError(f"original {stage} did not pass")
    plan = healthy_root / "healthy-scheduled/execution_task_plan.jsonl"
    with plan.open(encoding="utf-8") as stream:
        has_task = any(line.strip() for line in stream)
    if not has_task:
        raise ValueError("original Scheduler produced no task")
    config = _object(healthy_root / "campaign-config.json")
    if (config.get("case_id") != request["case_id"] or
            config.get("target_site") != check or
            config.get("target_throw") != {"siteId": throw,
                                           "exceptionClass": request["target"][
                                               "target_exception"]} or
            config.get("junit") != {"class": request["original_junit"]["class"],
                                    "method": request["original_junit"]["method"]} or
            config.get("recording", {}).get("test_id") != junit or
            config.get("recording", {}).get("target_occurrence") != occurrence[
                "selectedOccurrenceAddress"] or
            config.get("native_weave_config") != str(
                healthy_root / "native-weave-config.json") or
            any(config.get("recording", {}).get(key) != str(Path(
                weave_config["recording_artifacts"]) / file) for key, file in
                (("candidate_graph", "candidate_dataflow_edges.jsonl.gz"),
                 ("static_scope_map", "static_scope_map.jsonl"),
                 ("region_skeletons", "region_skeletons.jsonl.gz"))) or
            config.get("runner", {}).get("mode") != "region_state"):
        raise ValueError("native campaign differs from observed guard/JUnit")
    native._validate_config(config)
    return {"schema_version": 1, "case_id": request["case_id"],
            "status": "verified_existing_original_pipeline",
            "inventory_row_sha256": request["inventory_row_sha256"],
            "selected_junit": junit, "alternate_junit_attestation": request.get(
                "alternate_junit_attestation"),
            "check_site_id": check, "throw_site_id": throw,
            "static_manifest_sha256": _sha(scope / "weave_manifest.json"),
            "static_door_count": len(manifest["doors"]),
            "observed_fault_doors": door_count,
            "observed_target_checks": check_count,
            "healthy_trace_sha256": _sha(trace / "runtime_trace.jsonl"),
            "selected_occurrence": occurrence["selectedOccurrenceAddress"],
            "scheduler_plan_sha256": _sha(plan),
            "campaign_config_sha256": _sha(healthy_root / "campaign-config.json")}


def _run(stage: str, command: list[str], root: Path, timeout: int,
         env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
    logs = root / "commands"
    logs.mkdir(parents=True, exist_ok=True)
    _atomic(logs / f"{stage}.json", {"argv": command,
                                    "cwd": str(cwd or root),
                                    "timeout_seconds": timeout})
    with (logs / f"{stage}.stdout").open("wb") as stdout, (
            logs / f"{stage}.stderr").open("wb") as stderr:
        result = subprocess.run(command, cwd=cwd or root, env=env,
                                stdout=stdout, stderr=stderr, timeout=timeout)
    if result.returncode:
        raise ValueError(f"original GraphChecker {stage} failed: {result.returncode}")


def _profile(request: dict, path: Path) -> dict:
    profile = _object(path)
    if (profile.get("schema_version") != 1 or
            profile.get("mode") != "original_graphchecker_hdfs_profile" or
            request.get("system") != "hdfs" or
            profile.get("system_version") != request.get("system_version") or
            FORBIDDEN_PROFILE.intersection(profile)):
        raise ValueError("HDFS profile contains a case-specific target or door")
    inventory = Path(profile.get("inventory_path", ""))
    if (not inventory.is_absolute() or not inventory.is_file() or
            _sha(inventory) != profile.get("inventory_sha256") or
            request.get("inventory_sha256") != profile["inventory_sha256"]):
        raise ValueError("HDFS profile inventory pin changed")
    alternate = request.get("alternate_junit_attestation")
    expected = request_from_inventory(inventory, request["case_id"],
        Path(alternate["path"]) if alternate else None,
        request.get("target", {}).get("selected_check_mapping"))
    if (request.get("inventory_row_sha256") != expected[
            "inventory_row_sha256"] or
            any(request.get("target", {}).get(key) != expected["target"][key]
                for key in ("site_id", "class", "method", "check_sites",
                            "selected_check_mapping",
                            "throw_line", "source_path", "source_sha256",
                            "target_exception")) or
            any(request.get("original_junit", {}).get(key) != expected[
                "original_junit"][key] for key in
                ("selector", "class", "method", "source_path",
                 "source_sha256"))):
        raise ValueError("HDFS request differs from its pinned inventory")
    for key in ("source_root", "process_classes", "java", "engine_root",
                "native_fault_helper", "communication_mappings"):
        value = Path(profile.get(key, ""))
        if not value.is_absolute() or not value.exists() or value.is_symlink():
            raise ValueError(f"HDFS profile lacks immutable {key}")
    for key in ("analysis_classpath", "planner_classpath",
                "runtime_classpath", "soot_dependency_classpath"):
        values = profile.get(key)
        if not isinstance(values, list) or not values or any(
                not isinstance(value, str) or not Path(value).is_absolute() or
                not Path(value).exists() or Path(value).is_symlink()
                for value in values):
            raise ValueError(f"HDFS {key} lacks an ordered pinned classpath")
    pinned_classpath = profile.get("classpath_pins")
    required_classpath = {value for key in ("analysis_classpath",
        "planner_classpath", "runtime_classpath", "soot_dependency_classpath")
        for value in profile[key]}
    if (not isinstance(pinned_classpath, dict) or
            not required_classpath.issubset(pinned_classpath)):
        raise ValueError("HDFS profile omitted classpath artifact pins")
    classes = Path(profile["process_classes"])
    if _sha(Path(profile["java"])) != profile.get("java_sha256"):
        raise ValueError("HDFS Java executable changed")
    source = Path(profile["source_root"])
    if subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                               text=True).strip() != profile.get("source_commit"):
        raise ValueError("original HDFS source revision changed")
    for name, expected_sha in profile.get("classpath_pins", {}).items():
        path = Path(name)
        if not path.is_absolute() or not path.exists() or path.is_symlink():
            raise ValueError("HDFS pinned classpath path changed")
        actual = (_sha(path) if path.is_file() else weave.file_tree_digest(path))
        if actual != expected_sha:
            raise ValueError(f"HDFS classpath artifact changed: {name}")
    if weave.class_tree_digest(classes) != profile.get("process_classes_sha256"):
        raise ValueError("HDFS process class tree changed")
    if _sha(Path(profile["native_fault_helper"])) != profile.get(
            "native_fault_helper_sha256") or _sha(Path(
                profile["communication_mappings"])) != profile.get(
                    "communication_mappings_sha256"):
        raise ValueError("HDFS runtime helper or communication map changed")
    if Path(profile["engine_root"]).resolve() != weave.ENGINE:
        raise ValueError("launch with MALLORY_NATIVE_ENGINE_ROOT set to the profile engine")
    engine = weave.verify_engine()
    if engine.get("engine_jar_sha256") != profile.get("engine_jar_sha256"):
        raise ValueError("source-built original GraphChecker engine changed")
    _source_file(source, request["target"]["source_path"],
                 request["target"]["source_sha256"])
    junit = request["original_junit"]
    original_junit = _source_file(source, junit["source_path"],
                                  junit["source_sha256"])
    if f"{junit['method']}(" not in original_junit.read_text(encoding="utf-8"):
        raise ValueError("selected original JUnit method is absent from source")
    if alternate and _sha(Path(alternate["path"])) != alternate["sha256"]:
        raise ValueError("alternate original JUnit attestation changed")
    budget = profile.get("budget", {})
    if (any(not isinstance(budget.get(key), int) or budget[key] <= 0 for key in
            ("fault_trials", "seconds", "max_faults_per_trial")) or
            not isinstance(profile.get("max_jobs"), int) or
            profile["max_jobs"] <= 0):
        raise ValueError("HDFS profile needs bounded trial and scheduler budgets")
    return profile


def prepare(request_file: Path, profile_file: Path, output: Path) -> dict:
    """Run static scope, fault-capable REGION_STATE JUnit and original planning."""
    request = _object(request_file)
    profile = _profile(request, profile_file)
    if output.exists() and any(output.iterdir()):
        raise ValueError("native HDFS preparation output must start empty")
    output.mkdir(parents=True, exist_ok=True)
    static = output / "static"
    healthy = output / "healthy"
    static.mkdir()
    healthy.mkdir()
    target, junit = request["target"], request["original_junit"]
    java = profile["java"]
    process = Path(profile["process_classes"])
    analysis_cp = profile["analysis_classpath"]
    original = static / "original-scope"
    scope = static / "static-scope"
    checks = [row for row in target["check_sites"] if row["mapping"] ==
              target["selected_check_mapping"]]
    scope_target = {"class": target["class"], "method": target["method"],
                    "line": checks[0]["source_line"],
                    "kind": "BRANCH",
                    "check_line": checks[0]["source_line"],
                    "throw_line": target["throw_line"],
                    "exception": target["target_exception"]}
    scope_input = {"case_id": request["case_id"], "target": scope_target,
                   "workload": {"class": junit["class"],
                                "method": junit["method"]},
                   "analysis": {**profile.get("analysis", {}),
                                "process_dirs": [str(process)],
                                "classpath": analysis_cp,
                                "original_graphchecker_seed": True,
                                "original_engine_output_dir": str(original)}}
    if FORBIDDEN_PROFILE.intersection(scope_input["analysis"]):
        raise ValueError("HDFS analysis profile selects a fault site")
    _atomic(static / "scope-input.json", scope_input)
    _run("static", [java, f"-Xmx{profile.get('static_heap_mb', 8192)}m",
        f"-Dcausynth.communication.mappings={profile['communication_mappings']}",
        "-cp", os.pathsep.join(profile["planner_classpath"]),
        "edu.uva.liftlab.mallory.scope.ScopePlanner",
        str(static / "scope-input.json"), str(scope)], output,
        profile.get("static_timeout_seconds", 1800))
    check, throw, manifest = _target_sites(request, scope)
    graph = original / "candidate_dataflow_edges.jsonl.gz"
    static_map = original / "static_scope_map.jsonl"
    skeletons = original / "region_skeletons.jsonl.gz"
    for path in (graph, static_map, skeletons, original / "io_doors.jsonl"):
        if not path.is_file():
            raise ValueError("original GraphChecker static output incomplete")
    with (original / "io_doors.jsonl").open(encoding="utf-8") as stream:
        has_doors = any(line.strip() for line in stream)
    if not has_doors:
        raise ValueError("original GraphChecker found no typed I/O door")
    scope_receipt = {"schema_version": 1,
        "mode": "original_graphchecker_static_scope",
        "case_id": request["case_id"], "request_sha256": _digest(request),
        "analysis_kind": "original_graphchecker_seed_backward",
        "analysis_path": str(scope / "analysis.json"),
        "analysis_sha256": _sha(scope / "analysis.json"),
        "scope_input_path": str(static / "scope-input.json"),
        "scope_input_sha256": _sha(static / "scope-input.json"),
        "engine_jar_sha256": _sha(weave.JAR),
        "process_classes_path": str(process),
        "process_classes_sha256": weave.class_tree_digest(process),
        "ordered_analysis_classpath_sha256": hashlib.sha256(
            os.pathsep.join(analysis_cp).encode()).hexdigest(),
        "candidate_graph_sha256": _sha(graph),
        "static_scope_map_sha256": _sha(static_map),
        "region_skeletons_sha256": _sha(skeletons),
        "check_site_id": check, "throw_site_id": throw,
        "typed_io_door_count": len(manifest["doors"])}
    _atomic(output / "static-scope-receipt.json", scope_receipt)
    _atomic(static / "static-prep-receipt.json", {
        "schema_version": 1, "case_id": request["case_id"],
        "scope": {"manual_door_sites": False,
                  "original_graphchecker_seed": True},
        "target": {"check_site_id": check, "throw_site_id": throw},
        "artifacts": {"manifest": {"sha256": _sha(scope / "weave_manifest.json")},
                      "target_source": {"path": str(_source_file(
                          Path(profile["source_root"]), target["source_path"],
                          target["source_sha256"])),
                          "sha256": target["source_sha256"]},
                      "original_junit_source": {"path": str(_source_file(
                          Path(profile["source_root"]), junit["source_path"],
                          junit["source_sha256"])),
                          "sha256": junit["source_sha256"]}}})
    woven = healthy / "region-state-woven"
    artifacts = healthy / "recording-artifacts"
    weave_config = {"java": java,
        "jvm_args": [f"-Xmx{profile.get('weave_heap_mb', 8192)}m"],
        "input_classes": str(process), "output_classes": str(woven),
        "region_skeletons": str(skeletons),
        "dependency_classpath": os.pathsep.join(
            profile["soot_dependency_classpath"]),
        "tool_classpath": profile["native_fault_helper"],
        "native_fault_manifest": str(scope / "weave_manifest.json"),
        "recording_artifacts": str(artifacts),
        "communication_mappings": profile["communication_mappings"],
        "weave_mode": "region_state",
        "timeout_seconds": profile.get("weave_timeout_seconds", 1800)}
    weave_file = healthy / "native-weave-config.json"
    _atomic(weave_file, weave_config)
    _run("region-state-weave", [sys.executable, str(Path(
        weave.__file__).resolve()), "--config", str(weave_file)], output,
        weave_config["timeout_seconds"], os.environ.copy())
    verify = weave.verify_existing(weave_file)
    _atomic(healthy / "weave-verify.json", verify)
    _atomic(output / "recording-weave-receipt.json", {
        "schema_version": 1,
        "mode": "original_graphchecker_region_state_weave",
        "case_id": request["case_id"], "request_sha256": _digest(request),
        "engine_jar_sha256": _sha(weave.JAR),
        "input_classes": str(process),
        "input_classes_sha256": weave.class_tree_digest(process),
        "output_classes": str(woven),
        "output_classes_sha256": weave.class_tree_digest(woven)})
    test = junit["selector"]
    trace = healthy / "healthy-trace"
    work = healthy / "healthy-junit"
    for child in ("tmp", "data", "logs"):
        (work / child).mkdir(parents=True)
    plan = healthy / "healthy-fault-plan.json"
    _atomic(plan, {"faults": []})
    junit_cp = os.pathsep.join([str(woven), profile["native_fault_helper"],
                                str(weave.JAR), *profile["runtime_classpath"]])
    healthy_command = [java, f"-Xmx{profile.get('junit_heap_mb', 4096)}m", "-ea",
        f"-Djava.io.tmpdir={work / 'tmp'}", f"-Dtest.build.data={work / 'data'}",
        f"-Dhadoop.log.dir={work / 'logs'}",
        "-Dcausynth.trace.mode=region-state",
        f"-Dcausynth.trace.test={test}", "-cp", junit_cp,
        "edu.uva.liftlab.graphchecker.runtime.NativeHdfsJUnitRunner",
        junit["class"], junit["method"]]
    env = os.environ.copy()
    env.update(CAUSYNTH_TRACE_OUTPUT_DIR=str(trace), CAUSYNTH_TRACE_TEST=test,
               CAUSYNTH_STATIC_SCOPE_MAP=str(artifacts / "static_scope_map.jsonl"),
               MALLORY_NATIVE_FAULT_PLAN=str(plan),
               MALLORY_NATIVE_FAULT_EVENTS=str(healthy / "healthy-fault-events.jsonl"))
    started = time.monotonic()
    _run("healthy-junit", healthy_command, output,
         profile.get("junit_timeout_seconds", 600), env, work)
    _atomic(healthy / "healthy-run.json", {"status": 0, "junit": test,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "command": healthy_command})
    trace_manifest = _object(trace / "streaming_trace_manifest.json")
    if trace_manifest.get("status") != "CLOSED":
        raise ValueError("original HDFS healthy trace did not close")
    engine_cp = os.pathsep.join((str(weave.JAR),
        weave.DEPENDENCIES.read_text(encoding="utf-8").strip()))
    occurrence_file = healthy / "target-occurrence.json"
    common = ["--trace-dir", str(trace), "--test", test,
              "--candidate-graph", str(artifacts / graph.name),
              "--static-scope-map", str(artifacts / static_map.name),
              "--region-skeletons", str(artifacts / skeletons.name)]
    graph_jvm = [java, f"-Xmx{profile.get('graph_heap_mb', 4096)}m",
                 "-cp", engine_cp]
    _run("target-resolver", [*graph_jvm,
        "edu.uva.liftlab.graphchecker.runtime.MalloryTargetOccurrenceResolver",
        *common, "--check-site-id", check,
        "--output", str(occurrence_file)], output,
        profile.get("graph_timeout_seconds", 900))
    occurrence = _object(occurrence_file)
    if (occurrence.get("checkSiteId") != check or
            occurrence.get("test") != test or
            occurrence.get("fatalOutcome") is not False or
            occurrence.get("reachedEventCount", 0) < 1):
        raise ValueError("original HDFS target guard was not reached healthy")
    selector = occurrence["selectedOccurrenceAddress"]
    recorded = healthy / "healthy-recorded"
    scheduled = healthy / "healthy-scheduled"
    target_arg = ",".join((str(artifacts / graph.name),
                           str(artifacts / static_map.name),
                           str(artifacts / skeletons.name), str(recorded)))
    loop_bound = "-Dcausynth.loop.default.bound=3"
    _run("original-recorder", [java, graph_jvm[1], loop_bound, "-cp", engine_cp,
        "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
        "--trace-dir", str(trace), "--test", test,
        "--target", f"{request['case_id'].replace('-', '')}={target_arg}",
        "--target-occurrence", selector], output,
        profile.get("graph_timeout_seconds", 900))
    _run("original-scheduler", [java, graph_jvm[1], loop_bound, "-cp", engine_cp,
        "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler",
        "--region-plan", str(recorded / "concolic_region_plan.jsonl"),
        "--candidate-graph", str(artifacts / graph.name),
        "--static-scope-map", str(artifacts / static_map.name),
        "--output-dir", str(scheduled), "--max-jobs",
        str(profile["max_jobs"]), "--target-occurrence", selector], output,
        profile.get("graph_timeout_seconds", 900))
    with (scheduled / "execution_task_plan.jsonl").open(
            encoding="utf-8") as stream:
        has_task = any(line.strip() for line in stream)
    if not has_task:
        raise ValueError("original Scheduler produced no task")
    for stage in ("recorder", "scheduler"):
        _atomic(healthy / f"{stage}-run.json", {"status": 0})
    config = {"case_id": request["case_id"], "target_site": check,
        "target_throw": {"siteId": throw,
                         "exceptionClass": target["target_exception"]},
        "target_actor_names": [], "native_weave_config": str(weave_file),
        "recording": {"trace_dir": str(trace), "test_id": test,
                      "target_name": request["case_id"].replace("-", ""),
                      "candidate_graph": str(artifacts / graph.name),
                      "static_scope_map": str(artifacts / static_map.name),
                      "region_skeletons": str(artifacts / skeletons.name),
                      "target_occurrence": selector,
                      "max_jobs": profile["max_jobs"],
                      "graph_analysis_heap_mb": profile.get("graph_heap_mb", 4096),
                      "admission_timeout_seconds": profile.get(
                          "graph_timeout_seconds", 900),
                      "graph_analysis_timeout_seconds": profile.get(
                          "graph_timeout_seconds", 900),
                      "recorder_jvm_args": [loop_bound],
                      "scheduler_jvm_args": [loop_bound]},
        "junit": {"class": junit["class"], "method": junit["method"]},
        "runner": {"mode": "region_state", "zero_vm_java": java,
                   "main_class":
                       "edu.uva.liftlab.graphchecker.runtime.NativeHdfsJUnitRunner",
                   "classpath": [str(weave.JAR), profile["native_fault_helper"],
                                 *profile["runtime_classpath"]],
                   "jvm_args": [f"-Xmx{profile.get('junit_heap_mb', 4096)}m",
                                "-ea", "-Djava.io.tmpdir={trial_workdir}",
                                "-Dtest.build.data={trial_workdir}",
                                "-Dhadoop.log.dir={trial_workdir}"]},
        "budget": profile["budget"],
        "timeout_seconds": profile.get("junit_timeout_seconds", 600)}
    native._validate_config(config)
    _atomic(healthy / "campaign-config.json", config)
    _atomic(output / "case.json", config)
    gate = verify_existing(request, static, healthy)
    _atomic(output / "adapter-proof.json", {
        "schema_version": 1, "mode": PROOF_MODE,
        "case_id": request["case_id"], "request_sha256": _digest(request),
        "original_cluster_junit_verified": True,
        "scope_generated_by_original_graphchecker": True,
        "recording_closed": True,
        "junit": config["junit"],
        "source_evidence_paths": [str(_source_file(Path(profile["source_root"]),
            target["source_path"], target["source_sha256"])),
            str(_source_file(Path(profile["source_root"]),
            junit["source_path"], junit["source_sha256"]))],
        "static_scope_receipt_path": str(output / "static-scope-receipt.json"),
        "recording_weave_receipt_path": str(
            output / "recording-weave-receipt.json"),
        "target_occurrence_receipt_path": str(occurrence_file),
        "target_occurrence_receipt_sha256": _sha(occurrence_file)})
    return gate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("request", "verify-existing", "prepare"))
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--alternate-junit-attestation", type=Path)
    parser.add_argument("--selected-check-mapping")
    parser.add_argument("--static-root", type=Path)
    parser.add_argument("--healthy-root", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.request is None or args.profile is None or args.out is None:
            parser.error("prepare requires request, profile, and out")
        print(json.dumps(prepare(args.request, args.profile, args.out),
                         sort_keys=True))
        return
    if args.inventory is None or args.case_id is None:
        parser.error("request and verify-existing require inventory and case ID")
    request = request_from_inventory(args.inventory, args.case_id,
                                     args.alternate_junit_attestation,
                                     args.selected_check_mapping)
    if args.command == "request":
        result = request
    else:
        if args.static_root is None or args.healthy_root is None:
            parser.error("verify-existing requires static and healthy roots")
        result = verify_existing(request, args.static_root, args.healthy_root)
    if args.out is not None:
        if args.out.exists():
            raise ValueError("refusing to overwrite native preparation receipt")
        _atomic(args.out, result)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
