#!/usr/bin/env python3
"""Resume a target-anchored fault campaign for one original cluster JUnit test.

This controller does not classify any observation as a new bug. It records
reproducible target-exception candidates for separate source review.
"""

from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import gzip
import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .events import TraceError, load_trace
from .feedback import analyze, digest
from .junit import collect_junit_receipt, runner_kind
from .scheduler import mutate, pick_next, score, sequence_signature

SCHEMA = 1


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def validate_config(config: dict[str, Any]) -> None:
    required = ("case_id", "system", "cluster_test", "command", "cwd", "target", "budget")
    for key in required:
        if key not in config:
            raise ValueError(f"config missing {key}")
    if not isinstance(config["command"], list) or not config["command"] or not all(
            isinstance(item, str) and item for item in config["command"]):
        raise ValueError("command must be a nonempty argv list; shell syntax is unsupported")
    if not Path(config["cwd"]).is_dir():
        raise ValueError(f"cwd does not exist: {config['cwd']}")
    target = config["target"]
    if not isinstance(target, dict) or not isinstance(target.get("exception_class"), str):
        raise ValueError("target needs exception_class")
    check_sites = target.get("check_sites", [target.get("site")])
    throw_site = target.get("throw_site", target.get("site"))
    if (not isinstance(check_sites, list) or not check_sites or
            not all(isinstance(x, str) and x for x in check_sites) or
            not isinstance(throw_site, str) or not throw_site):
        raise ValueError("target needs exact check_sites and throw_site")
    budget = config["budget"]
    if not isinstance(budget, dict) or not all(
            isinstance(budget.get(k), int) and budget[k] > 0
            for k in ("trials", "seconds", "max_faults_per_trial", "trial_timeout_seconds")):
        raise ValueError("budget needs positive integer trials, seconds, max_faults_per_trial, trial_timeout_seconds")
    if "fault_types" in config and (not isinstance(config["fault_types"], list) or
                                    not all(isinstance(x, str) for x in config["fault_types"])):
        raise ValueError("fault_types must be a list")
    if config.get("agent_transport", "java_tool_options") not in \
            {"java_tool_options", "surefire_argline"}:
        raise ValueError("agent_transport must be java_tool_options or surefire_argline")
    if config.get("agent_transport") == "surefire_argline" and not config.get("agent_jar"):
        raise ValueError("surefire_argline requires agent_jar")
    property_name = config.get("agent_arg_property", "argLine")
    if not isinstance(property_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", property_name):
        raise ValueError("agent_arg_property must be a Maven property name")
    validated = config.get("validated_recovery_sites", [])
    if not isinstance(validated, list):
        raise ValueError("validated_recovery_sites must be a list")
    validated_names: set[str] = set()
    for row in validated:
        if (not isinstance(row, dict) or not isinstance(row.get("site"), str) or
                not row["site"] or not isinstance(row.get("evidence"), list) or
                not row["evidence"]):
            raise ValueError("each validated recovery site needs site and evidence")
        if row["site"] in validated_names:
            raise ValueError("validated recovery sites must be unique")
        validated_names.add(row["site"])
        for receipt in row["evidence"]:
            if (not isinstance(receipt, dict) or
                    not isinstance(receipt.get("trial_result"), str) or
                    not Path(receipt["trial_result"]).is_absolute() or
                    not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256", "")))):
                raise ValueError("recovery evidence needs absolute trial_result and sha256")
    interval = config.get("validated_recovery_exploration_interval", 5)
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 2:
        raise ValueError("validated_recovery_exploration_interval must be at least 2")
    if not isinstance(config.get("allow_local_timeline_doors", False), bool):
        raise ValueError("allow_local_timeline_doors must be boolean")
    breadth_interval = config.get("single_fault_breadth_interval")
    if breadth_interval is not None and (
            not isinstance(breadth_interval, int) or
            isinstance(breadth_interval, bool) or breadth_interval < 2):
        raise ValueError("single_fault_breadth_interval must be at least 2")


def verify_validated_recovery_sites(config: dict[str, Any]) -> None:
    """Only prioritize pilot doors backed by pinned effective target-retaining trials."""
    for row in config.get("validated_recovery_sites", []):
        site = row["site"]
        for receipt in row["evidence"]:
            path = Path(receipt["trial_result"]).resolve()
            if _sha256(path) != receipt["sha256"]:
                raise ValueError(f"recovery evidence digest mismatch: {path}")
            trial = read_json(path)
            feedback = trial.get("feedback", {})
            plan = trial.get("plan", [])
            if (trial.get("case_id") != config["case_id"] or
                    not isinstance(plan, list) or not plan or
                    any(not isinstance(fault, dict) or
                        not isinstance(fault.get("point"), dict) or
                        fault["point"].get("site") != site for fault in plan) or
                    feedback.get("all_faults_effective") is not True or
                    feedback.get("fault_identity_valid") is not True or
                    feedback.get("target_reached") is not True):
                raise ValueError(f"recovery evidence is not an exact target-retaining fault trial: {path}")
            expected_class_hash = config.get("expected_target_class_sha256")
            if (expected_class_hash and trial.get("site_catalog_validation", {})
                    .get("observed_target_class_sha256") != expected_class_hash):
                raise ValueError(f"recovery evidence used a different target class: {path}")


def load_static_frontier(config: dict[str, Any]) -> None:
    path_text = config.get("static_frontier_file")
    if not path_text:
        return
    path = Path(path_text).resolve()
    frontier = read_json(path)
    if frontier.get("analysis_kind") != "conservative_static_frontier":
        raise ValueError(f"not a Mallory static frontier: {path}")
    if frontier.get("case_id") not in (None, "", config["case_id"]):
        raise ValueError("static frontier case_id differs from campaign")
    rows = frontier.get("frontier")
    if not isinstance(rows, list):
        raise ValueError("static frontier lacks frontier rows")
    config["static_frontier_sha256"] = _sha256(path)
    config["static_fault_locations"] = [
        {"class": row["class"], "method": row["method"], "line": row["line"],
         "kind": row.get("kind"), "evidence": row.get("evidence", [])}
        for row in rows if isinstance(row, dict) and isinstance(row.get("class"), str)
        and isinstance(row.get("method"), str) and isinstance(row.get("line"), int)
        and row["line"] > 0]


def _fresh_state(config: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "case_id": config["case_id"],
            "config_digest": digest(config), "created_at": time.time(),
            "updated_at": time.time(), "status": "running", "next_trial": 1,
            "running": None, "queue": [], "seen_sequences": [], "coverage_ids": [],
            "closure_coverage_ids": [], "edge_fingerprints": [], "tried_sites": [],
            "completed_trials": [], "elapsed_seconds": 0.0,
            "target_exception_candidates": [], "reproduced_candidates": [],
            "runtime_attestation": None}


def _named_node(node: Any) -> bool:
    return isinstance(node, str) and node not in ("", "unknown", "null", "None")


def _healthy_attestation(config: dict[str, Any], result: dict[str, Any],
                         bound_nodes: list[str]) -> dict[str, Any]:
    feedback = result["feedback"]
    catalog = result["site_catalog_validation"]
    reasons: list[str] = []
    if feedback.get("status") != "observed":
        reasons.append("healthy_run_not_observed")
    if not bound_nodes:
        reasons.append("no_named_target_actor")
    if not any(row.get("node") in bound_nodes for row in feedback.get("target_closures", [])):
        reasons.append("no_named_target_region")
    if feedback.get("target_threw"):
        reasons.append("healthy_target_threw")
    if feedback.get("eligible_doors_before_target", 0) <= 0:
        reasons.append("no_injectable_door")
    if config.get("agent_jar"):
        if catalog.get("valid") is not True:
            reasons.append("exact_site_catalog_invalid")
        if not config.get("expected_target_class_sha256"):
            reasons.append("target_class_hash_unpinned")
        elif catalog.get("class_hash_match") is not True:
            reasons.append("loaded_target_class_hash_mismatch")
        if len(catalog.get("target_class_loader_ids", [])) != 1:
            reasons.append("target_class_loader_ambiguous")
    return {"valid": not reasons, "reasons": reasons,
            "bound_nodes": bound_nodes,
            "target_identity_gap_count": len(feedback.get("target_identity_gaps", [])),
            "exact_site_catalog_valid": catalog.get("valid"),
            "site_catalog_sha256": result.get("site_catalog_sha256"),
            "expected_target_class_sha256": config.get("expected_target_class_sha256"),
            "observed_target_class_sha256": catalog.get("observed_target_class_sha256"),
            "target_class_loader_ids": catalog.get("target_class_loader_ids", []),
            "eligible_doors_before_target": feedback.get("eligible_doors_before_target", 0)}


def _alive_process_group(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _compress_evidence(path: Path, *, minimum_bytes: int = 0) -> dict[str, Any]:
    """Replace raw evidence only after an fsynced, verifiable gzip exists."""
    if not path.is_file():
        return {"raw_path": None, "gzip_path": None,
                "raw_sha256": None, "gzip_sha256": None}
    raw_size = path.stat().st_size
    raw_hash = _sha256(path)
    if raw_size < minimum_bytes:
        return {"raw_path": path.name, "gzip_path": None,
                "raw_bytes": raw_size, "raw_sha256": raw_hash,
                "gzip_bytes": None, "gzip_sha256": None}
    compressed = path.with_name(path.name + ".gz")
    temporary = path.with_name(f".{path.name}.gz.{os.getpid()}.tmp")
    try:
        with path.open("rb") as source, temporary.open("wb") as sink:
            with gzip.GzipFile(fileobj=sink, mode="wb", filename="", mtime=0) as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            sink.flush()
            os.fsync(sink.fileno())
        # Check the entire stream before removing the sole raw copy.
        verifier = hashlib.sha256()
        with gzip.open(temporary, "rb") as restored:
            while chunk := restored.read(1024 * 1024):
                verifier.update(chunk)
        if verifier.hexdigest() != raw_hash:
            raise IOError(f"gzip round-trip hash mismatch: {path}")
        os.replace(temporary, compressed)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        path.unlink()
        return {"raw_path": None, "gzip_path": compressed.name,
                "raw_bytes": raw_size, "raw_sha256": raw_hash,
                "gzip_bytes": compressed.stat().st_size,
                "gzip_sha256": _sha256(compressed)}
    finally:
        temporary.unlink(missing_ok=True)


def _validate_site_catalog(path: Path, target: dict[str, Any], required: bool,
                           expected_class_sha256: str | None = None) -> dict[str, Any]:
    if not required:
        return {"required": False, "valid": None, "reason": "disabled"}
    if not path.is_file():
        return {"required": True, "valid": False, "reason": "catalog_missing"}
    try:
        trace = load_trace(path)
        if trace.incomplete_last_line:
            return {"required": True, "valid": False, "reason": "catalog_incomplete"}
        catalog = trace.events
    except TraceError as exc:
        return {"required": True, "valid": False,
                "reason": "catalog_invalid", "error": str(exc)}
    check_sites = target.get("check_sites", [target.get("site")])
    throw_site = target.get("throw_site", target.get("site"))
    checks = {e.get("site") for e in catalog if e.get("type") == "TARGET_CHECK"}
    throws = {e.get("site") for e in catalog if e.get("type") == "TARGET_THROW"}
    missing_checks = sorted(site for site in check_sites if site not in checks)
    missing_throw = throw_site not in throws
    target_counts = Counter((e.get("type"), e.get("site")) for e in catalog
                            if e.get("type") in {"TARGET_CHECK", "TARGET_THROW"})
    duplicates = sorted(site for kind, site in target_counts
                        if ((kind == "TARGET_CHECK" and site in check_sites) or
                            (kind == "TARGET_THROW" and site == throw_site))
                        and target_counts[(kind, site)] > 1)
    target_class = str(throw_site).split("#", 1)[0]
    loaded_rows = [e for e in catalog if e.get("class_name") == target_class]
    hashes = sorted({str(e["bytecode_sha256"]) for e in loaded_rows
                     if isinstance(e.get("bytecode_sha256"), str)})
    loader_ids = sorted({str(e["class_loader_id"]) for e in loaded_rows
                         if isinstance(e.get("class_loader_id"), str)})
    class_hash_match = (len(hashes) == 1 and hashes[0] == expected_class_sha256 and
                        len(loader_ids) == 1) if expected_class_sha256 else None
    valid = (not missing_checks and not missing_throw and not duplicates and
             (class_hash_match is not False))
    reason = ("ok" if valid else "target_site_ambiguous" if duplicates else
              "target_site_not_woven" if missing_checks or missing_throw else
              "target_class_identity_mismatch")
    return {"required": True, "valid": valid,
            "missing_check_sites": missing_checks,
            "missing_throw_site": throw_site if missing_throw else None,
            "duplicate_target_sites": duplicates,
            "target_class": target_class,
            "expected_target_class_sha256": expected_class_sha256,
            "observed_target_class_sha256": hashes[0] if len(hashes) == 1 else None,
            "observed_target_class_hashes": hashes,
            "target_class_loader_ids": loader_ids,
            "class_hash_match": class_hash_match,
            "catalog_rows": len(catalog), "reason": reason}


def _prepare_env(config: dict[str, Any], trial: Path, trial_id: int) -> tuple[dict[str, str], str | None]:
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in config.get("env", {}).items()})
    env.update({"MALLORY_EVENT_FILE": str(trial / "events.jsonl"),
                "MALLORY_PLAN_FILE": str(trial / "plan.json"),
                "MALLORY_SITE_CATALOG": str(trial / "sites.jsonl"),
                "MALLORY_RUN_ID": f"{config['case_id']}-r{trial_id:04d}"})
    if config.get("site_file"):
        env["MALLORY_SITE_FILE"] = str(Path(config["site_file"]).resolve())
    agent_jar = config.get("agent_jar")
    option = None
    if agent_jar:
        jar = Path(agent_jar).resolve()
        if not jar.is_file():
            raise FileNotFoundError(jar)
        properties = trial / "agent.properties"
        rows = {"events": str(trial / "events.jsonl"),
                "site.catalog": str(trial / "sites.jsonl"),
                "run.id": env["MALLORY_RUN_ID"],
                "fault.plan": str(trial / "plan.json")}
        if config.get("site_file"):
            rows["site.file"] = env["MALLORY_SITE_FILE"]
        if config.get("agent_include"):
            rows["include"] = ",".join(config["agent_include"])
        for key, value in config.get("agent_properties", {}).items():
            if not isinstance(key, str) or not isinstance(value, (str, bool, int)):
                raise ValueError("agent_properties must contain scalar string keys and values")
            if any(c in key + str(value) for c in "\r\n="):
                raise ValueError("agent_properties contains a newline or equals sign")
            rows[key] = str(value).lower() if isinstance(value, bool) else str(value)
        properties.write_text("".join(f"{k}={v}\n" for k, v in rows.items()), encoding="utf-8")
        option = f"-javaagent:{jar}=config={properties}"
        if config.get("agent_transport", "java_tool_options") == "java_tool_options":
            env["JAVA_TOOL_OPTIONS"] = (env.get("JAVA_TOOL_OPTIONS", "") + " " + option).strip()
    return env, option


def _run_trial(config: dict[str, Any], out: Path, trial_id: int,
               plan: list[dict[str, Any]], save_running,
               target_binding: dict[str, Any] | None) -> dict[str, Any]:
    trial = out / "trials" / f"r{trial_id:04d}"
    trial.mkdir(parents=True, exist_ok=True)
    atomic_json(trial / "plan.json", {"schema_version": SCHEMA, "faults": plan})
    env, agent_option = _prepare_env(config, trial, trial_id)
    argv = [item.format(event_file=trial / "events.jsonl", plan_file=trial / "plan.json",
                        run_id=env["MALLORY_RUN_ID"], site_file=env.get("MALLORY_SITE_FILE", ""),
                        trial_dir=trial)
            for item in config["command"]]
    if config.get("agent_transport") == "surefire_argline":
        assert agent_option is not None
        property_name = config.get("agent_arg_property", "argLine")
        prefix = "-D" + property_name + "="
        existing = [index for index, value in enumerate(argv) if value.startswith(prefix)]
        if len(existing) > 1:
            raise ValueError(f"multiple {prefix} values in Maven command")
        if existing:
            index = existing[0]
            argv[index] += " " + agent_option
        else:
            argv.append(prefix + agent_option)
    junit_runner = runner_kind(argv)
    report_suffix = None
    if junit_runner == "surefire_xml":
        # A unique report name prevents a previous trial's XML from making a
        # zero-test invocation look healthy, even after an interrupted run.
        report_suffix = f"mallory_{trial_id:04d}_{uuid.uuid4().hex}"
        argv.append(f"-Dsurefire.reportNameSuffix={report_suffix}")
    elif junit_runner == "solr_junit_wrapper":
        (trial / "pilot-result.json").unlink(missing_ok=True)
        (trial / "junit.log").unlink(missing_ok=True)
    started = time.time()
    timeout = int(config["budget"]["trial_timeout_seconds"])
    timed_out = False
    with (trial / "stdout.log").open("wb") as stdout, (trial / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=config["cwd"], env=env, stdout=stdout,
                                   stderr=stderr, start_new_session=True)
        save_running(process.pid)
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            return_code = process.returncode
    elapsed = round(time.time() - started, 3)
    junit_receipt = collect_junit_receipt(trial, argv, Path(config["cwd"]),
                                          return_code, report_suffix,
                                          config.get("cluster_test"))
    atomic_json(trial / "junit-receipt.json", junit_receipt)
    trace_error = None
    try:
        trace = load_trace(trial / "events.jsonl")
        target = {**config["target"], **(target_binding or {})}
        feedback = analyze(trace, target, plan,
                           return_code=return_code, timed_out=timed_out,
                           allow_local_timeline_doors=config.get("allow_local_timeline_doors", False),
                           reject_coarse_roots=config.get("reject_coarse_roots", False))
    except TraceError as exc:
        trace_error = str(exc)
        feedback = {"status": "trace_invalid", "target_reached": False,
                    "target_exception_candidate": False, "coverage_ids": [],
            "closure_coverage_ids": [], "closure_edges": [], "doors": [],
                    "all_faults_applied": False, "all_faults_effective": False}
    catalog_validation = _validate_site_catalog(
        trial / "sites.jsonl", config["target"],
        bool(config.get("require_site_catalog", bool(config.get("agent_jar")))),
        config.get("expected_target_class_sha256"))
    if catalog_validation["valid"] is False:
        feedback["status"] = catalog_validation["reason"]
        feedback["target_exception_candidate"] = False
    if trial_id == 0:
        junit_status = junit_receipt["status"]
        production = config["system"].lower() in {"hdfs", "hbase", "solr", "zookeeper"}
        if junit_status != "passed" and (production or junit_status != "not_applicable"):
            feedback["status"] = ("healthy_no_tests" if junit_status == "no_tests" else
                                  "healthy_junit_runner_unrecognized"
                                  if junit_status == "not_applicable" else
                                  "healthy_junit_" + junit_status)
            feedback["target_exception_candidate"] = False
    event_evidence = _compress_evidence(trial / "events.jsonl")
    stdout_evidence = _compress_evidence(trial / "stdout.log", minimum_bytes=1024 * 1024)
    stderr_evidence = _compress_evidence(trial / "stderr.log", minimum_bytes=1024 * 1024)
    result = {"schema_version": SCHEMA, "case_id": config["case_id"],
              "trial_id": trial_id, "started_at": started, "elapsed_seconds": elapsed,
              "dispatch_attempt_id": os.environ.get("MALLORY_ATTEMPT_ID"),
              "return_code": return_code, "timed_out": timed_out,
              "junit_validation": junit_receipt,
              "junit_receipt_sha256": _sha256(trial / "junit-receipt.json"),
              "plan": plan, "feedback": feedback, "trace_error": trace_error,
              "site_catalog_validation": catalog_validation,
              "events_sha256": event_evidence["raw_sha256"],
              "events_evidence": event_evidence,
              "site_catalog_sha256": _sha256(trial / "sites.jsonl"),
              "stdout_sha256": stdout_evidence["raw_sha256"],
              "stdout_evidence": stdout_evidence,
              "stderr_sha256": stderr_evidence["raw_sha256"],
              "stderr_evidence": stderr_evidence}
    atomic_json(trial / "result.json", result)
    return result


def _apply_result(state: dict[str, Any], config: dict[str, Any], result: dict[str, Any],
                  item: dict[str, Any] | None) -> None:
    feedback = result["feedback"]
    trial_id = result["trial_id"]
    if trial_id in state["completed_trials"]:
        return
    old_coverage = set(state["coverage_ids"])
    old_closure = set(state["closure_coverage_ids"])
    old_edges = set(state["edge_fingerprints"])
    new_coverage = set(feedback.get("coverage_ids", []))
    new_closure = set(feedback.get("closure_coverage_ids", []))
    new_edges = {digest([edge["source"], edge["target"], edge["kind"], edge["certainty"]])
                 for edge in feedback.get("closure_edges", [])}
    result["novelty"] = {"coverage": len(new_coverage - old_coverage),
                         "closure_coverage": len(new_closure - old_closure),
                         "closure_edges": len(new_edges - old_edges)}
    result["selection_reason"] = item.get("selection_reason") if item else "healthy_seed"
    atomic_json(Path(state["out"]) / "trials" / f"r{trial_id:04d}" / "result.json", result)
    state["coverage_ids"] = sorted(old_coverage | new_coverage)
    state["closure_coverage_ids"] = sorted(old_closure | new_closure)
    state["edge_fingerprints"] = sorted(old_edges | new_edges)
    state["elapsed_seconds"] += result["elapsed_seconds"]
    state["completed_trials"].append(trial_id)
    state["running"] = None
    if result["plan"]:
        state["tried_sites"] = sorted(set(state["tried_sites"]) |
                                      {str(fault["point"]["site"]) for fault in result["plan"]})
    if feedback.get("target_exception_candidate"):
        state["target_exception_candidates"].append(trial_id)
        if item and item.get("replay_of"):
            prior = item["replay_of"]
            successful = [x for x in state["completed_trials"] if x == prior]
            if successful:
                state["reproduced_candidates"].append({"first_trial": prior,
                                                        "replay_trial": trial_id})
        elif item is not None:
            for _ in range(int(config.get("candidate_replays", 2))):
                state["queue"].insert(0, {"faults": result["plan"],
                                          "signature": sequence_signature(result["plan"]),
                                          "selection_reason": "candidate_replay",
                                          "replay_of": trial_id, "priority": 1000.0,
                                          "queued_at": trial_id})

    should_expand = ((trial_id == 0 and feedback.get("status") == "observed" and
                      feedback.get("target_reached") and not feedback.get("target_threw")) or
                     (trial_id > 0 and feedback.get("all_faults_effective") and
                      feedback.get("target_reached")))
    if should_expand and not (item and item.get("replay_of")):
        seen = set(state["seen_sequences"])
        for candidate in mutate(result["plan"], feedback, config):
            signature = candidate["signature"]
            if signature in seen:
                continue
            candidate["priority"] = score(candidate, {**feedback, "novelty": result["novelty"]},
                                          set(state["tried_sites"]), len(state["queue"]))
            candidate["queued_at"] = trial_id
            state["queue"].append(candidate)
            seen.add(signature)
        max_queue = int(config.get("max_queue", 5000))
        if max_queue <= 0:
            raise ValueError("max_queue must be positive")
        state["queue"].sort(key=lambda candidate: (-candidate["priority"],
                                                   candidate["queued_at"],
                                                   candidate["signature"]))
        if len(state["queue"]) > max_queue:
            state["queue"] = state["queue"][:max_queue]
        state["seen_sequences"] = sorted(seen)
    if trial_id == 0 and not should_expand:
        state["status"] = "healthy_seed_invalid"
    if trial_id == 0 and should_expand:
        instances = feedback.get("target_instances", [])
        nodes = sorted({instance["node"] for instance in instances
                        if _named_node(instance.get("node"))})
        state["target_binding"] = {"nodes": nodes} if nodes else None
        state["runtime_attestation"] = _healthy_attestation(config, result, nodes)
        if not nodes:
            state["status"] = "healthy_node_identity_missing"
        elif not feedback.get("doors"):
            state["status"] = "healthy_no_injectable_door"
        elif (config.get("agent_jar") and not state.get("calibration_only") and
              not state["runtime_attestation"]["valid"]):
            state["status"] = "healthy_attestation_failed"
        if state["status"] != "running":
            state["queue"].clear()


def _write_summary(out: Path, state: dict[str, Any], config: dict[str, Any]) -> None:
    trial_rows = []
    for trial_id in state["completed_trials"]:
        path = out / "trials" / f"r{trial_id:04d}" / "result.json"
        if not path.is_file():
            raise RuntimeError(f"checkpoint references missing trial result: {path}")
        row = read_json(path)
        feedback = row["feedback"]
        trial_rows.append({"trial_id": trial_id, "result": str(path.relative_to(out)),
                           "dispatch_attempt_id": row.get("dispatch_attempt_id"),
                           "selection_reason": row.get("selection_reason"),
                           "duration_seconds": row["elapsed_seconds"],
                           "status": feedback["status"],
                           "junit_status": row.get("junit_validation", {}).get("status"),
                           "junit_tests": row.get("junit_validation", {}).get("tests"),
                           "junit_failures": row.get("junit_validation", {}).get("failures"),
                           "junit_errors": row.get("junit_validation", {}).get("errors"),
                           "junit_skipped": row.get("junit_validation", {}).get("skipped"),
                           "observed_door_events": feedback.get("observed_door_events"),
                           "eligible_doors_before_target": feedback.get("eligible_doors_before_target"),
                           "local_timeline_doors": feedback.get("local_timeline_doors"),
                           "all_faults_matched": feedback.get("all_faults_matched", False),
                           "all_faults_applied": feedback.get("all_faults_applied", False),
                           "all_faults_effective": feedback.get("all_faults_effective"),
                           "target_reached": feedback.get("target_reached", False),
                           "target_exception_candidate": feedback.get("target_exception_candidate", False),
                           "novelty": row.get("novelty", {})})
    fault_trials = [row for row in trial_rows if row["trial_id"] > 0]
    strict_known = all(row["all_faults_effective"] is not None for row in fault_trials)
    summary = {"schema_version": SCHEMA, "case_id": config["case_id"],
               "system": config["system"], "cluster_test": config["cluster_test"],
               "exact_check_location": config.get("exact_check_location"),
               "target": config["target"], "status": state["status"],
               "calibration_only": state.get("calibration_only", False),
               "dispatch_attempt_ids": state.get("dispatch_attempt_ids", []),
               "last_dispatch_attempt_id": state.get("last_dispatch_attempt_id"),
               "target_binding": state.get("target_binding"),
               "target_node_named": bool((state.get("target_binding") or {}).get("nodes")),
               "runtime_attestation": state.get("runtime_attestation"),
               "healthy_junit_validation": (
                   read_json(out / "trials/r0000/result.json").get("junit_validation")
                   if 0 in state["completed_trials"] else None),
               "target_identity_gaps": (
                   read_json(out / "trials/r0000/result.json").get("feedback", {})
                   .get("target_identity_gaps", [])
                   if 0 in state["completed_trials"] else []),
               "healthy_observed_door_events": (trial_rows[0]["observed_door_events"]
                                                if trial_rows and trial_rows[0]["trial_id"] == 0 else None),
               "healthy_eligible_doors": (trial_rows[0]["eligible_doors_before_target"]
                                          if trial_rows and trial_rows[0]["trial_id"] == 0 else None),
               "healthy_local_timeline_doors": (trial_rows[0]["local_timeline_doors"]
                                                if trial_rows and trial_rows[0]["trial_id"] == 0 else None),
               "duration_seconds": round(state["elapsed_seconds"], 3),
               "healthy_seed_valid": (bool(trial_rows) and trial_rows[0]["status"] == "observed"
                                      and state.get("target_binding") is not None
                                      and state["status"] not in
                                      {"healthy_node_identity_missing", "healthy_seed_ambiguous",
                                       "healthy_no_injectable_door", "healthy_attestation_failed"}),
               "fault_trials_completed": len(fault_trials),
               "strict_injected_trials": (sum(row["all_faults_effective"]
                                               for row in fault_trials) if strict_known else None),
               "strict_target_trials": (sum(row["all_faults_effective"] and row["target_reached"]
                                             for row in fault_trials) if strict_known else None),
               "target_reached_trials": sum(row["target_reached"] for row in fault_trials),
               "exact_exception_trials": sum(row["target_exception_candidate"]
                                             for row in fault_trials),
               "target_exception_candidate_trials": state["target_exception_candidates"],
               "reproduced_candidates": state["reproduced_candidates"],
               "coverage_ids_seen": len(state["coverage_ids"]),
               "closure_coverage_ids_seen": len(state["closure_coverage_ids"]),
               "closure_edge_fingerprints_seen": len(state["edge_fingerprints"]),
               "source_review_status": "not_reviewed", "new_bug": None,
               "trials": trial_rows,
               "evidence": {"config": "config.json", "checkpoint": "checkpoint.json",
                            "trial_root": "trials/"}}
    atomic_json(out / "result.json", summary)


def run(config_path: Path, out: Path, *, calibration_only: bool = False) -> dict[str, Any]:
    config = read_json(config_path)
    validate_config(config)
    load_static_frontier(config)
    verify_validated_recovery_sites(config)
    calibration_only = (calibration_only or
                        (bool(config.get("calibration_only", False)) and
                         not bool(config.get("auto_promote_if_healthy", False))))
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(out / ".campaign.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(lock_fd)
        raise RuntimeError(f"campaign already running: {out}") from exc
    try:
        state_path = out / "checkpoint.json"
        if state_path.exists():
            state = read_json(state_path)
            if state.get("config_digest") != digest(config):
                raise ValueError("config changed; use a new output directory")
            if calibration_only and any(x > 0 for x in state.get("completed_trials", [])):
                raise ValueError("calibration-only mode cannot reuse a fault-trial campaign")
        else:
            state = _fresh_state(config)
            state["out"] = str(out)
            state["calibration_only"] = calibration_only
            atomic_json(out / "config.json", config)
            atomic_json(state_path, state)
        if state.get("calibration_only") != calibration_only:
            raise ValueError("calibration-only mode changed; use a new output directory")

        attempt_id = os.environ.get("MALLORY_ATTEMPT_ID")
        if attempt_id:
            attempts = state.setdefault("dispatch_attempt_ids", [])
            if attempt_id not in attempts:
                attempts.append(attempt_id)
            state["last_dispatch_attempt_id"] = attempt_id
            atomic_json(state_path, state)

        _write_summary(out, state, config)

        while state["status"] == "running":
            pending = state.get("running")
            if pending:
                trial_id = pending["trial_id"]
                result_path = out / "trials" / f"r{trial_id:04d}" / "result.json"
                if result_path.is_file():
                    _apply_result(state, config, read_json(result_path), pending.get("item"))
                    state["updated_at"] = time.time()
                    atomic_json(state_path, state)
                    _write_summary(out, state, config)
                    continue
                if _alive_process_group(pending.get("pid")):
                    raise RuntimeError(f"trial r{trial_id:04d} process group still alive; refusing duplicate run")
                # The previous controller died without a complete result.
                # Preserve its evidence and retry this same plan in a new trial.
                interrupted = out / "trials" / f"r{trial_id:04d}"
                if interrupted.exists():
                    archive = out / "interrupted" / f"r{trial_id:04d}-{int(time.time())}"
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    interrupted.rename(archive)
                state["running"] = None
                state["next_trial"] = trial_id
                if pending.get("item") is not None:
                    state["queue"].insert(0, pending["item"])
                atomic_json(state_path, state)

            if calibration_only and 0 in state["completed_trials"]:
                state["status"] = "calibration_complete"
                break
            if 0 in state["completed_trials"] and config.get("agent_jar") and (
                    not config.get("auto_promote_if_healthy") or
                    not (state.get("runtime_attestation") or {}).get("valid")):
                state["status"] = "fault_trials_not_attested"
                break
            fault_trials = sum(x > 0 for x in state["completed_trials"])
            budget = config["budget"]
            if (fault_trials >= budget["trials"] or
                    state["elapsed_seconds"] >= budget["seconds"]):
                state["status"] = "budget_exhausted"
                break
            if 0 not in state["completed_trials"]:
                trial_id, item, plan = 0, None, []
            elif not state["queue"]:
                state["status"] = "queue_exhausted"
                break
            else:
                item = pick_next(state["queue"], state["next_trial"], fault_trials,
                                 config)
                trial_id, plan = state["next_trial"], item["faults"]
                state["next_trial"] += 1

            state["running"] = {"trial_id": trial_id, "item": item, "pid": None}
            state["updated_at"] = time.time()
            atomic_json(state_path, state)

            def save_running(pid: int) -> None:
                state["running"]["pid"] = pid
                atomic_json(state_path, state)

            result = _run_trial(config, out, trial_id, plan, save_running,
                                state.get("target_binding"))
            _apply_result(state, config, result, item)
            state["updated_at"] = time.time()
            atomic_json(state_path, state)
            _write_summary(out, state, config)

        state["updated_at"] = time.time()
        atomic_json(state_path, state)
        _write_summary(out, state, config)
        return state
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--calibration-only", action="store_true",
                        help="run only healthy r0000; never select a fault trial")
    args = parser.parse_args(argv)
    state = run(args.config, args.out, calibration_only=args.calibration_only)
    print(json.dumps({key: state[key] for key in ("case_id", "status", "completed_trials",
                                                    "elapsed_seconds", "target_exception_candidates",
                                                    "reproduced_candidates")}, sort_keys=True))
    return 0 if state["status"] != "healthy_seed_invalid" else 2


if __name__ == "__main__":
    sys.exit(main())
