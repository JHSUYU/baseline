"""One resumable fault campaign over one original cluster JUnit test.

A healthy (fault-free) run records the selected I/O points the workload
executes; each becomes a one-fault sequence. Every trial reruns the same
JUnit with its sequence of exact fault selectors, reads the trace, and --
when the run kept the target check after its last fault -- queues the
sequence extended by one I/O point executed after that fault. The oracle is
the check's typed exception after the last applied fault, beyond what the
healthy run already threw. Everything a trial needs to resume is in
``<root>/<case>/state.json``; finished trials are never rerun.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
import signal
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .faults import Sequence, fault_family, retry_lost_target, sequence_id, \
    strict_applied_prefix, strict_injection
from .oracle import (fatal_guard_paths, selected_target_control_branches,
                     selected_target_throw_lines, throw_oracle, trace_feedback)
from .scheduler import (ADMITTED, budget_has_room, choose_next_sequence, completed_sequences,
                        enqueue_extensions, enqueue_seed, static_reason_priority)
from .selection import prepare as prepare_selection
from .trace import atomic_json, fingerprint

SCHEMA = 1
TERMINAL = {"quality_complete", "no_cluster_test", "source_excluded", "confirmed_bug"}
CANDIDATES = {"target_exception_candidate", "partial_target_exception_candidate"}
# Config keys a resumed campaign may change without invalidating its trials.
MUTABLE_CONFIG_KEYS = {"budget", "timeout_seconds", "archive_completed_trials",
                       "_static_io_priority", "_static_io_exceptions"}


# --- configuration ------------------------------------------------------------

def validate(config: dict[str, Any]) -> None:
    """Check a campaign config and fill in the budget defaults."""
    if config.get("selection_mode", "coverage_io") != "coverage_io":
        raise ValueError("only selection_mode=coverage_io is supported")
    needed = {"case_id", "system", "test_class", "test_method", "target", "cwd", "seed",
              "trial", "budget", "timeout_seconds", "workspaces"}
    missing = needed - config.keys()
    if missing:
        raise ValueError(f"missing config keys: {sorted(missing)}")
    _validate_target(config["target"])
    scope = config.get("io_scope", {})
    if not isinstance(scope, dict) or any(
            not isinstance(scope.get(key, []), list) or
            any(not isinstance(item, str) or not item for item in scope.get(key, []))
            for key in ("marker_prefixes", "site_ids")):
        raise ValueError("io_scope needs marker_prefixes/site_ids string lists")
    if not isinstance(config["trial"].get("command"), list):
        raise ValueError("trial.command must be an argv list, never a shell string")
    if (not config["seed"].get("command") and "elapsed_seconds" not in config["seed"] and
            "timing_manifest" not in config["seed"]):
        raise ValueError("precomputed seed requires elapsed_seconds or timing_manifest")
    _validate_budget(config["budget"])
    _validate_workspaces(config)


def _validate_target(target: dict[str, Any]) -> None:
    if not target.get("method") or "exception_type" not in target:
        raise ValueError("target requires exact method and exception_type field")
    if target["exception_type"] is not None and not isinstance(target["exception_type"], str):
        raise ValueError("target.exception_type must be an exact class or null")
    if target.get("throw_site_id"):
        throw_method = target["throw_site_id"].split("#u", 1)[0]
        if target.get("throw_method") and target["throw_method"] != throw_method:
            raise ValueError("throw_method differs from throw_site_id's method")
        target["throw_method"] = throw_method
    check_events = target.get("check_events")
    allowed = {"BRANCH", "CHECK_REACHED", "CALL_SITE_ENTER", "CALL_SITE_RETURN",
               "CALL_SITE_THROW"}
    if check_events is not None and (not isinstance(check_events, list) or not check_events or
                                     any(event not in allowed for event in check_events)):
        raise ValueError("target.check_events must list supported check events")
    check_site_ids = target.get("check_site_ids", [])
    if (not isinstance(check_site_ids, list) or
            any(not isinstance(site, str) or "#u" not in site for site in check_site_ids)):
        raise ValueError("target.check_site_ids needs exact site IDs")
    has_guards = "fatal_guards" in target or "fatal_guard_paths" in target
    if check_events and not (target.get("site_id") or check_site_ids or has_guards):
        raise ValueError("target.check_events requires exact check site IDs")
    throw_event = target.get("throw_event", "METHOD_EXIT_THROW")
    if throw_event not in {"METHOD_EXIT_THROW", "EXPLICIT_THROW", "CALL_SITE_THROW"}:
        raise ValueError("target.throw_event must name a supported throw event")
    if throw_event == "CALL_SITE_THROW" and not (target.get("throw_site_id") or
                                                 target.get("site_id")):
        raise ValueError("CALL_SITE_THROW requires throw_site_id or site_id")
    if throw_event == "EXPLICIT_THROW":
        explicit_site = target.get("explicit_throw_site_id")
        lines = target.get("explicit_throw_lines", [])
        if (not isinstance(lines, list) or
                any(not isinstance(line, int) or isinstance(line, bool) or line < 1
                    for line in lines)):
            raise ValueError("explicit_throw_lines needs positive source lines")
        if explicit_site is None and not lines:
            raise ValueError("EXPLICIT_THROW needs an exact site or selected lines")
        if explicit_site is not None:
            method = target.get("throw_method", target["method"])
            if not isinstance(explicit_site, str) or not explicit_site.startswith(method + "#"):
                raise ValueError("explicit_throw_site_id differs from throw_method")
            if target.get("throw_site_id") and explicit_site != target["throw_site_id"]:
                raise ValueError("explicit_throw_site_id differs from throw_site_id")
    if has_guards:
        fatal_guard_paths(target)
    excluded = target.get("coverage_exclude_sites", [])
    if (not isinstance(excluded, list) or
            any(not isinstance(site, str) or "#u" not in site for site in excluded)):
        raise ValueError("target.coverage_exclude_sites needs exact site IDs")
    prefixes = target.get("coverage_include_prefixes", [])
    if (not isinstance(prefixes, list) or
            any(not isinstance(prefix, str) or not prefix for prefix in prefixes)):
        raise ValueError("target.coverage_include_prefixes needs nonempty strings")
    methods = target.get("coverage_include_methods", [])
    if (not isinstance(methods, list) or
            any(not isinstance(method, str) or not method.startswith("<") for method in methods)):
        raise ValueError("target.coverage_include_methods needs Soot signatures")
    if has_guards and any(guard["siteId"] in excluded
                          for path in fatal_guard_paths(target) for guard in path):
        raise ValueError("cannot exclude a fatal target guard from coverage")


def _validate_budget(budget: dict[str, Any]) -> None:
    budget.setdefault("max_trials", 80)
    budget.setdefault("max_faults", 8)
    if budget["max_trials"] < 1 or budget["max_faults"] < 1:
        raise ValueError("budgets must be positive")
    if "min_target_retained_trials" in budget:
        if (not isinstance(budget["min_target_retained_trials"], int) or
                budget["min_target_retained_trials"] < 1 or
                not isinstance(budget.get("base_trials"), int) or
                not 1 <= budget["base_trials"] <= budget["max_trials"]):
            raise ValueError("adaptive budget needs positive target trials and valid base_trials")
    for name in ("max_unmatched_retries", "max_lost_target_retries"):
        if not isinstance(budget.get(name, 1), int) or budget.get(name, 1) < 0:
            raise ValueError(f"{name} must be nonnegative")


def _validate_workspaces(config: dict[str, Any]) -> None:
    workspaces = config["workspaces"]
    for name in ("system_test", "temp"):
        if name not in workspaces or not Path(workspaces[name]).is_absolute():
            raise ValueError(f"workspaces.{name} must be an absolute per-case path")
    paths = [Path(value).resolve() for value in workspaces.values()]
    if len(set(paths)) != len(paths):
        raise ValueError("per-case workspaces must differ")
    shared = [Path(value).resolve() for value in config.get("shared_readonly_roots", [])]
    for path in paths:
        if any(path == root or root in path.parents for root in shared):
            raise ValueError(f"workspace must be outside shared source: {path}")
    if Path(config["cwd"]).resolve() not in paths:
        raise ValueError("cwd must be a per-case workspace")


def config_identity(config: dict[str, Any]) -> str:
    """A checkpoint's identity: everything but the knobs that may grow on resume."""
    return fingerprint({key: value for key, value in config.items()
                        if key not in MUTABLE_CONFIG_KEYS})


def with_selection(config: dict[str, Any], case_dir: Path) -> dict[str, Any]:
    """The config with its Soot selection applied to target, I/O scope and priorities."""
    selection = prepare_selection(config, case_dir)
    if selection is None:
        return config
    lines = selected_target_throw_lines(selection, config["target"])
    target = {**config["target"], "coverage_include_methods": selection["coverage_methods"]}
    if lines and "throw_event" not in target:
        target.update(throw_oracle(selection, target, lines))
    controls = (selected_target_control_branches(selection, target, lines)
                if target.get("check_events") == ["CHECK_REACHED"] else [])
    io_calls = selection["io_calls"]
    config = {**config, "target": target,
              "io_scope": {"site_ids": [row["site_id"] for row in io_calls]},
              "_static_io_priority": {row["site_id"]: static_reason_priority(
                  row.get("selection_reason", "")) for row in io_calls},
              "_static_io_exceptions": {row["site_id"]: row.get("exception_candidates", [])
                                        for row in io_calls if row.get("exception_candidates")},
              "_static_selection_digest": selection.get("input_digest",
                                                        selection.get("artifact_sha256")),
              "_static_selection_artifact": selection["artifact_path"]}
    if controls:
        # Observe the Soot branches controlling the typed throw as checks too.
        # A checkpoint started before this keeps its own observation contract.
        check_target = {**target, "check_events": ["CHECK_REACHED", "BRANCH"],
                        "check_site_ids": sorted(set(
                            target.get("check_site_ids", []) + controls +
                            ([target["site_id"]] if target.get("site_id") else [])))}
        checkpoint = case_dir / "state.json"
        if (not checkpoint.is_file() or json.loads(checkpoint.read_text()).get(
                "config_digest") != config_identity(config)):
            config = {**config, "target": check_target}
    validate(config)
    if not config["io_scope"]["site_ids"]:
        raise ValueError("static selection found no I/O callsites")
    return config


# --- running one JUnit ---------------------------------------------------------

def run_command(args: list[str], context: dict[str, str], cwd: Path, env: dict[str, str],
                log_dir: Path, timeout: int) -> dict[str, Any]:
    """Run an argv template in its own process group, killed on timeout."""
    log_dir.mkdir(parents=True, exist_ok=True)
    command = [value.format_map(context) for value in args]
    started = time.monotonic()
    with (log_dir / "stdout.log").open("wb") as stdout, \
            (log_dir / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        timed_out = False
        try:
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                code = _kill_group(process)
        except BaseException:
            if process.poll() is None:
                _kill_group(process)
            raise
    return {"command": command, "exit": code, "timed_out": timed_out,
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def _kill_group(process: subprocess.Popen) -> int:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        return process.wait()


def _base_env(config: dict[str, Any], trace_dir: Path) -> dict[str, str]:
    env = {**os.environ, **config.get("env", {}),
           "TMPDIR": config["workspaces"]["temp"],
           "CAUSYNTH_LOCAL_SCRATCH": config["workspaces"]["temp"],
           "CAUSYNTH_TRACE_OUTPUT_DIR": str(trace_dir)}
    if config.get("_static_selection_artifact"):
        env["CRASHFUZZ_STATIC_SELECTION"] = config["_static_selection_artifact"]
    return env


def write_trial(path: Path, sequence: Sequence, target: dict[str, Any]) -> None:
    """The agent's fault plan: each selector with its fault id and phase."""
    trial = {"schemaVersion": 1, "faults": [
        {"faultId": fingerprint(point), **point, "phase": point.get("phase", "before"),
         "value": True} for point in sequence]}
    if target.get("site_id"):
        trial["targetSiteId"] = target["site_id"]
    atomic_json(path, trial)


# --- the healthy seed -----------------------------------------------------------

def ensure_seed(config: dict[str, Any], state: dict[str, Any], case_dir: Path) -> None:
    """Record (or adopt) the healthy run and queue one sequence per I/O point."""
    seed = config["seed"]
    trace = Path(seed["trace"])
    seconds = None
    if not trace.is_file():
        if not seed.get("command"):
            raise FileNotFoundError(f"seed trace missing: {trace}")
        result = run_command(seed["command"],
                             {"case_dir": str(case_dir), "trace_dir": str(trace.parent)},
                             Path(config["cwd"]), _base_env(config, trace.parent),
                             case_dir / "seed-command", config["timeout_seconds"])
        atomic_json(case_dir / "seed-command" / "result.json", result)
        seconds = result["elapsed_seconds"]
        state["active_runtime_seconds"] += seconds
        state["seed_runtime_seconds"] += seconds
        if result["exit"] == 0 and not result["timed_out"]:
            state["seed_timing_recorded"] = True
        atomic_json(case_dir / "state.json", state)
        if result["exit"] != 0 or result["timed_out"]:
            raise RuntimeError("healthy JUnit recording failed")
    if seconds is None:
        seconds = _recorded_seed_seconds(seed, case_dir)
        if not state.get("seed_timing_recorded"):
            state["active_runtime_seconds"] += seconds
            state["seed_runtime_seconds"] += seconds
            state["seed_timing_recorded"] = True
            atomic_json(case_dir / "state.json", state)
    feedback = trace_feedback(trace, config["target"], config.get("io_scope"))
    if (config.get("_static_selection_digest") and
            feedback["static_selection_digests"] != [config["_static_selection_digest"]]):
        raise RuntimeError("healthy JUnit did not apply the selected instrumentation")
    state["seed"] = {"trace": str(trace), "feedback": feedback,
                     "target_reached": feedback["target_reached"],
                     "recorded_at": time.time(), "elapsed_seconds": seconds}
    state["coverage"] = feedback["coverage"]
    state["io_families"] = sorted({fault_family(p) for p in feedback["points"]})
    if not feedback["points"]:
        state["status"] = "no_io_fault_points"
        return
    state["status"] = "fuzzing"
    enqueue_seed(state, feedback, config.get("_static_io_priority", {}),
                 config.get("_static_io_exceptions"))


def _recorded_seed_seconds(seed: dict[str, Any], case_dir: Path) -> float:
    previous = case_dir / "seed-command" / "result.json"
    if previous.is_file():
        return float(json.loads(previous.read_text())["elapsed_seconds"])
    if seed.get("timing_manifest"):
        data = json.loads(Path(seed["timing_manifest"]).read_text())
        return sum(float(data.get(stage, {}).get("seconds", 0))
                   for stage in ("compile", "weave", "runtime"))
    return float(seed["elapsed_seconds"])


# --- one trial -------------------------------------------------------------------

def _run_attempt(config: dict[str, Any], state: dict[str, Any], case_dir: Path,
                 active: dict[str, Any], trial_dir: Path) -> dict[str, Any]:
    trial_dir.mkdir(parents=True, exist_ok=True)
    selector = trial_dir / "fault-trial.json"
    write_trial(selector, active["sequence"], config["target"])
    active["attempt"] = active.get("attempt", 0) + 1
    atomic_json(case_dir / "state.json", state)
    attempt_dir = trial_dir / f"attempt-{active['attempt']:02d}"
    trace_dir = attempt_dir / "trace"
    trace_dir.mkdir(parents=True, exist_ok=True)
    context = {"case_id": config["case_id"], "sequence_id": active["id"],
               "attempt": str(active["attempt"]),
               "trial_name": (f"{config['case_id']}-{active['number']:04d}-"
                              f"{active['id'][:12]}-a{active['attempt']:02d}"),
               "case_dir": str(case_dir), "trial_dir": str(trial_dir),
               "trace_dir": str(trace_dir), "fault_trial": str(selector)}
    env = _base_env(config, trace_dir)
    env["CAUSYNTH_FAULT_TRIAL"] = str(selector)
    env.update({key: value.format_map(context)
                for key, value in config["trial"].get("env", {}).items()})
    env["CAUSYNTH_WORKLOAD_JAVA_OPTS"] = (env.get("CAUSYNTH_WORKLOAD_JAVA_OPTS", "") +
                                          " -Dcausynth.fault.trial=" + str(selector)).strip()
    result = run_command(config["trial"]["command"], context, Path(config["cwd"]), env,
                         attempt_dir, config["timeout_seconds"])
    state["active_runtime_seconds"] += result["elapsed_seconds"]
    state["fault_runtime_seconds"] += result["elapsed_seconds"]
    atomic_json(case_dir / "state.json", state)
    trace = Path(config["trial"].get("trace_path",
                                     "{trace_dir}/runtime_trace.jsonl").format_map(context))
    roots = [case_dir.resolve()] + [Path(value).resolve()
                                    for value in config["workspaces"].values()]
    resolved = trace.resolve()
    if not trace.is_absolute() or not any(resolved == root or root in resolved.parents
                                          for root in roots):
        raise ValueError(f"trial trace must stay in a per-case workspace: {trace}")
    if trace.is_file():
        result.update(trace_feedback(trace, config["target"], config.get("io_scope")))
        result["trace"] = str(trace)
        if (config.get("_static_selection_digest") and
                result["static_selection_digests"] != [config["_static_selection_digest"]]):
            raise RuntimeError("fault trial did not apply the selected instrumentation")
    else:
        result.update({"trace": None, "matched_count": 0, "applied_count": 0,
                       "target_reached": False, "target_reached_after_fault": False,
                       "oracle": False, "coverage": [], "points": []})
    result.update(sequence_id=active["id"], fault_count=len(active["sequence"]),
                  attempt=active["attempt"], completed_at=time.time())
    atomic_json(attempt_dir / "result.json", result)
    return result


def _trial_status(result: dict[str, Any], matched: bool, realized_prefix: Sequence) -> str:
    if realized_prefix and result["oracle"] and result["differential_target_exception"]:
        return "partial_target_exception_candidate"
    if not matched:
        return "unmatched"
    if not result.get("target_reached_after_fault"):
        return "lost_target"
    if result["oracle"] and result["differential_target_exception"]:
        return "target_exception_candidate"
    if result["oracle"]:
        return "baseline_exception_recurrence"
    if result.get("target_after_fault"):
        return "target_exception_unlinked"
    if result["timed_out"]:
        return "timeout"
    return "checked"


def process_trial(config: dict[str, Any], state: dict[str, Any], case_dir: Path,
                  active: dict[str, Any]) -> None:
    """Run (or resume) the active sequence's trial and fold its result in."""
    trial_dir = case_dir / "trials" / f"{active['number']:04d}-{active['id']}"
    result_file = trial_dir / "result.json"
    budget = config["budget"]
    if result_file.is_file():
        result = json.loads(result_file.read_text())
    else:
        while True:
            result = _run_attempt(config, state, case_dir, active, trial_dir)
            # A selector whose I/O was absent this run is executed again,
            # and so is a matched multi-fault plan whose last fault landed
            # after the check (callback order varies between runs).
            if (not strict_injection(result, active["sequence"]) and
                    active.get("attempt", 0) <= budget.get("max_unmatched_retries", 1)):
                atomic_json(case_dir / "state.json", state)
                continue
            if retry_lost_target(result, active["sequence"], active.get("attempt", 0),
                                 budget.get("max_lost_target_retries", 1)):
                atomic_json(case_dir / "state.json", state)
                continue
            break
    matched = strict_injection(result, active["sequence"])
    result["selector_matched"] = matched
    result["strict_injection"] = matched
    realized_prefix = [] if matched else strict_applied_prefix(result, active["sequence"])
    result["strict_applied_prefix"] = bool(realized_prefix)
    result["realized_fault_count"] = len(active["sequence"]) if matched else len(realized_prefix)
    seed = state["seed"]["feedback"]
    baseline_fatal = seed.get("target_fatal_exception_count", 0)
    result["baseline_target_fatal_exception_count"] = baseline_fatal
    result["differential_target_exception"] = bool(
        result.get("target_fatal_exception_count", 0) > baseline_fatal)
    result["target_outcome_changed"] = bool(
        set(result.get("target_outcomes_after_fault", [])) -
        set(seed.get("target_outcomes", [])))
    status = _trial_status(result, matched, realized_prefix)
    old_coverage = set(state["coverage"])
    observed_coverage = set(result.get("coverage", [])) - old_coverage
    old_io = set(state.get("io_families", []))
    observed_io = {fault_family(point) for point in result.get("points", [])} - old_io
    admitted = status in ADMITTED
    new_coverage = observed_coverage if admitted else set()
    new_io = observed_io if admitted else set()
    result.update(observed_new_coverage_count=len(observed_coverage),
                  new_coverage_count=len(new_coverage),
                  observed_new_io_count=len(observed_io), new_io_count=len(new_io),
                  new_io_families=sorted(new_io), status=status)
    if config.get("archive_completed_trials") and status not in CANDIDATES:
        result["archived_artifacts"] = sorted(set(result.get("archived_artifacts", []) +
                                                  archive_trial_attempts(trial_dir, result)))
    atomic_json(result_file, result)
    if admitted:
        state["coverage"] = sorted(old_coverage | set(result.get("coverage", [])))
        state["io_families"] = sorted(old_io | {fault_family(point)
                                                for point in result.get("points", [])})
    state["completed"].append({"id": active["id"], "number": active["number"],
                               "status": status, "result": str(result_file),
                               "elapsed_seconds": result["elapsed_seconds"],
                               "sequence": active["sequence"]})
    enqueue_extensions(state, realized_prefix or active["sequence"], result,
                       budget["max_faults"], config.get("_static_io_priority"),
                       config.get("_static_io_exceptions"))
    state["active"] = None


ARCHIVED_FILES = ("runtime_trace.jsonl", "junit.log", "jacoco.exec")


def archive_trial_attempts(trial_dir: Path, final_result: dict[str, Any]) -> list[str]:
    """Gzip every attempt's trace and logs (verified), repointing the records."""
    archived = []
    for attempt_dir in sorted(trial_dir.glob("attempt-*")):
        attempt_result_path = attempt_dir / "result.json"
        if not attempt_result_path.is_file():
            continue
        attempt_result = json.loads(attempt_result_path.read_text())
        manifest_path = attempt_dir / "trace" / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else None
        changed = manifest_changed = False
        attempt_archived = []
        for name in ARCHIVED_FILES:
            path = attempt_dir / "trace" / name
            target = path.with_name(path.name + ".gz")
            if path.is_file():
                _gzip_verified(path, target)
            elif not target.is_file():
                continue
            archived.append(str(target))
            attempt_archived.append(str(target))
            for record in (attempt_result, final_result):
                for key in ("trace", "junit_log", "jacoco_exec"):
                    if record.get(key) == str(path):
                        record[key] = str(target)
                        changed = True
            if manifest is not None:
                for key in ("trace", "junit_log", "jacoco_exec"):
                    if manifest.get(key) == str(path):
                        manifest[key] = str(target)
                        manifest_changed = True
            if str(target) not in attempt_result.get("archived_artifacts", []):
                changed = True
        if changed:
            attempt_result["archived_artifacts"] = sorted(set(
                attempt_result.get("archived_artifacts", []) + attempt_archived))
            atomic_json(attempt_result_path, attempt_result)
        if manifest_changed:
            atomic_json(manifest_path, manifest)
    return archived


def _gzip_verified(path: Path, target: Path) -> None:
    temporary = target.with_name(target.name + f".tmp.{os.getpid()}")
    try:
        source_digest = hashlib.sha256()
        with path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=3) as sink:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                source_digest.update(chunk)
                sink.write(chunk)
        restored_digest = hashlib.sha256()
        with gzip.open(temporary, "rb") as restored:
            for chunk in iter(lambda: restored.read(1024 * 1024), b""):
                restored_digest.update(chunk)
        if restored_digest.digest() != source_digest.digest():
            raise IOError(f"compressed artifact differs from source: {path}")
        os.replace(temporary, target)
        path.unlink()
    finally:
        temporary.unlink(missing_ok=True)


# --- the case record --------------------------------------------------------------

def write_case_result(case_dir: Path, state: dict[str, Any]) -> None:
    """Summarize the campaign into ``<case>/result.json``."""
    completed = state["completed"]
    sequences = completed_sequences(state)
    results = [json.loads(Path(item["result"]).read_text()) for item in completed]
    candidates = [item for item, result in zip(completed, results)
                  if result.get("status") in CANDIDATES]
    status = state.get("status", "recorded_seed")
    if candidates and status not in TERMINAL:
        status = "candidate_review"
    elif completed and not state.get("finished"):
        status = "fuzzing"
    seed = state.get("seed") or {}
    seed_feedback = seed.get("feedback", {})
    coverage_delta = set(state.get("coverage", [])) - set(seed_feedback.get("coverage", []))
    seconds = {name: float(state.get(key, 0)) for name, key in
               (("setup", "setup_seconds"), ("build", "build_seconds"),
                ("seed", "seed_runtime_seconds"), ("fault", "fault_runtime_seconds"))}
    total = round(sum(seconds.values()), 3)
    target = {key: state.get(key) for key in
              ("target_method", "target_throw_method", "target_throw_site_id",
               "target_source_file", "target_source_line", "target_code")}
    record = {
        "schema_version": SCHEMA, "case_id": state["case_id"], "system": state["system"],
        "cluster_test": state["test_class"] + "#" + state["test_method"], **target,
        "coverage_exclude_sites": state.get("coverage_exclude_sites", []),
        "status": status,
        "target_reached": seed.get("target_reached"),
        "fault_trials": len(completed),
        "single_fault_trials": sum(len(sequence) == 1 for sequence in sequences),
        "multi_fault_trials": sum(len(sequence) > 1 for sequence in sequences),
        "first_fault_families_tested": len({fault_family(s[0]) for s in sequences}),
        "last_fault_families_tested": len({fault_family(s[-1]) for s in sequences}),
        "strict_injections": sum(bool(r.get("strict_injection")) for r in results),
        "strict_applied_prefixes": sum(bool(r.get("strict_applied_prefix")) for r in results),
        "post_fault_target_reach_trials": sum(
            bool(r.get("strict_injection") and r.get("target_reached_after_fault"))
            for r in results),
        "lost_target_trials": sum(r.get("status") == "lost_target" for r in results),
        "target_after_fault": sum(bool(r.get("target_after_fault")) for r in results),
        "target_exception_after_fault_trials": sum(
            bool(r.get("strict_injection") and r.get("oracle")) for r in results),
        "target_outcome_changed_trials": sum(bool(r.get("target_outcome_changed"))
                                             for r in results),
        "oracle_candidates": len(candidates),
        "partial_target_exception_candidates": sum(
            r.get("status") == "partial_target_exception_candidate" for r in results),
        "coverage_gain": len(coverage_delta),
        "coverage_gain_by_kind": {
            "methods": sum(item.startswith("METHOD:") for item in coverage_delta),
            "branch_outcomes": sum(item.startswith("BRANCH:") for item in coverage_delta),
            "call_site_events": sum(item.startswith("CALL_SITE:") for item in coverage_delta)},
        "coverage_include_prefixes": state.get("coverage_include_prefixes", []),
        "static_selection_digest": state.get("static_selection_digest"),
        "static_selection_artifact": state.get("static_selection_artifact"),
        "io_family_gain": max(0, len(state.get("io_families", [])) - len(
            {fault_family(point) for point in seed_feedback.get("points", [])})),
        **{f"{name}_seconds": round(value, 3) for name, value in seconds.items()},
        "total_elapsed_seconds": total, "elapsed_seconds": total,
        "bug_mark": "candidate" if candidates else "none",
        "evidence": (candidates[0]["result"] if candidates else
                     completed[-1]["result"] if completed else None),
        "started_at": state.get("started"), "updated_at": time.time(),
    }
    atomic_json(case_dir / "result.json", record)


# --- ownership ---------------------------------------------------------------------

class CaseLease:
    """One owner per case directory: a local flock plus a heartbeated claim dir.

    ``mkdir`` of the claim directory is the cross-host claim on a shared
    mount; an expired claim (no heartbeat within the TTL) can be taken over.
    """

    def __init__(self, case_dir: Path, ttl: int = 120, interval: int = 15):
        self.case_dir = case_dir
        self.ttl = ttl
        self.interval = interval
        self.owner = str(uuid.uuid4())
        self.directory = case_dir / "claim.d"
        self.path = self.directory / "lease.json"
        self.lock = None
        self.stop = threading.Event()
        self.thread = None
        self.started = time.time()

    def _record(self) -> dict[str, Any]:
        return {"owner": self.owner, "host": socket.gethostname(), "pid": os.getpid(),
                "started_at": self.started, "heartbeat": time.time(),
                "ttl_seconds": self.ttl}

    def _heartbeat(self) -> None:
        while not self.stop.wait(self.interval):
            atomic_json(self.path, self._record())

    def __enter__(self) -> "CaseLease":
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.lock = (self.case_dir / ".lock").open("w")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise RuntimeError(f"case already claimed: {self.case_dir}") from exc
        try:
            if self.directory.exists():
                old = json.loads(self.path.read_text()) if self.path.exists() else {}
                if time.time() - old.get("heartbeat", 0) <= self.ttl:
                    raise RuntimeError(f"case lease still live: {self.case_dir}")
                os.rename(self.directory,
                          self.case_dir / f"claim.stale.{int(time.time())}.{self.owner}.d")
            self.directory.mkdir()
            atomic_json(self.path, self._record())
        except BaseException:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            raise
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=self.interval + 1)
        if self.path.exists():
            lease = json.loads(self.path.read_text())
            if lease.get("owner") == self.owner:
                self.path.unlink()
                self.directory.rmdir()
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()


# --- the campaign --------------------------------------------------------------------

def new_state(config: dict[str, Any], digest: str) -> dict[str, Any]:
    target = config["target"]
    return {"schemaVersion": SCHEMA, "case_id": config["case_id"],
            "system": config["system"], "test_class": config["test_class"],
            "test_method": config["test_method"],
            "target_method": target["method"],
            "target_throw_method": target.get("throw_method", target["method"]),
            "target_throw_site_id": target.get("throw_site_id"),
            "target_source_file": target.get("source_file"),
            "target_source_line": target.get("source_line"),
            "target_code": target.get("code"),
            "coverage_exclude_sites": target.get("coverage_exclude_sites", []),
            "coverage_include_prefixes": target.get("coverage_include_prefixes", []),
            "static_selection_digest": config.get("_static_selection_digest"),
            "static_selection_artifact": config.get("_static_selection_artifact"),
            "config_digest": digest, "seed": None, "coverage": [], "queue": [],
            "seen_sequences": {}, "io_families": [], "active_runtime_seconds": 0.0,
            "seed_runtime_seconds": 0.0, "fault_runtime_seconds": 0.0,
            "setup_seconds": float(config.get("setup_seconds", 0)),
            "build_seconds": float(config.get("build_seconds", 0)),
            "active": None, "completed": [], "started": time.time()}


def _open_state(config: dict[str, Any], path: Path) -> dict[str, Any]:
    digest = config_identity(config)
    if path.exists():
        state = json.loads(path.read_text())
        # Budgets may grow; a changed workload or selector contract may not.
        if state["config_digest"] != digest:
            raise ValueError("case config changed; use a new case directory")
        return state
    state = new_state(config, digest)
    if config.get("status") in TERMINAL:
        state["status"] = config["status"]
    atomic_json(path, state)
    return state


def campaign(config: dict[str, Any], root: Path) -> dict[str, Any]:
    """Run (or resume) the campaign of ``config`` under ``root/<case>``."""
    validate(config)
    case_dir = root / config["case_id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    Path(config["workspaces"]["temp"]).mkdir(parents=True, exist_ok=True)
    with CaseLease(case_dir):
        config = with_selection(config, case_dir)
        path = case_dir / "state.json"
        resumed = path.exists()
        state = _open_state(config, path)
        if state.get("status") in TERMINAL:
            if not resumed:
                write_case_result(case_dir, state)
            return state
        external = case_dir / "result.json"
        if external.is_file():
            review = json.loads(external.read_text())
            if review.get("status") in TERMINAL:
                state["status"] = review["status"]
                atomic_json(path, state)
                return state
        if state["seed"] is None:
            ensure_seed(config, state, case_dir)
            atomic_json(path, state)
            write_case_result(case_dir, state)
        if state.get("status") == "no_io_fault_points":
            state["finished"] = False
            atomic_json(path, state)
            write_case_result(case_dir, state)
            return state
        budget = config["budget"]
        # A larger max_faults can extend sequences that ended at the old depth.
        for completed in state["completed"]:
            if completed.get("sequence"):
                enqueue_extensions(state, completed["sequence"],
                                   json.loads(Path(completed["result"]).read_text()),
                                   budget["max_faults"], config.get("_static_io_priority"),
                                   config.get("_static_io_exceptions"))
        max_runtime = budget.get("max_seconds", 1e18)

        def can_run() -> bool:
            # stop_at_candidate: a measurement of the time to the first candidate
            found = (budget.get("stop_at_candidate") and
                     any(item["status"] in CANDIDATES for item in state["completed"]))
            return (not found and budget_has_room(state, budget) and
                    (state["active"] or state["active_runtime_seconds"] < max_runtime) and
                    bool(state["queue"] or state["active"]))

        if can_run() and state.get("finished"):
            # A larger budget reopened an exhausted checkpoint.
            state["finished"] = False
            if state.get("status") in {"budget_or_queue_complete", "no_valid_target_trial"}:
                state["status"] = "fuzzing"
            atomic_json(path, state)
            write_case_result(case_dir, state)
        while can_run():
            if state["active"] is None:
                item = state["queue"].pop(choose_next_sequence(
                    state, config.get("_static_io_priority")))
                state["active"] = {**item, "number": len(state["completed"]) + 1}
                atomic_json(path, state)
            process_trial(config, state, case_dir, state["active"])
            atomic_json(path, state)
            write_case_result(case_dir, state)
        state["last_updated"] = time.time()
        state["finished"] = bool(not state["active"] and
                                 (not state["queue"] or not budget_has_room(state, budget) or
                                  state["active_runtime_seconds"] >= max_runtime or
                                  not can_run()))
        if state["finished"] and state.get("status") not in TERMINAL:
            valid = {"checked", "target_exception_candidate",
                     "partial_target_exception_candidate", "baseline_exception_recurrence"}
            state["status"] = ("budget_or_queue_complete"
                               if any(item["status"] in valid for item in state["completed"])
                               else "no_valid_target_trial")
        atomic_json(path, state)
        write_case_result(case_dir, state)
        return state


def replay(config: dict[str, Any], root: Path, sequence: Sequence,
           repeats: int = 1) -> dict[str, Any]:
    """Run one given fault sequence ``repeats`` times as ordinary trials.

    The trials go through the same matching, retries and oracle as a
    campaign's; nothing else is scheduled. Use a root of its own.
    """
    validate(config)
    case_dir = root / config["case_id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    Path(config["workspaces"]["temp"]).mkdir(parents=True, exist_ok=True)
    with CaseLease(case_dir):
        config = with_selection(config, case_dir)
        path = case_dir / "state.json"
        state = _open_state(config, path)
        if state["seed"] is None:
            ensure_seed(config, state, case_dir)
            atomic_json(path, state)
        name = sequence_id(sequence)
        while len(state["completed"]) < repeats:
            if state["active"] is None:
                state["active"] = {"id": name, "sequence": sequence, "priority": 0,
                                   "created": time.time(), "target_proximity": 0,
                                   "number": len(state["completed"]) + 1}
                atomic_json(path, state)
            process_trial(config, state, case_dir, state["active"])
            atomic_json(path, state)
        state["finished"] = True
        atomic_json(path, state)
        write_case_result(case_dir, state)
        return state
