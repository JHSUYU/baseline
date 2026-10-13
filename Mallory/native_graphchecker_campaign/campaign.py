"""One-weave, fresh-JUnit native GraphChecker fault campaign.

This driver consumes the original GraphChecker concolic weave and native
SessionReader feedback. An adapter must emit typed FAULT_DOOR, FAULT_APPLIED,
and TARGET_THROW receipts at the event; the campaign never infers an applied
fault from a failed JUnit or a static candidate site.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from Mallory.instrumentation.graphchecker_port.native_original_weave import (
    ENGINE, JAR, DEPENDENCIES, dependency_digests, verify_existing,
)
from Mallory.native_graphchecker_feedback import delta, summarize_target_set
from Mallory.native_graphchecker_feedback.feedback import NoNativeTargetError

SCHEMA = 1
FAULT_FIELDS = ("siteId", "node", "actorEpochOrdinal", "occurrenceId",
                "ordinal", "exceptionClass")
SELECTOR_FIELDS = ("siteId", "node", "actorEpochOrdinal", "ordinal",
                   "exceptionClass")
MAX_FAULTS = 10


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha(root: Path) -> str:
    """Hash the closed recording, including file names and all row bytes."""
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError("closed original recording is empty")
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha(path)))
    return digest.hexdigest()


def _start_ticks(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (OSError, IndexError):
        return None


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".native-campaign-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_config(config: dict[str, Any]) -> None:
    for field in ("case_id", "target_site", "native_weave_config"):
        if not isinstance(config.get(field), str) or not config[field]:
            raise ValueError(f"native campaign requires {field}")
    target_throw = config.get("target_throw")
    if (not isinstance(target_throw, dict) or
            not all(isinstance(target_throw.get(key), str) and target_throw[key]
                    for key in ("siteId", "exceptionClass"))):
        raise ValueError("native campaign requires exact target_throw")
    actors = config.get("target_actor_names", [])
    if (not isinstance(actors, list) or
            not all(isinstance(actor, str) and actor for actor in actors)):
        raise ValueError("target_actor_names must be a list of physical actor names")
    recording = config.get("recording")
    if (not isinstance(recording, dict) or not all(
            isinstance(recording.get(key), str) and recording[key]
            for key in ("trace_dir", "test_id", "target_name",
                        "candidate_graph", "static_scope_map", "region_skeletons"))):
        raise ValueError("native campaign requires original recording provenance")
    if (not isinstance(recording.get("max_jobs"), int) or
            isinstance(recording["max_jobs"], bool) or
            recording["max_jobs"] <= 0):
        raise ValueError("native campaign requires positive original schedule max_jobs")
    if (recording.get("target_occurrence") is not None and
            (not isinstance(recording["target_occurrence"], str) or
             not recording["target_occurrence"])):
        raise ValueError("recording target_occurrence must be an exact ID")
    junit = config.get("junit")
    if not isinstance(junit, dict) or not all(
            isinstance(junit.get(key), str) and junit[key]
            for key in ("class", "method")):
        raise ValueError("native campaign requires original JUnit class/method")
    runner = config.get("runner")
    if (not isinstance(runner, dict) or not all(
            isinstance(runner.get(key), str) and runner[key]
            for key in ("zero_vm_java", "main_class")) or
            not isinstance(runner.get("classpath"), list) or
            not all(isinstance(item, str) and item for item in runner["classpath"]) or
            not isinstance(runner.get("jvm_args", []), list) or
            not all(isinstance(item, str) for item in runner.get("jvm_args", []))):
        raise ValueError("native campaign requires bounded Zero VM JUnit runner")
    budget = config.get("budget")
    if (not isinstance(budget, dict) or any(
            not isinstance(budget.get(key), int) or isinstance(budget[key], bool)
            or budget[key] <= 0 for key in
            ("fault_trials", "seconds", "max_faults_per_trial")) or
            budget["max_faults_per_trial"] > MAX_FAULTS):
        raise ValueError("invalid native campaign budget")
    if (not isinstance(config.get("timeout_seconds"), int) or
            config["timeout_seconds"] <= 0):
        raise ValueError("native campaign needs positive per-trial timeout_seconds")


def _scheduler_source() -> Path:
    """Require original PLAN stage in the same pinned source-built engine."""
    source = (ENGINE / "vendor/src/main/java/edu/uva/liftlab/graphchecker/plan/"
              "ConcolicScheduler.java")
    class_name = "edu/uva/liftlab/graphchecker/plan/ConcolicScheduler.class"
    if not source.is_file() or not JAR.is_file():
        raise ValueError("pinned original GraphChecker scheduler is unavailable")
    with zipfile.ZipFile(JAR) as archive:
        if class_name not in archive.namelist():
            raise ValueError("source-built original engine omits ConcolicScheduler")
    return source


def _verify_recording_plan(config: dict[str, Any], weave: dict[str, Any]) -> dict[str, str]:
    """Re-run the original recorder and scheduler; reject a hand-authored task.

    The source-built recorder validates the closed region-state recording's
    TracedRows digest against the same static artifacts before planning.
    Re-aggregation and scheduling occur once at campaign admission, never
    per fuzz trial. The task plan must be byte-identical to the pinned weave.
    """
    rec = config["recording"]
    planned = Path(weave["task_plan"]).resolve(strict=True)
    scope = Path(rec["static_scope_map"]).resolve(strict=True)
    skeletons = Path(rec["region_skeletons"]).resolve(strict=True)
    woven_skeletons = Path(weave["region_skeletons"]).resolve(strict=True)
    graph = Path(rec["candidate_graph"]).resolve(strict=True)
    trace = Path(rec["trace_dir"]).resolve(strict=True)
    if not (trace / "streaming_trace_manifest.json").is_file():
        raise ValueError("closed original region-state recording is missing")
    with tempfile.TemporaryDirectory(prefix="mallory-native-recording-") as scratch:
        output = Path(scratch) / "recorded"
        scheduled = Path(scratch) / "scheduled"
        _scheduler_source()
        classpath = f"{JAR}:{DEPENDENCIES.read_text(encoding='utf-8').strip()}"
        target = ",".join((str(graph), str(scope), str(skeletons), str(output)))
        command = [str(Path(weave["java"]).resolve(strict=True)), "-cp",
                   classpath,
                   "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
                   "--trace-dir", str(trace), "--test", rec["test_id"],
                   "--target", f"{rec['target_name']}={target}"]
        if rec.get("target_occurrence"):
            command.extend(("--target-occurrence", rec["target_occurrence"]))
        subprocess.run(command, check=True, timeout=300,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        region_plan = output / "concolic_region_plan.jsonl"
        if not region_plan.is_file():
            raise ValueError("original recorder produced no region plan")
        scheduler = [str(Path(weave["java"]).resolve(strict=True)), "-cp",
                     classpath,
                     "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler",
                     "--region-plan", str(region_plan),
                     "--candidate-graph", str(graph),
                     "--static-scope-map", str(scope),
                     "--output-dir", str(scheduled),
                     "--max-jobs", str(rec["max_jobs"])]
        if rec.get("target_occurrence"):
            scheduler.extend(("--target-occurrence", rec["target_occurrence"]))
        subprocess.run(scheduler, check=True, timeout=300,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        generated = scheduled / "execution_task_plan.jsonl"
        index = scheduled / "runtime_workflow_schedule_index.json"
        if not generated.is_file() or not index.is_file() or _sha(generated) != _sha(planned):
            raise ValueError("pinned GraphChecker task differs from recording-derived schedule")
        selected_skeletons = output / "region_skeletons.jsonl"
        if not selected_skeletons.is_file() or _sha(selected_skeletons) != (
                _sha(woven_skeletons)):
            raise ValueError("woven regions differ from healthy recording")
    task_id = weave["task_id"]
    if not any(json.loads(line).get("taskId") == task_id
               for line in planned.read_text(encoding="utf-8").splitlines()
               if line.strip()):
        raise ValueError("weave task ID is absent from recording-derived plan")
    return {"recording_manifest_sha256": _sha(trace / "streaming_trace_manifest.json"),
            "recording_plan_sha256": _sha(planned),
            "scheduler_source_sha256": _sha(_scheduler_source()),
            "static_scope_map_sha256": _sha(scope)}


def _admit(config: dict[str, Any], root: Path) -> dict[str, Any]:
    weave_file = Path(config["native_weave_config"]).resolve(strict=True)
    weave_receipt = verify_existing(weave_file)
    weave = _load(weave_file)
    rec = config["recording"]
    recording_fingerprint = {
        "trace_tree_sha256": _tree_sha(Path(rec["trace_dir"]).resolve(strict=True)),
        "candidate_graph_sha256": _sha(Path(rec["candidate_graph"]).resolve(strict=True)),
        "static_scope_map_sha256": _sha(Path(rec["static_scope_map"]).resolve(strict=True)),
        "region_skeletons_sha256": _sha(Path(rec["region_skeletons"]).resolve(strict=True)),
        "weave_config_sha256": _sha(weave_file),
        "weave_receipt_sha256": _sha(Path(weave["output_classes"]).resolve(strict=True)
                                     / "native-original-weave-receipt.json"),
        "scheduler_source_sha256": _sha(_scheduler_source()),
        "engine_jar_sha256": _sha(JAR),
    }
    admission = root / "recording-admission.json"
    if admission.is_file():
        cached = _load(admission)
        if (cached.get("schema_version") != SCHEMA or
                cached.get("recording_fingerprint") != recording_fingerprint or
                not isinstance(cached.get("origin"), dict)):
            raise ValueError("cached native recording admission inputs changed")
        origin = cached["origin"]
    else:
        origin = _verify_recording_plan(config, weave)
        _atomic(admission, {"schema_version": SCHEMA,
                            "recording_fingerprint": recording_fingerprint,
                            "origin": origin})
    return {"weave_config": weave, "weave_receipt": weave_receipt,
            "origin": origin, "weave_config_sha256": _sha(weave_file),
            "zero_vm_sha256": _sha(Path(config["runner"]["zero_vm_java"])
                                   .resolve(strict=True)),
            "runner_classpath_artifacts": dependency_digests(os.pathsep.join(
                config["runner"]["classpath"]))}


def _verify_pins(config: dict[str, Any], admitted: dict[str, Any]) -> None:
    weave_file = Path(config["native_weave_config"]).resolve(strict=True)
    if _sha(weave_file) != admitted["weave_config_sha256"]:
        raise ValueError("native weave config changed during campaign")
    receipt = verify_existing(weave_file)
    if receipt != admitted["weave_receipt"]:
        raise ValueError("native weave receipt changed during campaign")
    if _sha(Path(config["runner"]["zero_vm_java"]).resolve(strict=True)) != (
            admitted["zero_vm_sha256"]):
        raise ValueError("Zero VM executable changed during campaign")
    scope = Path(config["recording"]["static_scope_map"]).resolve(strict=True)
    if _sha(scope) != admitted["origin"]["static_scope_map_sha256"]:
        raise ValueError("native static scope map changed during campaign")
    if dependency_digests(os.pathsep.join(config["runner"]["classpath"])) != (
            admitted["runner_classpath_artifacts"]):
        raise ValueError("JUnit runner classpath changed during campaign")


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    previous = -1
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("kind") not in (
                "FAULT_DOOR", "FAULT_APPLIED", "TARGET_THROW"):
            raise ValueError(f"invalid native fault receipt row {number}")
        seq = row.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= previous:
            raise ValueError(f"nonmonotone native fault receipt seq {number}")
        previous = seq
        rows.append(row)
    return rows


def _fault_identity(row: dict[str, Any], *, applied: bool) -> tuple[Any, ...]:
    values = tuple(row.get(field) for field in FAULT_FIELDS)
    if (not all(isinstance(value, str) and value for value in values[:2]) or
            not isinstance(values[2], int) or isinstance(values[2], bool) or
            values[2] < 0 or not isinstance(values[3], str) or not values[3] or
            not isinstance(values[4], int) or isinstance(values[4], bool) or
            values[4] <= 0 or (applied and
            (not isinstance(values[5], str) or not values[5]))):
        raise ValueError("native fault receipt lacks exact I/O identity")
    return values


def _strict_faults(faults: list[dict[str, Any]], rows: list[dict[str, Any]]
                   ) -> tuple[bool, int | None]:
    applied = [row for row in rows if row["kind"] == "FAULT_APPLIED"]
    if len(applied) != len(faults):
        return False, None
    doors = [row for row in rows if row["kind"] == "FAULT_DOOR"]
    for planned, actual in zip(faults, applied):
        identity = _fault_identity(actual, applied=True)
        # The source occurrence is an audit address from a prior JVM. A new
        # JVM binds the selector to a fresh exact occurrence at its door.
        if tuple(actual.get(field) for field in SELECTOR_FIELDS) != tuple(
                planned.get(field) for field in SELECTOR_FIELDS):
            return False, None
        if not any(door["seq"] < actual["seq"] and
                   _fault_identity(door, applied=False) == identity
                   for door in doors):
            return False, None
    return True, applied[-1]["seq"] if applied else None


def _exact_throws(rows: list[dict[str, Any]], summary: dict[str, Any],
                  target: dict[str, str], last_fault_seq: int | None
                  ) -> list[dict[str, Any]]:
    if last_fault_seq is None:
        return []
    targets = set(summary["targetOccurrenceIds"])
    return [row for row in rows if row["kind"] == "TARGET_THROW" and
            row.get("siteId") == target["siteId"] and
            row.get("exceptionClass") == target["exceptionClass"] and
            row.get("occurrenceId") in targets and row["seq"] > last_fault_seq]


def _doors(rows: list[dict[str, Any]], summary: dict[str, Any],
           after_seq: int | None = None) -> list[dict[str, Any]]:
    closure = {item["occurrenceId"] for item in summary["closureMembers"]}
    found = []
    for row in rows:
        if row["kind"] != "FAULT_DOOR" or (after_seq is not None and
                                             row["seq"] <= after_seq):
            continue
        try:
            identity = _fault_identity(row, applied=True)
        except ValueError:
            continue
        fault = {field: row[field] for field in SELECTOR_FIELDS}
        fault["sourceOccurrenceId"] = row["occurrenceId"]
        found.append({"fault": fault, "seq": row["seq"],
                      "tier": "observed_closure" if row["occurrenceId"] in closure
                      else "outside_closure"})
    return found


def _plan_key(faults: list[dict[str, Any]]) -> str:
    stable = [{field: fault[field] for field in SELECTOR_FIELDS}
              for fault in faults]
    return hashlib.sha256(json.dumps(stable, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _enqueue(state: dict[str, Any], doors: list[dict[str, Any]],
             prefix: list[dict[str, Any]], novelty: int) -> None:
    if len(prefix) >= state["budget"]["max_faults_per_trial"]:
        return
    seen = set(state["seen_plan_keys"])
    # One plan per exact observed I/O identity; an occurrence is never
    # fabricated from a static relation or a different trial's task address.
    for door in doors:
        faults = [*prefix, door["fault"]]
        key = _plan_key(faults)
        if key in seen:
            continue
        seen.add(key)
        state["queue"].append({"faults": faults, "key": key,
                               "tier": door["tier"], "novelty": novelty,
                               "enqueued_at": state["completed_fault_trials"]})
    state["seen_plan_keys"] = sorted(seen)


def _pick(state: dict[str, Any]) -> dict[str, Any]:
    queue = state["queue"]
    if not queue:
        raise ValueError("empty native fault queue")
    completed = state["completed_fault_trials"]
    # A sparse slot preserves exploration outside the observed target closure.
    outside = [item for item in queue if item["tier"] == "outside_closure"]
    candidates = outside if outside and completed % 8 == 7 else queue
    selected = max(candidates, key=lambda item: (
        (100 if item["tier"] == "observed_closure" else 15) +
        item["novelty"] + 3 * len(item["faults"]) +
        min(20, completed - item["enqueued_at"]), item["key"]))
    queue.remove(selected)
    return selected


def _novelty(state: dict[str, Any], feedback: dict[str, Any]) -> int:
    score = 0
    for field, seen_field, weight in (
            ("newClosureNodeFamilies", "seen_node_families", 2),
            ("newObservedClosureEdgeFamilies", "seen_edge_families", 4),
            ("newClosureBranchOutcomeIds", "seen_branch_outcomes", 1)):
        values = feedback.get(field)
        if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values):
            raise ValueError(f"native delta lacks exact {field}")
        seen = set(state[seen_field])
        new = set(values) - seen
        state[seen_field] = sorted(seen | set(values))
        score += weight * len(new)
    return min(60, score)


def _execute_junit(config: dict[str, Any], admitted: dict[str, Any],
                   trial: Path, faults: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the same unchanged JUnit method in a fresh Zero VM."""
    iteration = trial / "iteration-native"
    workdir = iteration / "workdir"
    workdir.mkdir(parents=True)
    _atomic(iteration / "fault-plan.json", {"faults": faults})
    weave = admitted["weave_config"]
    runner = config["runner"]
    cp = os.pathsep.join((
        str(Path(weave["output_classes"]).resolve(strict=True)),
        *(str(Path(item).resolve(strict=True)) for item in runner["classpath"]),
        str(JAR.resolve(strict=True)),
        DEPENDENCIES.read_text(encoding="utf-8").strip()))
    argv = [str(Path(runner["zero_vm_java"]).resolve(strict=True)),
            f"-Dcausynth.concolic.task.plan={Path(weave['task_plan']).resolve(strict=True)}",
            f"-Dcausynth.concolic.task.id={weave['task_id']}",
            f"-Dcausynth.concolic.results={iteration / 'vm-result.json'}",
            *runner.get("jvm_args", []), "-cp", cp, runner["main_class"],
            config["junit"]["class"], config["junit"]["method"]]
    env = os.environ.copy()
    env.update({"CAUSYNTH_STATIC_SCOPE_MAP": str(Path(config["recording"][
        "static_scope_map"]).resolve(strict=True)),
                "CAUSYNTH_CONCOLIC_SESSIONS": str(iteration / "sessions"),
                "MALLORY_NATIVE_FAULT_PLAN": str(iteration / "fault-plan.json"),
                "MALLORY_NATIVE_FAULT_EVENTS": str(iteration / "fault-events.jsonl")})
    started = time.monotonic()
    with (trial / "stdout.log").open("wb") as stdout, (
            trial / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=workdir, env=env, stdout=stdout,
                                   stderr=stderr, start_new_session=True)
        _atomic(trial / "process.json", {"pid": process.pid,
                                        "start_ticks": _start_ticks(process.pid),
                                        "argv": argv, "started_at": time.time()})
        try:
            code = process.wait(timeout=config["timeout_seconds"])
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            code, timed_out = process.returncode, True
    return {"return_code": code, "timed_out": timed_out,
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def _run_trial(config: dict[str, Any], admitted: dict[str, Any],
               trial: Path, faults: list[dict[str, Any]],
               healthy: dict[str, Any] | None) -> dict[str, Any]:
    _verify_pins(config, admitted)
    trial.mkdir(parents=True, exist_ok=False)
    execution = _execute_junit(config, admitted, trial, faults)
    iteration = trial / "iteration-native"
    result: dict[str, Any] = {"schema_version": SCHEMA, "case_id": config["case_id"],
                              "faults": faults, **execution}
    result["fault_events_sha256"] = (_sha(iteration / "fault-events.jsonl")
                                      if (iteration / "fault-events.jsonl").is_file()
                                      else None)
    result["strict_injection"] = False
    result["junit_passed"] = execution["return_code"] == 0 and not execution["timed_out"]
    result["target_exception_triggered"] = False
    result["native_target_retained"] = False
    result["eligible_doors"] = []
    try:
        events = _rows(iteration / "fault-events.jsonl")
        strict, last_fault = _strict_faults(faults, events)
    except ValueError as failure:
        result["status"] = "invalid_fault_receipt"
        result["analysis_error"] = str(failure)
        _atomic(trial / "result.json", result)
        return result
    result["strict_injection"] = bool(faults and strict)
    if not result["junit_passed"] and not faults:
        result["status"] = "blocked_healthy_junit"
    else:
        try:
            selected_actors = set(config.get("target_actor_names", [])) or None
            try:
                summary = summarize_target_set(
                    iteration, config["target_site"], trial / "native-summary.json",
                    static_scope_map=Path(config["recording"]["static_scope_map"]),
                    actor_names=selected_actors, engine_jar=JAR)
            except NoNativeTargetError as missing:
                result["status"] = (("blocked_healthy_target_attribution"
                                     if missing.site_target_rows_seen
                                     else "blocked_healthy_target")
                                    if not faults else "target_lost")
            else:
                result["native_session_sha256"] = summary["nativeSessionSha256"]
                result["native_target_occurrence_ids"] = summary[
                    "targetOccurrenceIds"]
                reached = bool(summary["perTargetOccurrences"]) and all(
                    any(row.get("reachedAnchor") is True for row in one["targetRows"])
                    for one in summary["perTargetOccurrences"])
                if not reached:
                    result["status"] = ("blocked_healthy_target_attribution"
                                        if not faults else "target_lost")
                elif faults and not strict:
                    result["status"] = "unmatched"
                else:
                    result["native_target_retained"] = True
                    if healthy is not None:
                        try:
                            feedback = delta(healthy, summary)
                        except ValueError as failure:
                            if "lost every healthy target region" not in str(failure):
                                raise
                            result["status"] = "target_lost"
                            result["native_target_retained"] = False
                            result["analysis_error"] = str(failure)
                        else:
                            result["native_delta"] = feedback
                    if result.get("status") != "target_lost":
                        result["eligible_doors"] = _doors(events, summary, last_fault)
                        thrown = _exact_throws(events, summary,
                                               config["target_throw"], last_fault)
                        result["target_exception_triggered"] = bool(thrown)
                        result["target_throw_rows"] = thrown
                        if faults:
                            applied = [row for row in events if row["kind"] ==
                                       "FAULT_APPLIED"]
                            closure = {row["occurrenceId"] for row in summary[
                                "closureMembers"]}
                            result["fault_in_target_closure"] = bool(
                                applied and applied[-1]["occurrenceId"] in closure)
                        if faults and not result["fault_in_target_closure"]:
                            result["status"] = ("needs_causal_review" if thrown
                                                else "unrelated_target")
                        else:
                            result["status"] = ("candidate" if thrown else
                                                "healthy_seed" if not faults
                                                else "checked")
        except (ValueError, FileNotFoundError, subprocess.SubprocessError,
                OSError) as failure:
            result["status"] = ("blocked_healthy_native_session" if not faults
                                else "invalid_native_session")
            result["analysis_error"] = str(failure)
    _atomic(trial / "result.json", result)
    return result


def _accept(state: dict[str, Any], result: dict[str, Any], name: str) -> None:
    active = state["active"]
    if active is None or active["name"] != name or active["faults"] != result["faults"]:
        raise ValueError("native campaign active trial identity changed")
    state["elapsed_seconds"] = round(state["elapsed_seconds"] +
                                     result["elapsed_seconds"], 3)
    if active["index"] == 0:
        state["healthy"] = {"name": name, "status": result["status"],
                            "result": f"trials/{name}/result.json"}
        if result["status"] != "healthy_seed":
            state["status"] = result["status"]
        else:
            _enqueue(state, result["eligible_doors"], [], 0)
            if not state["queue"]:
                state["status"] = "no_observed_fault_door"
    else:
        state["completed_fault_trials"] += 1
        record = {"name": name, "status": result["status"],
                  "result": f"trials/{name}/result.json",
                  "strict_injection": result["strict_injection"],
                  "native_target_retained": result["native_target_retained"],
                  "target_exception_triggered": result["target_exception_triggered"],
                  "elapsed_seconds": result["elapsed_seconds"]}
        state["trials"].append(record)
        if result["status"] in ("checked", "candidate"):
            novelty = _novelty(state, result["native_delta"])
            record["target_closure_novelty"] = novelty
            _enqueue(state, result["eligible_doors"], active["faults"], novelty)
    state["active"] = None
    _finish_status(state)


def _finish_status(state: dict[str, Any]) -> None:
    if state["status"] != "running":
        state["terminal"] = True
    elif state["completed_fault_trials"] >= state["budget"]["fault_trials"]:
        state["status"], state["terminal"] = "complete_trial_budget", True
    elif state["elapsed_seconds"] >= state["budget"]["seconds"]:
        state["status"], state["terminal"] = "complete_time_budget", True
    elif state["healthy"] is not None and not state["queue"] and state["active"] is None:
        state["status"], state["terminal"] = "complete_queue", True


def _new_state(config: dict[str, Any], config_sha: str,
               admitted: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "case_id": config["case_id"],
            "config_sha256": config_sha, "budget": config["budget"],
            "weave_receipt_sha256": _sha(Path(admitted["weave_config"][
                "output_classes"]) / "native-original-weave-receipt.json"),
            "origin": admitted["origin"],
            "zero_vm_sha256": admitted["zero_vm_sha256"],
            "runner_classpath_artifacts": admitted["runner_classpath_artifacts"],
            "status": "running", "terminal": False,
            "healthy": None, "trials": [], "queue": [], "seen_plan_keys": [],
            "seen_node_families": [], "seen_edge_families": [],
            "seen_branch_outcomes": [], "completed_fault_trials": 0,
            "elapsed_seconds": 0.0, "active": None, "next_trial_index": 1}


def _resume_active(config: dict[str, Any], admitted: dict[str, Any],
                   root: Path, state: dict[str, Any]) -> None:
    active = state["active"]
    if active is None:
        return
    name = active["name"]
    trial = root / "trials" / name
    result_file = trial / "result.json"
    if result_file.is_file():
        result = _load(result_file)
        if result.get("case_id") != state["case_id"] or result.get(
                "faults") != active["faults"]:
            raise ValueError("completed native trial disagrees with checkpoint")
        _accept(state, result, name)
        _atomic(root / "checkpoint.json", state)
        return
    if trial.exists():
        # An interrupted JVM may still be running. Refuse a duplicate until
        # a supervisor resolves the process; never infer death from a lock.
        process = trial / "process.json"
        if process.is_file():
            process_receipt = _load(process)
            pid = process_receipt.get("pid")
            if isinstance(pid, int):
                current_ticks = _start_ticks(pid)
                saved_ticks = process_receipt.get("start_ticks")
                if current_ticks and (not saved_ticks or current_ticks == saved_ticks):
                    raise RuntimeError(f"native trial process still exists: {pid}")
        interrupted = root / "interrupted"
        interrupted.mkdir(exist_ok=True)
        suffix = 1
        while (interrupted / f"{name}-attempt{suffix}").exists():
            suffix += 1
        trial.rename(interrupted / f"{name}-attempt{suffix}")
    healthy = (_load(root / "trials" / "r0000" / "native-summary.json")
               if active["index"] > 0 else None)
    result = _run_trial(config, admitted, trial, active["faults"], healthy)
    _accept(state, result, name)
    _atomic(root / "checkpoint.json", state)


def run_campaign(config_path: Path, root: Path) -> dict[str, Any]:
    config_path = config_path.resolve(strict=True)
    config = _load(config_path)
    _validate_config(config)
    config_sha = _sha(config_path)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".campaign.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as failure:
            raise RuntimeError("native campaign is owned by another worker") from failure
        admitted = _admit(config, root)
        checkpoint = root / "checkpoint.json"
        if checkpoint.is_file():
            state = _load(checkpoint)
            if (state.get("schema_version") != SCHEMA or
                    state.get("case_id") != config["case_id"] or
                    state.get("config_sha256") != config_sha or
                    state.get("budget") != config["budget"] or
                    state.get("weave_receipt_sha256") != _sha(Path(admitted[
                        "weave_config"]["output_classes"]) /
                        "native-original-weave-receipt.json") or
                    state.get("origin") != admitted["origin"] or
                    state.get("zero_vm_sha256") != admitted["zero_vm_sha256"] or
                    state.get("runner_classpath_artifacts") != admitted[
                        "runner_classpath_artifacts"]):
                raise ValueError("native checkpoint inputs changed")
        else:
            state = _new_state(config, config_sha, admitted)
            _atomic(checkpoint, state)
        if state["terminal"]:
            return state
        (root / "trials").mkdir(exist_ok=True)
        if state["healthy"] is None and state["active"] is None:
            state["active"] = {"index": 0, "name": "r0000", "faults": []}
            _atomic(checkpoint, state)
        _resume_active(config, admitted, root, state)
        while not state["terminal"]:
            _finish_status(state)
            if state["terminal"]:
                break
            if state["active"] is None:
                selected = _pick(state)
                index = state["next_trial_index"]
                state["next_trial_index"] += 1
                state["active"] = {"index": index, "name": f"r{index:04d}",
                                   "faults": selected["faults"]}
                _atomic(checkpoint, state)
            _resume_active(config, admitted, root, state)
        _atomic(checkpoint, state)
        _atomic(root / "summary.json", {key: value for key, value in state.items()
                                         if key not in ("queue", "seen_plan_keys", "active")})
        return state
