"""One-weave, fresh-JUnit native GraphChecker fault campaign.

This driver consumes the original GraphChecker concolic weave and native
SessionReader feedback. An adapter must emit typed FAULT_DOOR, FAULT_APPLIED,
and TARGET_THROW receipts at the event; the campaign never infers an applied
fault from a failed JUnit or a static candidate site.
"""

from __future__ import annotations

import fcntl
import hashlib
from collections import Counter
import json
import os
import re
import shutil
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
from Mallory.native_graphchecker_feedback.region_state_graph import (
    _closed_inputs, delta_region_state, record_region_state,
)
from Mallory.native_graphchecker_feedback.multi_target import (
    record_multiple_region_states, record_pinned_region_states,
)
from .source_preflight import feedback_bridge
from .static_may import rpc_producer_sites
from .peer_identity import rank_region_doors_by_peer

SCHEMA = 1
SCHEDULER_VERSION = 10
FAULT_FIELDS = ("siteId", "node", "actorEpochOrdinal", "occurrenceId",
                "ordinal", "exceptionClass")
SELECTOR_FIELDS = ("siteId", "node", "actorEpochOrdinal", "ordinal",
                   "exceptionClass")
MAX_FAULTS = 10
MAX_UNMATCHED_RETRIES = 2
SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
MESSAGE_FIELDS = ("messageReplayKey", "messageParentId")


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
    if any(not isinstance(recording.get(key, []), list) or
           not all(isinstance(arg, str) and arg.startswith("-D")
                   for arg in recording.get(key, []))
           for key in ("recorder_jvm_args", "scheduler_jvm_args")):
        raise ValueError("recording JVM arguments must be JVM properties")
    if (recording.get("target_occurrence") is not None and
            (not isinstance(recording["target_occurrence"], str) or
             not recording["target_occurrence"])):
        raise ValueError("recording target_occurrence must be an exact ID")
    anchor_count = recording.get("multi_target_max_anchors")
    if anchor_count is not None and (
            not isinstance(anchor_count, int) or isinstance(anchor_count, bool)
            or not 2 <= anchor_count <= 16 or
            recording.get("target_occurrence") is not None or
            recording.get("admission_mode") != "region_state_no_schedule" or
            not isinstance(config.get("runner"), dict) or
            config["runner"].get("mode") != "region_state"):
        raise ValueError("multi-target anchors require task-free REGION_STATE")
    may_path = recording.get("static_may_scope_map")
    may_sha = recording.get("static_may_scope_map_sha256")
    if (may_path is None) != (may_sha is None) or (may_path is not None and
            (not isinstance(may_path, str) or
             not Path(may_path).is_absolute() or
             not isinstance(may_sha, str) or
             not SHA256_HEX.fullmatch(may_sha))):
        raise ValueError("static MAY scope requires an absolute path and SHA-256 pin")
    precomputed = recording.get("precomputed_schedule")
    if precomputed is not None and (not isinstance(precomputed, str) or
                                    not Path(precomputed).is_absolute()):
        raise ValueError("precomputed schedule receipt must be an absolute path")
    admission_mode = recording.get("admission_mode", "scheduled")
    if admission_mode not in ("scheduled", "region_state_no_schedule"):
        raise ValueError("unknown original recording admission mode")
    if precomputed is not None and admission_mode != "scheduled":
        raise ValueError("task-free admission cannot reuse a scheduled plan")
    analysis_jar = recording.get("analysis_engine_jar")
    analysis_sha = recording.get("analysis_engine_sha256")
    has_analysis_jar = "analysis_engine_jar" in recording
    has_analysis_sha = "analysis_engine_sha256" in recording
    if (has_analysis_jar != has_analysis_sha or
            (has_analysis_jar and
             (not isinstance(config.get("runner"), dict) or
              config["runner"].get("mode") != "region_state"))):
        raise ValueError("analysis engine requires a REGION_STATE path and SHA-256 pin")
    if has_analysis_jar and (
            not isinstance(analysis_jar, str) or
            not Path(analysis_jar).is_absolute() or
            not isinstance(analysis_sha, str) or
            not SHA256_HEX.fullmatch(analysis_sha)):
        raise ValueError("analysis engine requires an absolute path and SHA-256 pin")
    heap_mb = recording.get("graph_analysis_heap_mb", 3072)
    if (not isinstance(heap_mb, int) or isinstance(heap_mb, bool) or
            not 0 < heap_mb <= 65536):
        raise ValueError("graph_analysis_heap_mb must be within 1..65536")
    for key in ("admission_timeout_seconds", "graph_analysis_timeout_seconds"):
        seconds = recording.get(key, 300)
        if (not isinstance(seconds, int) or isinstance(seconds, bool) or
                not 0 < seconds <= 3600):
            raise ValueError(f"{key} must be within 1..3600")
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
            not all(isinstance(item, str) for item in runner.get("jvm_args", [])) or
            not isinstance(runner.get("args_before_test", []), list) or
            not all(isinstance(item, str) and item and
                    ("{" not in item and "}" not in item or
                     item == "{trial_result_file}")
                    for item in runner.get("args_before_test", []))):
        raise ValueError("native campaign requires bounded Zero VM JUnit runner")
    local_work_root = runner.get("local_work_root")
    if local_work_root is not None and (
            not isinstance(local_work_root, str) or
            not local_work_root or
            not Path(local_work_root).is_absolute()):
        raise ValueError("runner.local_work_root must be an absolute path")
    local_artifact_root = runner.get("local_artifact_root")
    if local_artifact_root is not None and (
            not isinstance(local_artifact_root, str) or
            not local_artifact_root or
            not Path(local_artifact_root).is_absolute()):
        raise ValueError("runner.local_artifact_root must be an absolute path")
    marker = runner.get("result_marker")
    if marker is not None and (not isinstance(marker, str) or
                               not re.fullmatch(r"[A-Z][A-Z0-9_]*", marker)):
        raise ValueError("runner result_marker must be an exact identifier")
    if runner.get("mode", "concolic") not in ("concolic", "region_state"):
        raise ValueError("runner mode must be concolic or region_state")
    if (admission_mode == "region_state_no_schedule" and
            runner.get("mode") != "region_state"):
        raise ValueError("no-schedule admission requires REGION_STATE runner")
    if (runner.get("mode") == "region_state" and
            recording["test_id"] != junit["class"] + "#" + junit["method"]):
        raise ValueError("recording test_id must match the original JUnit workload")
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
    predecessor = config.get("predecessor_campaign")
    if predecessor is not None:
        names = ("config", "checkpoint", "summary")
        derived = ("tested_plan_keys_sha256", "source_result_tree_sha256",
                   "source_unmatched_event_tree_sha256")
        optional = {"source_all_event_tree_sha256"}
        if (not isinstance(predecessor, dict) or
                set(predecessor) not in (
                    {name for item in names for name in (item, item + "_sha256")} |
                    set(derived),
                    {name for item in names for name in (item, item + "_sha256")} |
                    set(derived) | optional) or
                any(not isinstance(predecessor[name], str) or
                    not predecessor[name].startswith("/") or
                    not isinstance(predecessor[name + "_sha256"], str) or
                    not SHA256_HEX.fullmatch(predecessor[name + "_sha256"])
                    for name in names) or
                any(not isinstance(predecessor[name], str) or
                    not SHA256_HEX.fullmatch(predecessor[name])
                    for name in set(derived) | (set(predecessor) & optional))):
            raise ValueError("predecessor_campaign needs exact paths and SHA-256 pins")


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


def _skeleton_lineage(static_skeletons: Path, woven_skeletons: Path,
                      selected_skeletons: Path) -> dict[str, str]:
    """Bind the weave to the static input and retain the recorder's selection.

    The recorder emits the selected runtime skeleton set. It is intentionally
    smaller than the static skeleton set supplied to the concolic weave.
    """
    if not selected_skeletons.is_file():
        raise ValueError("original recorder produced no selected region skeletons")
    static_sha = _sha(static_skeletons)
    if _sha(woven_skeletons) != static_sha:
        raise ValueError("woven regions differ from the pinned static skeletons")
    return {"static_skeletons_sha256": static_sha,
            "selected_skeletons_sha256": _sha(selected_skeletons)}


def _task_plan_lineage(full_plan: Path, woven_plan: Path,
                       task_id: str) -> dict[str, str]:
    """Accept the full schedule or one byte-identical task selected from it."""
    with woven_plan.open("rb") as stream:
        selected = [line.rstrip(b"\r\n") for line in stream if line.strip()]
    if not selected:
        raise ValueError("woven GraphChecker task plan is empty")
    try:
        selected_ids = [json.loads(line).get("taskId") for line in selected]
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("woven GraphChecker task plan is invalid JSONL") from error
    if task_id not in selected_ids:
        raise ValueError("weave task ID is absent from its task plan")
    full_sha = _sha(full_plan)
    woven_sha = _sha(woven_plan)
    if full_sha != woven_sha:
        if len(selected) != 1 or selected_ids != [task_id]:
            raise ValueError("selected GraphChecker task must contain one exact task")
        matches = 0
        with full_plan.open("rb") as stream:
            for line in stream:
                if line.rstrip(b"\r\n") == selected[0]:
                    matches += 1
        if matches != 1:
            raise ValueError("selected GraphChecker task differs from full schedule")
    return {"recording_plan_sha256": full_sha,
            "selected_task_plan_sha256": woven_sha}


def _region_state_plan_lineage(full_plan: Path, index: Path,
                               woven_plan: Path | None) -> dict[str, Any]:
    """Pin the recorder schedule without comparing an unused weave task.

    REGION_STATE runs do not publish a concolic task to the JVM. The original
    scheduler can give the same task a different dynamic root call ID when a
    healthy trace is rerun, while the static region and native hook pins stay
    identical. Concolic campaigns retain exact task-row matching.
    """
    rows = [json.loads(line) for line in full_plan.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if not rows or any(not isinstance(row, dict) or
                       not isinstance(row.get("taskId"), str) or
                       not row["taskId"] for row in rows):
        raise ValueError("original scheduler produced no valid task")
    lineage = {"recording_plan_sha256": _sha(full_plan),
               "recording_index_sha256": _sha(index),
               "recording_plan_task_count": len(rows)}
    if woven_plan is not None:
        lineage["unused_weave_task_plan_sha256"] = _sha(woven_plan)
    return lineage


def _precomputed_command(config: dict[str, Any], receipt: Path,
                         main_class: str, program_args: list[str],
                         jvm_properties: list[str]) -> str:
    """Check the *executed* original JVM command, not an asserted plan label.

    Heap size may differ between preparation and admission. All properties,
    classpath entries, GraphChecker arguments, and their order must agree.
    """
    argv = _load(receipt).get("argv")
    if not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv):
        raise ValueError("precomputed GraphChecker command has no argv")
    java = str(Path(_load(Path(config["native_weave_config"]))["java"]))
    classpath = f"{JAR}:{DEPENDENCIES.read_text(encoding='utf-8').strip()}"
    if not argv or Path(argv[0]).resolve(strict=True) != Path(java).resolve(strict=True):
        raise ValueError("precomputed GraphChecker Java executable differs")
    try:
        cp_index = argv.index("-cp")
    except ValueError as error:
        raise ValueError("precomputed GraphChecker classpath is missing") from error
    jvm = argv[1:cp_index]
    if (not all(arg.startswith("-Xmx") or arg.startswith("-D") for arg in jvm) or
            [arg for arg in jvm if arg.startswith("-D")] != jvm_properties or
            argv[cp_index + 1:] != [classpath, main_class, *program_args]):
        raise ValueError("precomputed GraphChecker command differs from admission")
    return _sha(receipt)


def _precomputed_body(config: dict[str, Any], recorded: Path,
                      scheduled: Path, recorder_command: Path,
                      scheduler_command: Path) -> dict[str, Any]:
    """Bind reusable plan bytes to the unchanged CLOSED trace and arguments."""
    rec = config["recording"]
    trace = Path(rec["trace_dir"]).resolve(strict=True)
    graph = Path(rec["candidate_graph"]).resolve(strict=True)
    scope = Path(rec["static_scope_map"]).resolve(strict=True)
    skeletons = Path(rec["region_skeletons"]).resolve(strict=True)
    recorded, scheduled = recorded.resolve(strict=True), scheduled.resolve(strict=True)
    recorder_command = recorder_command.resolve(strict=True)
    scheduler_command = scheduler_command.resolve(strict=True)
    from Mallory.native_graphchecker_feedback.artifacts import region_plan_path
    plan = region_plan_path(recorded)
    selected = recorded / "region_skeletons.jsonl"
    generated = scheduled / "execution_task_plan.jsonl"
    index = scheduled / "runtime_workflow_schedule_index.json"
    closed = _closed_inputs(trace, scope, graph, skeletons)
    _scheduler_source()
    recorder_args = ["--trace-dir", str(trace), "--test", rec["test_id"],
                     "--target", f"{rec['target_name']}={graph},{scope},{skeletons},{recorded}"]
    scheduler_args = ["--region-plan", str(plan),
                      "--candidate-graph", str(graph),
                      "--static-scope-map", str(scope),
                      "--output-dir", str(scheduled),
                      "--max-jobs", str(rec["max_jobs"])]
    if rec.get("target_occurrence"):
        recorder_args.extend(("--target-occurrence", rec["target_occurrence"]))
        scheduler_args.extend(("--target-occurrence", rec["target_occurrence"]))
    commands = {
        "recorder": _precomputed_command(config, recorder_command,
            "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
            recorder_args, rec.get("recorder_jvm_args", [])),
        "scheduler": _precomputed_command(config, scheduler_command,
            "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler",
            scheduler_args, rec.get("scheduler_jvm_args", [])),
    }
    weave = _load(Path(config["native_weave_config"]).resolve(strict=True))
    woven_skeletons = Path(weave["region_skeletons"]).resolve(strict=True)
    if _sha(woven_skeletons) != closed["regionSkeletonsSha256"]:
        raise ValueError("precomputed GraphChecker skeletons differ from weave")
    return {"schema_version": 1, "closed_inputs": closed,
            "test_id": rec["test_id"], "target_name": rec["target_name"],
            "target_occurrence": rec.get("target_occurrence"),
            "max_jobs": rec["max_jobs"],
            "recorder_jvm_args": rec.get("recorder_jvm_args", []),
            "scheduler_jvm_args": rec.get("scheduler_jvm_args", []),
            "engine_jar_sha256": _sha(JAR),
            "dependencies_sha256": _sha(DEPENDENCIES),
            "java_sha256": _sha(Path(weave["java"]).resolve(strict=True)),
            "scheduler_source_sha256": _sha(_scheduler_source()),
            "recorded": str(recorded), "scheduled": str(scheduled),
            "recorder_command": str(recorder_command),
            "scheduler_command": str(scheduler_command),
            "command_sha256": commands,
            "artifacts_sha256": {
                "region_plan": _sha(plan),
                "selected_skeletons": _sha(selected),
                "execution_task_plan": _sha(generated),
                "schedule_index": _sha(index)}}


def seal_precomputed_schedule(config: dict[str, Any], recorded: Path,
                              scheduled: Path, recorder_command: Path,
                              scheduler_command: Path, receipt: Path) -> dict[str, Any]:
    """Seal successful preparation output for later same-trace admission."""
    if receipt.exists():
        raise ValueError("precomputed schedule receipt already exists")
    if config["recording"].get("admission_mode", "scheduled") != "scheduled":
        raise ValueError("task-free admission has no schedule to seal")
    body = _precomputed_body(config, recorded, scheduled, recorder_command,
                             scheduler_command)
    _atomic(receipt, body)
    return body


def _verified_precomputed_origin(config: dict[str, Any], weave: dict[str, Any]
                                 ) -> dict[str, Any]:
    receipt = Path(config["recording"]["precomputed_schedule"]).resolve(strict=True)
    value = _load(receipt)
    actual = _precomputed_body(config, Path(value["recorded"]),
                               Path(value["scheduled"]),
                               Path(value["recorder_command"]),
                               Path(value["scheduler_command"]))
    if value != actual:
        raise ValueError("precomputed GraphChecker schedule inputs or outputs changed")
    rec = config["recording"]
    recorded, scheduled = Path(value["recorded"]), Path(value["scheduled"])
    generated = scheduled / "execution_task_plan.jsonl"
    index = scheduled / "runtime_workflow_schedule_index.json"
    planned = Path(weave["task_plan"]).resolve(strict=True) if weave.get(
        "task_plan") else None
    if config["runner"].get("mode") == "region_state":
        lineage = _region_state_plan_lineage(generated, index, planned)
    else:
        if planned is None:
            raise ValueError("concolic campaign requires a woven task plan")
        lineage = _task_plan_lineage(generated, planned, weave["task_id"])
    return {"recording_manifest_sha256": value["closed_inputs"][
                "traceManifestSha256"],
            **lineage,
            "scheduler_source_sha256": value["scheduler_source_sha256"],
            "static_scope_map_sha256": value["closed_inputs"]["scopeMapSha256"],
            **_skeleton_lineage(Path(rec["region_skeletons"]),
                                Path(weave["region_skeletons"]),
                                recorded / "region_skeletons.jsonl"),
            "precomputed_schedule_receipt_sha256": _sha(receipt)}


def _verify_recording_plan(config: dict[str, Any], weave: dict[str, Any],
                           campaign_root: Path) -> dict[str, Any]:
    """Bind original recording provenance; schedule unless explicitly task-free.

    The source-built recorder validates the closed region-state recording's
    TracedRows digest against the same static artifacts before planning.
    Scheduled re-aggregation occurs once at admission. Task-free REGION_STATE
    runs the original graph stages on each fresh JUnit trial instead.
    Concolic task plans must match the pinned weave exactly.
    """
    rec = config["recording"]
    admission_timeout = rec.get("admission_timeout_seconds", 300)
    analysis_heap = f"-Xmx{rec.get('graph_analysis_heap_mb', 3072)}m"
    planned = (Path(weave["task_plan"]).resolve(strict=True)
               if weave.get("task_plan") else None)
    if config["runner"].get("mode") != "region_state" and planned is None:
        raise ValueError("concolic campaign requires a woven task plan")
    scope = Path(rec["static_scope_map"]).resolve(strict=True)
    skeletons = Path(rec["region_skeletons"]).resolve(strict=True)
    woven_skeletons = Path(weave["region_skeletons"]).resolve(strict=True)
    graph = Path(rec["candidate_graph"]).resolve(strict=True)
    trace = Path(rec["trace_dir"]).resolve(strict=True)
    if not (trace / "streaming_trace_manifest.json").is_file():
        raise ValueError("closed original region-state recording is missing")
    if rec.get("admission_mode") == "region_state_no_schedule":
        if planned is not None or weave.get("task_id"):
            raise ValueError("no-schedule REGION_STATE weave carries a concolic task")
        # The fresh r0000 trial runs the original Resolver, Recorder and
        # Finalizer before it can seed a fault queue. Here we only bind the
        # closed prior recording and static input bytes to the verified weave.
        closed = _closed_inputs(trace, scope, graph, skeletons)
        if _sha(woven_skeletons) != closed["regionSkeletonsSha256"]:
            raise ValueError("woven regions differ from the pinned static skeletons")
        return {"admission_mode": "region_state_no_schedule",
                "recording_manifest_sha256": closed["traceManifestSha256"],
                "closed_inputs": closed,
                "static_scope_map_sha256": closed["scopeMapSha256"],
                "static_skeletons_sha256": closed["regionSkeletonsSha256"]}
    if rec.get("precomputed_schedule"):
        return _verified_precomputed_origin(config, weave)
    admission_scratch = campaign_root
    if config["runner"].get("local_artifact_root") is not None:
        _validate_local_artifact_root(config, campaign_root)
        admission_scratch = Path(config["runner"]["local_artifact_root"]).resolve()
    with tempfile.TemporaryDirectory(prefix=".recording-admission-",
                                     dir=admission_scratch) as scratch:
        output = Path(scratch) / "recorded"
        scheduled = Path(scratch) / "scheduled"
        _scheduler_source()
        classpath = f"{JAR}:{DEPENDENCIES.read_text(encoding='utf-8').strip()}"
        target = ",".join((str(graph), str(scope), str(skeletons), str(output)))
        command = [str(Path(weave["java"]).resolve(strict=True)), analysis_heap,
                   *rec.get("recorder_jvm_args", []), "-cp",
                   classpath,
                   "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
                   "--trace-dir", str(trace), "--test", rec["test_id"],
                   "--target", f"{rec['target_name']}={target}"]
        if rec.get("target_occurrence"):
            command.extend(("--target-occurrence", rec["target_occurrence"]))
        subprocess.run(command, check=True, timeout=admission_timeout,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        from Mallory.native_graphchecker_feedback.artifacts import region_plan_path
        region_plan = region_plan_path(output)
        if not region_plan.is_file():
            raise ValueError("original recorder produced no region plan")
        scheduler = [str(Path(weave["java"]).resolve(strict=True)), analysis_heap,
                     *rec.get("scheduler_jvm_args", []), "-cp",
                     classpath,
                     "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler",
                     "--region-plan", str(region_plan),
                     "--candidate-graph", str(graph),
                     "--static-scope-map", str(scope),
                     "--output-dir", str(scheduled),
                     "--max-jobs", str(rec["max_jobs"])]
        if rec.get("target_occurrence"):
            scheduler.extend(("--target-occurrence", rec["target_occurrence"]))
        subprocess.run(scheduler, check=True, timeout=admission_timeout,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        generated = scheduled / "execution_task_plan.jsonl"
        index = scheduled / "runtime_workflow_schedule_index.json"
        if not generated.is_file() or not index.is_file():
            raise ValueError("original scheduler produced no complete task plan")
        if config["runner"].get("mode") == "region_state":
            task_plan_lineage = _region_state_plan_lineage(generated, index, planned)
        else:
            assert planned is not None
            task_plan_lineage = _task_plan_lineage(generated, planned, weave["task_id"])
        skeleton_lineage = _skeleton_lineage(
            skeletons, woven_skeletons, output / "region_skeletons.jsonl")
    return {"recording_manifest_sha256": _sha(trace / "streaming_trace_manifest.json"),
            **task_plan_lineage,
            "scheduler_source_sha256": _sha(_scheduler_source()),
            "static_scope_map_sha256": _sha(scope),
            **skeleton_lineage}


def _feedback_required(config: dict[str, Any]) -> bool:
    return config["runner"].get("mode", "concolic") == "concolic"


def _analysis_engine_jar(config: dict[str, Any]) -> Path:
    """Pin the optional region analyzer separately from the woven trace engine."""
    recording = config["recording"]
    if "analysis_engine_jar" not in recording:
        return JAR
    path = Path(recording["analysis_engine_jar"]).resolve(strict=True)
    if not path.is_file() or _sha(path) != recording["analysis_engine_sha256"]:
        raise ValueError("analysis engine SHA-256 mismatch")
    return path


def _require_exact_resolver_protocol(config: dict[str, Any],
                                     java: Path) -> dict[str, Any] | None:
    """Reject an analysis JAR that cannot prove exact occurrence selection.

    This runs during admission, before the original workload JUnit. The
    woven/runtime engine remains a separate, unchanged source pin.
    """
    if (config["runner"].get("mode") != "region_state" or
            not config["recording"].get("target_occurrence")):
        return None
    analyzer = _analysis_engine_jar(config)
    dependencies = DEPENDENCIES.read_text(encoding="utf-8").strip()
    if not dependencies:
        raise ValueError("original GraphChecker dependency classpath is empty")
    command = [str(java.resolve(strict=True)), "-cp",
               os.pathsep.join((str(analyzer), dependencies)),
               "edu.uva.liftlab.graphchecker.runtime.MalloryTargetOccurrenceResolver",
               "--capabilities"]
    try:
        probe = subprocess.run(command, text=True, capture_output=True,
                               timeout=20, check=False)
        capabilities = json.loads(probe.stdout) if probe.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as failure:
        raise ValueError("exact target resolver protocol preflight failed") from failure
    if (not isinstance(capabilities, dict) or
            capabilities.get("schemaVersion") != 1 or
            capabilities.get("kind") != "MALLORY_TARGET_RESOLVER_CAPABILITIES" or
            capabilities.get("exactRequestedOccurrenceReceiptSchemaVersion") != 2 or
            capabilities.get("exactSelectionPolicy") !=
            "EXACT_REQUESTED_OCCURRENCE_THEN_EARLIEST_EVENT"):
        raise ValueError("analysis engine lacks exact occurrence receipt schema 2")
    return {"analysis_engine_jar_sha256": _sha(analyzer),
            "capabilities": capabilities}


def _admit(config: dict[str, Any], root: Path) -> dict[str, Any]:
    # The Java bridge is consumed by concolic SessionReader feedback. Original
    # REGION_STATE replay uses the resolver/Recorder directly and has no bridge.
    feedback_source = (feedback_bridge(Path(__file__).resolve().parents[2], JAR)
                       if _feedback_required(config)
                       else None)
    weave_file = Path(config["native_weave_config"]).resolve(strict=True)
    weave_receipt = verify_existing(weave_file)
    weave = _load(weave_file)
    rec = config["recording"]
    resolver_protocol = (_require_exact_resolver_protocol(
        config, Path(weave["java"]))
        if (config["runner"].get("mode") == "region_state" and
            rec.get("target_occurrence")) else None)
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
    if resolver_protocol is not None:
        recording_fingerprint["resolver_protocol"] = resolver_protocol
    if "static_may_scope_map" in rec:
        may_path = Path(rec["static_may_scope_map"]).resolve(strict=True)
        may_sha = _sha(may_path)
        if may_sha != rec["static_may_scope_map_sha256"]:
            raise ValueError("static MAY scope SHA-256 mismatch")
        rpc_producer_sites(str(may_path), may_sha, config["target_site"])
        recording_fingerprint["static_may_scope_map"] = str(may_path)
        recording_fingerprint["static_may_scope_map_sha256"] = may_sha
    if "analysis_engine_jar" in rec:
        analyzer = _analysis_engine_jar(config)
        recording_fingerprint["analysis_engine_jar"] = str(analyzer)
        recording_fingerprint["analysis_engine_sha256"] = rec[
            "analysis_engine_sha256"]
    if rec.get("admission_mode") == "region_state_no_schedule":
        recording_fingerprint["admission_mode"] = "region_state_no_schedule"
    if rec.get("precomputed_schedule"):
        receipt = Path(rec["precomputed_schedule"]).resolve(strict=True)
        recording_fingerprint["precomputed_schedule"] = str(receipt)
        recording_fingerprint["precomputed_schedule_sha256"] = _sha(receipt)
    if feedback_source is not None:
        recording_fingerprint["feedback_source"] = feedback_source
    admission = root / "recording-admission.json"
    if admission.is_file():
        cached = _load(admission)
        if (cached.get("schema_version") != SCHEMA or
                cached.get("recording_fingerprint") != recording_fingerprint or
                not isinstance(cached.get("origin"), dict)):
            raise ValueError("cached native recording admission inputs changed")
        origin = cached["origin"]
        if rec.get("precomputed_schedule") and origin != (
                _verified_precomputed_origin(config, weave)):
            raise ValueError("cached precomputed GraphChecker schedule changed")
    else:
        origin = _verify_recording_plan(config, weave, root)
        if "static_may_scope_map_sha256" in recording_fingerprint:
            origin["static_may_scope_map_sha256"] = recording_fingerprint[
                "static_may_scope_map_sha256"]
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
    rec = config["recording"]
    if "static_may_scope_map" in rec:
        may_path = Path(rec["static_may_scope_map"]).resolve(strict=True)
        if (_sha(may_path) != rec["static_may_scope_map_sha256"] or
                admitted["origin"].get("static_may_scope_map_sha256") !=
                rec["static_may_scope_map_sha256"]):
            raise ValueError("native static MAY scope map changed during campaign")
    if dependency_digests(os.pathsep.join(config["runner"]["classpath"])) != (
            admitted["runner_classpath_artifacts"]):
        raise ValueError("JUnit runner classpath changed during campaign")


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    previous_by_actor: dict[tuple[str, int], int] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("kind") not in (
                "FAULT_DOOR", "FAULT_APPLIED", "TARGET_CHECK", "TARGET_THROW",
                "ENDPOINT_EXPORT", "ENDPOINT_ATTACH"):
            raise ValueError(f"invalid native fault receipt row {number}")
        seq = row.get("seq")
        node = row.get("node")
        epoch = row.get("actorEpochOrdinal")
        if (not isinstance(seq, int) or isinstance(seq, bool) or seq <= 0 or
                not isinstance(node, str) or not node or
                not isinstance(epoch, int) or isinstance(epoch, bool) or
                epoch < 0):
            raise ValueError(f"invalid native fault receipt actor/seq {number}")
        actor = (node, epoch)
        if seq <= previous_by_actor.get(actor, -1):
            raise ValueError(f"nonmonotone native fault receipt seq {number}")
        previous_by_actor[actor] = seq
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
        if any(field in planned for field in MESSAGE_FIELDS) and not all(
                SHA256_HEX.fullmatch(planned.get(field, ""))
                for field in MESSAGE_FIELDS):
            return False, None
        # The source occurrence is an audit address from a prior JVM. A new
        # JVM binds the selector to a fresh exact occurrence at its door.
        keyed = all(SHA256_HEX.fullmatch(planned.get(field, ""))
                    for field in MESSAGE_FIELDS)
        if keyed:
            match = (all(actual.get(field) == planned[field]
                         for field in ("siteId", "exceptionClass", *MESSAGE_FIELDS))
                     and sum(all(door.get(field) == planned[field]
                                 for field in ("siteId", "exceptionClass",
                                               *MESSAGE_FIELDS))
                             for door in doors) == 1)
        else:
            match = tuple(actual.get(field) for field in SELECTOR_FIELDS) == tuple(
                    planned.get(field) for field in SELECTOR_FIELDS)
        if not match:
            return False, None
        if not any(door["seq"] < actual["seq"] and
                   _fault_identity(door, applied=False) == identity
                   for door in doors):
            return False, None
    return True, applied[-1]["seq"] if applied else None


def _target_throw_observations(
        rows: list[dict[str, Any]], target_site: str,
        target_throw: dict[str, str], *, after_index: int = -1
        ) -> list[dict[str, Any]]:
    """Pair exact target checks and throws on one actor and occurrence."""
    checks: dict[tuple[str, str, int], tuple[int, dict[str, Any]]] = {}
    observed: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if index <= after_index:
            continue
        identity = (row.get("occurrenceId"), row.get("node"),
                    row.get("actorEpochOrdinal"))
        if row["kind"] == "TARGET_CHECK" and (
                row.get("siteId") == target_site or
                row.get("targetAnchorSiteId") == target_site):
            checks[identity] = (index, row)
        elif (row["kind"] == "TARGET_THROW" and identity in checks and
              row.get("siteId") == target_throw["siteId"] and
              row.get("exceptionClass") == target_throw["exceptionClass"] and
              row.get("actualExceptionClass",
                      row.get("exceptionClass")) ==
              target_throw["exceptionClass"]):
            check_index, check = checks[identity]
            if check_index < index:
                observed.append({"throwSeq": row["seq"],
                                 "checkSeq": check["seq"],
                                 "node": row.get("node"),
                                 "actorEpochOrdinal": row.get(
                                     "actorEpochOrdinal"),
                                 "occurrenceId": row.get("occurrenceId")})
    return observed


def _raw_prefix_target_throws(
        faults: list[dict[str, Any]], rows: list[dict[str, Any]],
        target_site: str, target_throw: dict[str, str]) -> dict[str, Any]:
    """Record an exact throw after a verified applied prefix, without an oracle.

    Rows from different actors have no proven causal order. Their append order
    only makes this a lead for source and lifecycle review; strict admission
    still requires the entire plan and original graph/temporal checks.
    """
    applied_positions = [index for index, row in enumerate(rows)
                         if row["kind"] == "FAULT_APPLIED"]
    prefix_size = len(applied_positions)
    if (not faults or not prefix_size or prefix_size > len(faults) or
            not _strict_faults(faults[:prefix_size], rows)[0]):
        return {"appliedPrefixCount": 0, "targetThrows": [],
                "lifecycleContext": "not_applicable",
                "causalAttribution": "unproven"}
    observed = _target_throw_observations(
        rows, target_site, target_throw, after_index=applied_positions[-1])
    return {"appliedPrefixCount": prefix_size, "targetThrows": observed,
            "lifecycleContext": "unclassified" if observed else
            "not_applicable", "causalAttribution": "unproven"}


def _unmatched_actor_successors(
        faults: list[dict[str, Any]], rows: list[dict[str, Any]]
        ) -> tuple[int, list[dict[str, Any]]]:
    """Rebase a missing fault on an observed actor after a proven prefix.

    The receipt file is an append-only interleaving. Its row order locates
    doors after the last applied fault; per-actor ``seq`` values cannot order
    events from different actors. A successor still uses the full exact
    selector, and the old occurrence ID is retained only as provenance.
    """
    applied_positions = [index for index, row in enumerate(rows)
                         if row["kind"] == "FAULT_APPLIED"]
    prefix_size = len(applied_positions)
    if not faults or prefix_size >= len(faults):
        return 0, []
    valid_prefix, _ = _strict_faults(faults[:prefix_size], rows)
    if not valid_prefix:
        return 0, []
    missing = faults[prefix_size]
    after_index = applied_positions[-1] if applied_positions else -1
    missing_actor = (missing["node"], missing["actorEpochOrdinal"])
    successors = []
    seen = set()
    for index, row in enumerate(rows):
        if index <= after_index or row["kind"] != "FAULT_DOOR":
            continue
        if (row.get("siteId"), row.get("exceptionClass")) != (
                missing["siteId"], missing["exceptionClass"]):
            continue
        if (row.get("node"), row.get("actorEpochOrdinal")) == missing_actor:
            continue
        try:
            _fault_identity(row, applied=True)
        except ValueError:
            continue
        fault = {field: row[field] for field in SELECTOR_FIELDS}
        fault["sourceOccurrenceId"] = row["occurrenceId"]
        key = _plan_key([*faults[:prefix_size], fault])
        if key in seen:
            continue
        seen.add(key)
        successors.append({"fault": fault, "seq": row["seq"],
                           "tier": "outside_closure"})
    return prefix_size, successors


def _exact_throws(rows: list[dict[str, Any]], summary: dict[str, Any],
                  target: dict[str, str], last_fault_seq: int | None
                  ) -> list[dict[str, Any]]:
    if last_fault_seq is None:
        return []
    targets = set(summary["targetOccurrenceIds"])
    # The fault and target may run in different processes. Their local
    # receipt sequences cannot be compared here; candidate admission later
    # requires the throw after TARGET_CHECK on the target actor itself.
    return [row for row in rows if row["kind"] == "TARGET_THROW" and
            row.get("siteId") == target["siteId"] and
            row.get("exceptionClass") == target["exceptionClass"] and
            row.get("occurrenceId") in targets]


def _wire_path(fault: dict[str, Any], check: dict[str, Any],
               plan: dict[str, Any], rows: list[dict[str, Any]]
               ) -> list[dict[str, Any]] | None:
    """Prove a WIRE path with exact endpoints and only local receipt order."""
    members = {item["occurrenceId"]: item for item in plan["closureMembers"]}
    session = plan["sessionId"]

    def actor(row: dict[str, Any], occurrence: str) -> bool:
        member = members.get(occurrence)
        epoch = row.get("actorEpochOrdinal")
        return (member is not None and row.get("occurrenceId") == occurrence and
                isinstance(row.get("node"), str) and row["node"] and
                isinstance(epoch, int) and not isinstance(epoch, bool) and
                epoch >= 0 and member.get("node") ==
                f"{row['node']}#epoch{epoch}")

    if not actor(fault, fault["occurrenceId"]) or not actor(
            check, plan["targetOccurrenceId"]):
        return None

    adjacency: dict[str, list[tuple[dict[str, Any], dict[str, Any],
                                    dict[str, Any]]]] = {}
    for edge in plan["observedEdgesWithinClosure"]:
        if edge.get("type") != "WIRE":
            continue
        source = edge.get("producerOccurrenceId")
        destination = edge.get("consumerOccurrenceId")
        evidence = edge.get("evidence")
        if (not isinstance(source, str) or not isinstance(destination, str) or
                not isinstance(evidence, dict)):
            continue
        producer = evidence.get("producerEndpointId")
        consumer = evidence.get("consumerEndpointId")
        export_vm = evidence.get("exportSeq")
        attach_vm = evidence.get("attachSeq")
        if (not isinstance(producer, str) or not producer or
                not isinstance(consumer, str) or not consumer or
                not isinstance(export_vm, int) or isinstance(export_vm, bool) or
                not isinstance(attach_vm, int) or isinstance(attach_vm, bool)):
            continue
        exports = [row for row in rows if row["kind"] == "ENDPOINT_EXPORT" and
                   row.get("sessionId") == session and
                   row.get("endpointId") == producer and
                   isinstance(row.get("nativeVmEventId"), int) and
                   not isinstance(row["nativeVmEventId"], bool) and
                   row.get("nativeVmEventId") == export_vm and
                   actor(row, source)]
        attaches = [row for row in rows if row["kind"] == "ENDPOINT_ATTACH" and
                    row.get("sessionId") == session and
                    row.get("endpointId") == consumer and
                    row.get("producerEndpointId") == producer and
                    isinstance(row.get("nativeVmEventId"), int) and
                    not isinstance(row["nativeVmEventId"], bool) and
                    row.get("nativeVmEventId") == attach_vm and
                    actor(row, destination)]
        if len(exports) != 1 or len(attaches) != 1:
            continue
        adjacency.setdefault(source, []).append((edge, exports[0], attaches[0]))

    def walk(occurrence: str, previous: dict[str, Any], seen: set[str],
             path: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if occurrence == plan["targetOccurrenceId"]:
            if (previous["seq"] < check["seq"] and
                    (previous.get("node"), previous.get("actorEpochOrdinal")) ==
                    (check.get("node"), check.get("actorEpochOrdinal"))):
                return path
            return None
        for edge, export, attach in adjacency.get(occurrence, []):
            next_occurrence = edge["consumerOccurrenceId"]
            if (next_occurrence in seen or export["seq"] <= previous["seq"] or
                    (previous.get("node"), previous.get("actorEpochOrdinal")) !=
                    (export.get("node"), export.get("actorEpochOrdinal"))):
                continue
            item = {"type": "WIRE", "sessionId": session,
                    "producerOccurrenceId": occurrence,
                    "consumerOccurrenceId": next_occurrence,
                    "producerEndpointId": edge["evidence"]["producerEndpointId"],
                    "consumerEndpointId": edge["evidence"]["consumerEndpointId"],
                    "pairedBy": edge["evidence"].get("pairedBy"),
                    "correlationId": edge["evidence"].get("correlationId"),
                    "producerNode": export["node"],
                    "producerActorEpochOrdinal": export["actorEpochOrdinal"],
                    "consumerNode": attach["node"],
                    "consumerActorEpochOrdinal": attach["actorEpochOrdinal"],
                    "exportSeq": export["seq"], "attachSeq": attach["seq"],
                    "exportNativeVmEventId": export["nativeVmEventId"],
                    "attachNativeVmEventId": attach["nativeVmEventId"]}
            found = walk(next_occurrence, attach, seen | {next_occurrence},
                         path + [item])
            if found is not None:
                return found
        return None

    return walk(fault["occurrenceId"], fault, {fault["occurrenceId"]}, [])


def _temporal_target(rows: list[dict[str, Any]], summary: dict[str, Any],
                     target_site: str) -> tuple[bool, str, dict[str, Any] | None]:
    """Prove the final fault precedes a reached check in its causal closure.

    The fault receipt sequence and native TargetRow VM event ID are different
    clocks. Receipt order is compared only within an exact actor. A directed
    cross-occurrence WIRE path also needs paired original endpoints and
    locally ordered endpoint receipts at each hop.
    """
    applied = [row for row in rows if row["kind"] == "FAULT_APPLIED"]
    if not applied:
        return False, "no_applied_fault", None
    fault = applied[-1]
    fault_occurrence = fault["occurrenceId"]
    inside = False
    cross_occurrence = False
    saw_same_check = False
    for one in summary["perTargetOccurrences"]:
        target_occurrence = one["targetOccurrenceId"]
        closure = {item["occurrenceId"] for item in one["closureMembers"]}
        if fault_occurrence not in closure:
            continue
        inside = True
        if fault_occurrence != target_occurrence:
            cross_occurrence = True
        reached = any(row.get("occurrenceId") == target_occurrence and
                      row.get("siteId") == target_site and
                      row.get("reachedAnchor") is True
                      for row in one["targetRows"])
        if not reached:
            continue
        for check in rows:
            if (check["kind"] != "TARGET_CHECK" or
                    check.get("targetAnchorSiteId") != target_site or
                    check.get("occurrenceId") != target_occurrence or
                    check.get("node") != one.get("targetNodeName") or
                    not isinstance(check.get("actorEpochOrdinal"), int) or
                    isinstance(check["actorEpochOrdinal"], bool) or
                    check["actorEpochOrdinal"] < 0 or
                    not isinstance(check.get("siteId"), str) or
                    not check["siteId"] or
                    not (target_site == check["siteId"] or
                         target_site.startswith(check["siteId"] + "#"))):
                continue
            if fault_occurrence != target_occurrence:
                path = _wire_path(fault, check, one, rows)
                if path is not None:
                    return True, "wire_path_before_check", {
                        "faultSeq": fault["seq"], "checkSeq": check["seq"],
                        "targetOccurrenceId": target_occurrence,
                        "targetAnchorSiteId": target_site, "wirePath": path,
                    }
                continue
            if (fault.get("node") != check.get("node") or
                    fault.get("actorEpochOrdinal") !=
                    check.get("actorEpochOrdinal")):
                continue
            saw_same_check = True
            if check["seq"] > fault["seq"]:
                return True, "same_occurrence_before_check", {
                    "faultSeq": fault["seq"], "checkSeq": check["seq"],
                    "targetOccurrenceId": target_occurrence,
                    "targetAnchorSiteId": target_site,
                }
    if saw_same_check:
        return False, "post_target_fault", None
    if cross_occurrence:
        return False, "cross_occurrence_order_unproved", None
    if inside:
        return False, "target_check_not_recorded", None
    return False, "fault_outside_exact_target_closure", None


def _doors(rows: list[dict[str, Any]], summary: dict[str, Any],
           after_fault: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    closure = {item["occurrenceId"] for item in summary["closureMembers"]}
    found = []
    for row in rows:
        if row["kind"] != "FAULT_DOOR":
            continue
        if (after_fault is not None and
                (row.get("node"), row.get("actorEpochOrdinal")) ==
                (after_fault.get("node"),
                 after_fault.get("actorEpochOrdinal")) and
                row["seq"] <= after_fault["seq"]):
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
    return _prefer_unique_message_keys(found, rows)


def _plan_key(faults: list[dict[str, Any]],
              anchor_address: str | None = None) -> str:
    if any(any(field in fault for field in MESSAGE_FIELDS) and not all(
            SHA256_HEX.fullmatch(fault.get(field, ""))
            for field in MESSAGE_FIELDS) for fault in faults):
        raise ValueError("native message replay selector requires two SHA-256 keys")
    stable = [({field: fault[field] for field in
                ("siteId", "exceptionClass", *MESSAGE_FIELDS)}
               if all(SHA256_HEX.fullmatch(fault.get(field, ""))
                      for field in MESSAGE_FIELDS)
               else {field: fault[field] for field in SELECTOR_FIELDS})
              for fault in faults]
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    if anchor_address is None:
        # Preserve every existing checkpoint and exact plan key byte-for-byte.
        return hashlib.sha256(encoded).hexdigest()
    if not isinstance(anchor_address, str) or not anchor_address:
        raise ValueError("anchored plan requires an exact occurrence address")
    return hashlib.sha256(b"MALLORY_ANCHORED_PLAN_V1\0" +
                          anchor_address.encode() + b"\0" + encoded).hexdigest()


def _prefer_unique_message_keys(
        doors: list[dict[str, Any]], rows: list[dict[str, Any]]
        ) -> list[dict[str, Any]]:
    """Rebind only a unique seed message; original exact selectors remain fallback."""
    def key(row: dict[str, Any]) -> tuple[str, ...] | None:
        if not all(SHA256_HEX.fullmatch(row.get(field, ""))
                   for field in MESSAGE_FIELDS):
            return None
        return tuple(row.get(field, "") for field in
                     ("siteId", "exceptionClass", *MESSAGE_FIELDS))

    counts = Counter(value for row in rows if row.get("kind") == "FAULT_DOOR"
                     if (value := key(row)) is not None)
    by_identity = {(row.get("seq"), row.get("siteId"), row.get("occurrenceId")):
                   row for row in rows if row.get("kind") == "FAULT_DOOR"}
    preferred = []
    for item in doors:
        fault = item["fault"]
        source = by_identity.get((item["seq"], fault["siteId"],
                                  fault["sourceOccurrenceId"]))
        identity = key(source) if source is not None else None
        if identity is not None and counts[identity] == 1:
            item = {**item, "fault": {**fault,
                    **{field: source[field] for field in MESSAGE_FIELDS}}}
        preferred.append(item)
    return preferred


def _enqueue(state: dict[str, Any], doors: list[dict[str, Any]],
             prefix: list[dict[str, Any]], novelty: int,
             depth_feedback: dict[str, Any] | None = None,
             anchor_address: str | None = None) -> None:
    if len(prefix) >= state["budget"]["max_faults_per_trial"]:
        return
    seen = set(state["seen_plan_keys"])
    # One plan per exact observed I/O identity; an occurrence is never
    # fabricated from a static relation or a different trial's task address.
    for door in doors:
        faults = [*prefix, door["fault"]]
        anchor = anchor_address or door.get("anchor_address")
        if state.get("multi_anchor_addresses"):
            if anchor not in state["multi_anchor_addresses"] or (
                    door.get("anchor_address") not in (None, anchor)):
                raise ValueError("fault door changed its exact target anchor")
        elif anchor is not None:
            raise ValueError("legacy queue cannot receive an anchored fault")
        key = _plan_key(faults, anchor)
        if key in seen:
            continue
        seen.add(key)
        item = {"faults": faults, "key": key,
                "tier": door["tier"], "novelty": novelty,
                "enqueued_at": state["completed_fault_trials"],
                "attempt": 0}
        if anchor is not None:
            item["anchor_address"] = anchor
        if state.get("scheduler_version", 1) >= 5:
            item["target_phase"] = door.get("target_phase", "unknown")
        if state.get("scheduler_version", 1) >= 6:
            item["selected_target_actor"] = door.get("selected_target_actor")
            item["target_order_distance"] = door.get("target_order_distance")
        if state.get("scheduler_version", 1) >= 8:
            item["peer_relation"] = door.get("peer_relation", "unknown")
        if state.get("scheduler_version", 1) >= 10 and prefix:
            item["depth_feedback"] = dict(depth_feedback or {})
        state["queue"].append(item)
    state["seen_plan_keys"] = sorted(seen)


def _fault_id(fault: dict[str, Any]) -> str:
    """CrashFuzz-style I/O identity, independent of actor and occurrence."""
    return json.dumps([fault["siteId"], fault["exceptionClass"]],
                      separators=(",", ":"), ensure_ascii=False)


def _pick_v1(state: dict[str, Any]) -> dict[str, Any]:
    """Frozen selection rule for checkpoints created before version 2."""
    queue = state["queue"]
    if not queue:
        raise ValueError("empty native fault queue")
    completed = state["completed_fault_trials"]
    # A sparse slot preserves exploration outside the observed target closure.
    outside = [item for item in queue if item["tier"] == "outside_closure"]
    candidates = outside if outside and completed % 8 == 7 else queue
    selected = max(candidates, key=lambda item: (
        {"observed_closure": 100, "pre_target_actor": 60,
         "outside_closure": 15}.get(item["tier"], 15) +
        item["novelty"] + 3 * len(item["faults"]) +
        min(20, completed - item["enqueued_at"]) -
        25 * item.get("attempt", 0), item["key"]))
    queue.remove(selected)
    return selected


def _pick(state: dict[str, Any]) -> dict[str, Any]:
    """Select diverse I/O sites, with explicit depth and waiting slots."""
    # Retry an exact, previously selected plan after an infrastructure
    # failure. The caller checkpoints the chosen active plan before running
    # its JUnit, so a crash cannot silently skip this replay.
    required = state.get("required_replay_plan_keys")
    if required is not None:
        if (not isinstance(required, list) or
                any(not isinstance(key, str) or not key for key in required) or
                len(required) != len(set(required))):
            raise ValueError("invalid required replay plan keys")
        if required:
            queue = state["queue"]
            matches = [item for item in queue if item["key"] == required[0]]
            if len(matches) != 1:
                raise ValueError("required replay plan is missing from queue")
            selected = matches[0]
            queue.remove(selected)
            required.pop(0)
            return selected
    version = state.get("scheduler_version", 1)
    if version == 1:
        return _pick_v1(state)
    if version not in (2, 3, 4, 5, 6, 7, 8, 9, SCHEDULER_VERSION):
        raise ValueError(f"unsupported native scheduler version: {version}")
    queue = state["queue"]
    if not queue:
        raise ValueError("empty native fault queue")
    completed = state["completed_fault_trials"]
    selection_queue = queue
    addresses = state.get("multi_anchor_addresses", [])
    if addresses:
        # One exact target activation per trial. The rotating quota applies
        # before the old tier/depth rules and cannot rewrite a queued plan.
        for offset in range(len(addresses)):
            desired = addresses[(completed + offset) % len(addresses)]
            matching = [item for item in queue if
                        item.get("anchor_address") == desired]
            if matching:
                selection_queue = matching
                break
        else:
            raise ValueError("anchored queue has no valid target identity")
    outside = [item for item in selection_queue if
               item["tier"] == "outside_closure"]
    inside = [item for item in selection_queue if
              item["tier"] != "outside_closure"]
    # Keep one of eight slots for observed doors outside the target closure.
    outside_slot = bool(outside) and completed % 8 == 7
    candidates = outside if outside_slot else inside or outside
    deep_fair_slot = False
    if version >= 10 and not outside_slot and completed % 16 == 11:
        # The v6 depth>=3 slot still sorts fault ID before depth. Reserve a
        # separate slot for depth 4..6 descendants of a strictly injected
        # trial that reached the target after its final fault and supplied
        # target-directed graph, closure, temporal, or peer feedback. This
        # does not admit any new fault door or alter the target oracle.
        max_depth = min(6, state["budget"]["max_faults_per_trial"])
        deep = [item for item in candidates if
                4 <= len(item["faults"]) <= max_depth and
                isinstance(item.get("depth_feedback"), dict) and
                item["depth_feedback"].get("strict_post_fault_target") is True and
                isinstance(item["depth_feedback"].get("score"), int) and
                not isinstance(item["depth_feedback"]["score"], bool) and
                item["depth_feedback"]["score"] >= 2]
        if deep:
            desired = 4 + (completed // 16) % 3
            depths = {len(item["faults"]) for item in deep}
            chosen_depth = (desired if desired in depths else
                            max((depth for depth in depths if depth < desired),
                                default=min(depths)))
            candidates = [item for item in deep if
                          len(item["faults"]) == chosen_depth]
            deep_fair_slot = True
    repeat_phase_slot = False
    if version >= 9 and not outside_slot and completed % 16 == 12:
        # A late occurrence of an already successful I/O site may observe a
        # different recovery state. Give such exact, observed-closure doors a
        # bounded slot; leave every other selection and old checkpoint rule
        # unchanged. The selector still includes the actor and ordinal.
        repeated = [item for item in candidates if
                    item["tier"] == "observed_closure" and
                    item.get("target_phase") == "after_selected_target" and
                    isinstance(item["faults"][-1].get("ordinal"), int) and
                    not isinstance(item["faults"][-1]["ordinal"], bool) and
                    item["faults"][-1]["ordinal"] > 1 and
                    state["fault_id_successes"].get(_fault_id(
                        item["faults"][-1]), 0) > 0]
        if repeated:
            candidates, repeat_phase_slot = repeated, True
    peer_slot = False
    if version >= 8 and not outside_slot and completed % 8 == 4:
        # A bounded slot gives tool-selected producer RPC doors to the
        # target's observed peer a chance before a large closure queue uses
        # the whole budget. Peer identity is a hint, never causal closure.
        matching_peer = [item for item in candidates if item.get(
            "peer_relation") == "same_peer_before_target"]
        if matching_peer:
            static_peer = [item for item in matching_peer if item["tier"] ==
                           "static_producer_frontier"]
            candidates, peer_slot = static_peer or matching_peer, True
    if version >= 5 and not outside_slot and completed % 8 == 5:
        # Preserve a bounded recovery slot even when the late plan's fault
        # depth differs from the usual depth preference.
        later = [item for item in candidates if item.get(
            "target_phase") == "after_selected_target"]
        if later:
            candidates = later
    if version >= 6 and not outside_slot and completed % 16 == 10:
        # Recovery may need a third fault. Spend a bounded slot on plans
        # with at least three faults instead of waiting for depth-two plans
        # to exhaust the queue.
        deep = [item for item in candidates if len(item["faults"]) >= 3]
        if deep:
            candidates = deep
    elif version >= 4 and not outside_slot and not deep_fair_slot:
        # A target-reaching seed can reveal hundreds of descendants. If all
        # descendants inherit its novelty, the old score selects deep plans
        # repeatedly even when their second actor often runs before the
        # first fault on the next JVM. Reserve one slot in four for depth;
        # use the other slots to explore fresh one-fault identities. The
        # outside-closure slot remains independent of this depth cadence.
        preferred_depth = 2 if completed % 4 == 2 else 1
        same_depth = [item for item in candidates if
                      (len(item["faults"]) > 1) == (preferred_depth > 1)]
        if same_depth:
            candidates = same_depth
    if version >= 5 and not outside_slot and not repeat_phase_slot and completed % 8 != 5:
        # Row order is an observation, not a cross-actor happens-before
        # proof. Favor doors observed before the selected target instance's
        # final check, while reserving one slot in eight for later recovery.
        timely = [item for item in candidates if item.get(
            "target_phase") != "after_selected_target"]
        if timely:
            candidates = timely
    if version >= 6 and not outside_slot and not peer_slot:
        # Actor affinity is a scheduling hint, not closure membership. Keep
        # cross-actor plans in the queue and give them a recurring slot.
        actor_choice = (completed % 4 in (0, 1))
        if completed % 4 == 3:
            actor_choice = False
        matching = [item for item in candidates if item.get(
            "selected_target_actor") is actor_choice]
        if matching:
            candidates = matching

    def attempts(item: dict[str, Any]) -> int:
        return state["fault_id_attempts"].get(_fault_id(item["faults"][-1]), 0)

    def score(item: dict[str, Any]) -> tuple[Any, ...]:
        fault_id = _fault_id(item["faults"][-1])
        if version >= 6:
            distance = item.get("target_order_distance")
            # Most slots stay near the selected check. The bounded repeat
            # slot spreads to later observed positions.
            proximity = ((distance if repeat_phase_slot else -distance)
                         if isinstance(distance, int) and
                         not isinstance(distance, bool) and distance >= 0
                         else -10**9)
            ordinal = item["faults"][-1].get("ordinal")
            # An early occurrence is more likely to recur in a fresh JVM.
            # The site may be observed near the target only on a later
            # occurrence whose count varies with cluster startup timing.
            recurrence = (-ordinal if isinstance(ordinal, int) and
                          not isinstance(ordinal, bool) and ordinal > 0
                          else -10**9)
            return (*((item["depth_feedback"]["score"],)
                      if deep_fair_slot else ()),
                    -attempts(item),
                    -state["fault_id_successes"].get(fault_id, 0),
                    {"observed_closure": 4, "static_producer_frontier": 3,
                     "pre_target_actor": 2,
                     "outside_closure": 1}.get(item["tier"], 1),
                    *(({"same_peer_before_target": 2,
                        "same_peer_after_target": 1}.get(
                            item.get("peer_relation"), 0),)
                      if version >= 8 else ()),
                    *((recurrence,) if version >= 7 else ()),
                    proximity, item["novelty"], len(item["faults"]),
                    completed - item["enqueued_at"],
                    -item.get("attempt", 0), item["key"])
        return (-attempts(item),
                -state["fault_id_successes"].get(fault_id, 0),
                {"observed_closure": 4, "static_producer_frontier": 3,
                 "pre_target_actor": 2,
                 "outside_closure": 1}.get(item["tier"], 1),
                item["novelty"], len(item["faults"]),
                completed - item["enqueued_at"],
                -item.get("attempt", 0), item["key"])

    if inside and completed % 8 == 6:
        # A bounded waiting slot prevents older exact plans from starving.
        selected = min(candidates, key=lambda item: (
            item["enqueued_at"], attempts(item), item["key"]))
    else:
        if version < 4 and inside and completed % 4 == 3:
            # Preserve multi-fault exploration even with many unseen doors.
            deeper = [item for item in candidates if len(item["faults"]) > 1]
            if deeper:
                candidates = deeper
        selected = max(candidates, key=score)
    queue.remove(selected)
    return selected


def _novelty(state: dict[str, Any], feedback: dict[str, Any]) -> int:
    score = 0
    region_state = "newNodeFamilies" in feedback
    for field, seen_field, weight in (
            ("newClosureNodeFamilies", "seen_node_families", 2),
            ("newObservedClosureEdgeFamilies", "seen_edge_families", 4),
            ("newClosureBranchOutcomeIds", "seen_branch_outcomes", 1)):
        if region_state:
            field = {"newClosureNodeFamilies": "newNodeFamilies",
                     "newObservedClosureEdgeFamilies": "newClosureEdgeFamilies",
                     "newClosureBranchOutcomeIds": "newBranchOutcomeIds"}[field]
        values = feedback.get(field)
        if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values):
            raise ValueError(f"native delta lacks exact {field}")
        seen = set(state[seen_field])
        new = set(values) - seen
        state[seen_field] = sorted(seen | set(values))
        score += weight * len(new)
    if region_state:
        # A ROLE sender is an observed causal context outside the static
        # Finalizer region plan. Reward a new exact handoff into a selected
        # region, but keep it in its own corpus and below a region-region
        # closure edge's weight. It never admits a fault to the closure.
        boundaries = feedback.get("newContextBoundaryEdgeFamilies", [])
        if not isinstance(boundaries, list) or not all(
                isinstance(value, str) and value for value in boundaries):
            raise ValueError("native delta has invalid context boundary edges")
        seen = set(state.setdefault("seen_context_boundary_families", []))
        new = set(boundaries) - seen
        state["seen_context_boundary_families"] = sorted(seen | set(boundaries))
        score += 2 * len(new)
        # An exact ZooKeeper version read is a data dependency, separate
        # from an activation/watch edge. Its novelty guides the next trial,
        # while fault eligibility remains the original Finalizer plan.
        reads = feedback.get("newValueReadFromEdgeFamilies", [])
        if not isinstance(reads, list) or not all(
                isinstance(value, str) and value for value in reads):
            raise ValueError("native delta has invalid value read-from edges")
        seen = set(state.setdefault("seen_value_read_from_families", []))
        new = set(reads) - seen
        state["seen_value_read_from_families"] = sorted(seen | set(reads))
        score += 2 * len(new)
    return min(60, score)


def _depth_feedback(active: dict[str, Any], result: dict[str, Any],
                    novelty: int) -> dict[str, Any]:
    """Bounded depth priority from an actually applied, target-reaching seed.

    Native receipt phase and peer are scheduling hints. A graph delta or
    observed closure membership supplies a stronger signal. Neither this
    score nor the slot changes graph membership or the bug verdict.
    """
    retained = (result.get("runner_mode") == "region_state" and
                result.get("strict_injection") is True and
                result.get("native_target_retained") is True and
                result.get("post_fault_target_check_observed") is True)
    graph = novelty > 0
    closure = result.get("fault_in_target_closure") is True
    temporal = result.get("target_temporal_admitted") is True
    phase = active.get("target_phase") == "before_selected_target"
    peer = active.get("peer_relation") == "same_peer_before_target"
    score = (2 * int(graph) + 2 * int(closure) + 2 * int(temporal) +
             int(phase) + int(peer)) if retained else 0
    return {"strict_post_fault_target": retained,
            "graph_delta": graph, "fault_in_closure": closure,
            "target_temporal_admitted": temporal,
            "observed_pre_target_phase": phase,
            "same_peer_before_target": peer,
            "score": score}


def _region_doors(rows: list[dict[str, Any]], summary: dict[str, Any],
                  after_fault: dict[str, Any] | None = None,
                  static_may_rpc_sites: frozenset[str] = frozenset()
                  ) -> list[dict[str, Any]]:
    """Mutate doors admitted by the original target demand closure."""
    if summary.get("closureMembershipAuthority") != (
            "original_runtime_selected_region_finalizer"):
        raise ValueError("REGION_STATE summary lacks original closure authority")
    closure_ids = set(summary["closureOccurrenceIds"])
    after_index = None
    if after_fault is not None:
        after_index = next((index for index, row in enumerate(rows)
                            if row is after_fault), None)
        if after_index is None:
            raise ValueError("last applied fault is absent from the ordered log")
    selected = summary.get("targetEvidence", {})
    selected_ids = selected.get("targetCheckOccurrenceIds", [])
    selected_check_indices = [index for index, row in enumerate(rows) if
                              row.get("kind") == "TARGET_CHECK" and
                              row.get("siteId") == summary["targetSiteId"] and
                              row.get("occurrenceId") in selected_ids and
                              row.get("node") == selected.get("physicalActor") and
                              row.get("actorEpochOrdinal") == selected.get(
                                  "actorEpochOrdinal")]
    # A repeated check may disappear after a fault, even if the original
    # fault-free run observed it later. Use the first selected check as the
    # pre-target boundary so a door between checks is not promoted as a
    # prospective fault before the target.
    first_selected_check = (min(selected_check_indices)
                            if selected_check_indices else None)
    actor_checks: dict[tuple[str, int], int] = {}
    for row in rows:
        if (row["kind"] != "TARGET_CHECK" or
                row.get("siteId") != summary["targetSiteId"] or
                not isinstance(row.get("occurrenceId"), str)):
            continue
        actor = (row["node"], row["actorEpochOrdinal"])
        actor_checks[actor] = min(actor_checks.get(actor, row["seq"]), row["seq"])
    found = []
    for index, row in enumerate(rows):
        if row["kind"] != "FAULT_DOOR":
            continue
        # Sidecar appends are serialized. A second fault can only be added at
        # a door observed after the last applied fault in that same run.
        # Per-actor seq values cannot order two different actors.
        if after_index is not None and index <= after_index:
            continue
        if (after_fault is not None and
                (row.get("node"), row.get("actorEpochOrdinal")) ==
                (after_fault.get("node"), after_fault.get("actorEpochOrdinal"))
                and row["seq"] <= after_fault["seq"]):
            continue
        try:
            _fault_identity(row, applied=True)
        except ValueError:
            continue
        fault = {field: row[field] for field in SELECTOR_FIELDS}
        fault["sourceOccurrenceId"] = row["occurrenceId"]
        actor = (row["node"], row["actorEpochOrdinal"])
        direct = row["occurrenceId"] in closure_ids
        before_actor_check = row["seq"] < actor_checks.get(actor, -1)
        target_phase = ("unknown" if first_selected_check is None else
                        "before_selected_target" if index < first_selected_check else
                        "after_selected_target")
        selected_actor = (selected.get("physicalActor"),
                          selected.get("actorEpochOrdinal"))
        actor_affinity = (actor == selected_actor if
                          selected_actor[0] is not None and
                          selected_actor[1] is not None else None)
        target_distance = (abs(first_selected_check - index) if
                           first_selected_check is not None else None)
        found.append({"fault": fault, "seq": row["seq"],
                      "target_phase": target_phase,
                      "selected_target_actor": actor_affinity,
                      "target_order_distance": target_distance,
                      "tier": "observed_closure" if direct else
                              "static_producer_frontier" if (
                                  row["siteId"] in static_may_rpc_sites and
                                  target_phase == "before_selected_target") else
                              "pre_target_actor" if before_actor_check else
                              "outside_closure"})
    return _prefer_unique_message_keys(found, rows)


def _post_fault_target_checks(rows: list[dict[str, Any]],
                              summary: dict[str, Any],
                              applied: dict[str, Any] | None
                              ) -> dict[str, Any]:
    """Order selected checks with the native hook's verified receipt clock.

    NativeFaultHooks emits one gapless sequence under a JVM-wide lock. Only
    that verified clock can order two logical actors; otherwise use an actor's
    own sequence and leave cross-actor checks unknown. Temporal order still
    does not prove that one actor's fault caused another actor's check.
    """
    selected = summary.get("targetEvidence", {})
    selected_ids = set(selected.get("targetCheckOccurrenceIds", []))
    selected_actor = (selected.get("physicalActor"),
                      selected.get("actorEpochOrdinal"))
    applied_index = next((index for index, row in enumerate(rows)
                          if row is applied), None)
    if applied is not None and applied_index is None:
        raise ValueError("last applied fault is absent from the ordered log")
    global_clock = all(row["seq"] == index + 1
                       for index, row in enumerate(rows))
    before = after = unordered = 0
    same_actor_after = 0
    for index, row in enumerate(rows):
        if (row.get("kind") != "TARGET_CHECK" or
                row.get("siteId") != summary.get("targetSiteId") or
                row.get("occurrenceId") not in selected_ids or
                (row.get("node"), row.get("actorEpochOrdinal")) !=
                selected_actor):
            continue
        if applied_index is None:
            unordered += 1
            continue
        same_actor = ((row.get("node"), row.get("actorEpochOrdinal")) ==
                      (applied.get("node"), applied.get("actorEpochOrdinal")))
        if global_clock:
            ordered_before = index < applied_index
            ordered_after = index > applied_index
        elif same_actor:
            ordered_before = row["seq"] < applied["seq"]
            ordered_after = row["seq"] > applied["seq"]
        else:
            ordered_before = ordered_after = False
        if ordered_before:
            before += 1
        elif ordered_after:
            after += 1
            if same_actor and row["seq"] > applied["seq"]:
                same_actor_after += 1
        else:
            unordered += 1
    if after:
        observed = True
    elif unordered or not before:
        observed = None
    else:
        observed = False
    return {"observed": observed,
            "beforeFaultCheckCount": before,
            "afterFaultCheckCount": after,
            "unorderedCheckCount": unordered,
            "sameActorOrderedCheckCount": same_actor_after,
            "orderBasis": ("single_jvm_gapless_receipt_clock" if global_clock
                           else "same_actor_seq_only"),
            "causalOrder": ("same_actor_seq_proven" if same_actor_after else
                            "unproven")}


def _region_throw_evidence(rows: list[dict[str, Any]], target_site: str,
                           target_throw: dict[str, str],
                           applied: dict[str, Any] | None,
                           selected_occurrence_ids: set[str] | None = None
                           ) -> tuple[list[dict[str, Any]], bool, str,
                                      dict[str, Any] | None]:
    """Keep the selected original target's throw distinct from other calls."""
    checks = [row for row in rows if row["kind"] == "TARGET_CHECK" and
              row.get("siteId") == target_site and
              (selected_occurrence_ids is None or
               row.get("occurrenceId") in selected_occurrence_ids)]
    throws = []
    temporal = None
    for row in rows:
        if (row["kind"] != "TARGET_THROW" or
                row.get("siteId") != target_throw["siteId"] or
                row.get("exceptionClass") != target_throw["exceptionClass"] or
                row.get("actualExceptionClass",
                        row.get("exceptionClass")) !=
                target_throw["exceptionClass"] or
                (selected_occurrence_ids is not None and
                 row.get("occurrenceId") not in selected_occurrence_ids)):
            continue
        matching = [check for check in checks if
                    (check.get("occurrenceId"), check.get("node"),
                     check.get("actorEpochOrdinal")) ==
                    (row.get("occurrenceId"), row.get("node"),
                     row.get("actorEpochOrdinal")) and
                    check["seq"] < row["seq"]]
        if not matching:
            continue
        throws.append(row)
        if applied is not None:
            for check in matching:
                if ((applied.get("occurrenceId"), applied.get("node"),
                     applied.get("actorEpochOrdinal")) ==
                    (check.get("occurrenceId"), check.get("node"),
                     check.get("actorEpochOrdinal")) and
                        applied["seq"] < check["seq"]):
                    temporal = {"faultSeq": applied["seq"],
                                "checkSeq": check["seq"],
                                "throwSeq": row["seq"],
                                "targetOccurrenceId": row["occurrenceId"]}
                    break
    if applied is None:
        return throws, False, "no_applied_fault", None
    return (throws, temporal is not None,
            "same_occurrence_before_check" if temporal else
            "cross_occurrence_order_unproved" if throws else
            "no_exact_target_throw", temporal)


def _region_schedule(iteration: Path, trial: Path) -> None:
    """Place the sole original publisher's schedule beside its closed trace.

    The unchanged JUnit runner may open RowRuntime after the trace writer.
    RowRuntime then writes ScheduleLog into its session directory. Copy those
    exact bytes only if this JVM published one unambiguous schedule.
    """
    trace = iteration / "trace"
    destination = trace / "schedule.jsonl"
    if destination.is_file():
        lineage = {
            "source": str(destination), "source_sha256": _sha(destination),
            "destination_sha256": _sha(destination), "copied": False}
        _durable_schedule_copy(trial, destination, lineage)
        _atomic(trial / "schedule-lineage.json", lineage)
        return
    manifest = _load(trace / "streaming_trace_manifest.json")
    if manifest.get("status") != "CLOSED":
        raise ValueError("region-state runtime trace is not closed")
    sources = sorted((iteration / "sessions").glob("*/schedule.jsonl"))
    if len(sources) != 1 or not sources[0].is_file() or sources[0].stat().st_size == 0:
        raise ValueError("region-state trace has no unique original schedule")
    source = sources[0]
    with tempfile.NamedTemporaryFile("wb", dir=trace, prefix=".schedule-",
                                     delete=False) as stream:
        temporary = Path(stream.name)
        with source.open("rb") as original:
            shutil.copyfileobj(original, stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        if _sha(source) != _sha(temporary):
            raise ValueError("original session schedule changed while copying")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    lineage = {
        "source": str(source), "source_sha256": _sha(source),
        "destination_sha256": _sha(destination), "copied": True}
    _durable_schedule_copy(trial, destination, lineage)
    _atomic(trial / "schedule-lineage.json", lineage)


def _durable_schedule_copy(trial: Path, source: Path,
                           lineage: dict[str, Any]) -> None:
    """Keep exact original schedule bytes available to a remote auditor."""
    if not (trial / "local-artifacts.json").is_file():
        return
    copy = trial / "native-schedule.jsonl"
    with tempfile.NamedTemporaryFile("wb", dir=trial, prefix=".schedule-copy-",
                                     delete=False) as stream:
        temporary = Path(stream.name)
        with source.open("rb") as original:
            shutil.copyfileobj(original, stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        if _sha(temporary) != lineage["destination_sha256"]:
            raise ValueError("durable original schedule copy changed")
        os.replace(temporary, copy)
    finally:
        temporary.unlink(missing_ok=True)
    lineage["durable_copy"] = str(copy)
    lineage["durable_copy_sha256"] = _sha(copy)


def _trial_jvm_args(runner: dict[str, Any], workdir: Path) -> list[str]:
    return [arg.replace("{trial_workdir}", str(workdir))
            for arg in runner.get("jvm_args", [])]


def _filesystem_mount(path: Path) -> tuple[Path, str]:
    """Find the Linux mount containing an existing work root."""
    resolved = path.resolve()
    nearest = resolved
    while not nearest.exists():
        nearest = nearest.parent
    best: tuple[int, Path, str] | None = None
    with Path("/proc/self/mountinfo").open(encoding="utf-8") as stream:
        for line in stream:
            before, separator, after = line.partition(" - ")
            if not separator:
                continue
            fields = before.split()
            if len(fields) < 5:
                continue
            mount = Path(re.sub(r"\\([0-7]{3})", lambda match:
                            chr(int(match.group(1), 8)), fields[4]))
            if nearest == mount or mount in nearest.parents:
                depth = len(mount.parts)
                if best is None or depth > best[0]:
                    best = (depth, mount, after.split()[0])
    if best is None:
        raise ValueError(f"cannot identify filesystem for {path}")
    return best[1], best[2]


def _validate_local_work_root(config: dict[str, Any], campaign: Path) -> None:
    configured = config["runner"].get("local_work_root")
    if configured is None:
        return
    root = Path(configured).resolve()
    campaign = campaign.resolve()
    if root == campaign or campaign in root.parents or root in campaign.parents:
        raise ValueError("local JUnit work root must be separate from campaign output")
    if not root.is_dir():
        raise ValueError("runner.local_work_root must already exist as a directory")
    mount, fs_type = _filesystem_mount(root)
    if mount == Path("/") or fs_type.lower().startswith("nfs"):
        raise ValueError("runner.local_work_root must be on a host-local filesystem")


def _validate_local_artifact_root(config: dict[str, Any], campaign: Path) -> None:
    """Only an explicit host-local directory may hold raw trial artifacts."""
    configured = config["runner"].get("local_artifact_root")
    if configured is None:
        return
    root = Path(configured).resolve()
    campaign = campaign.resolve()
    if root == campaign or campaign in root.parents or root in campaign.parents:
        raise ValueError("local artifact root must be separate from campaign output")
    if not root.is_dir():
        raise ValueError("runner.local_artifact_root must already exist as a directory")
    mount, fs_type = _filesystem_mount(root)
    if mount == Path("/") or fs_type.lower().startswith("nfs"):
        raise ValueError("runner.local_artifact_root must be on a host-local filesystem")


def _prepare_trial_artifacts(config: dict[str, Any], trial: Path) -> None:
    """Put only raw trace, graph and logs on local scratch.

    Durable fault receipts, native summary and result remain under `trial`.
    A new local attempt directory is allocated after an interrupted trial is
    moved aside, so recovery never overwrites evidence from the old attempt.
    """
    configured = config["runner"].get("local_artifact_root")
    if configured is None:
        return
    campaign = trial.parent.parent.resolve()
    _validate_local_artifact_root(config, campaign)
    namespace = hashlib.sha256((str(campaign) + "\0" + config["case_id"])
                               .encode("utf-8")).hexdigest()[:24]
    parent = Path(configured).resolve() / namespace / "raw"
    parent.mkdir(parents=True, exist_ok=True)
    local = Path(tempfile.mkdtemp(prefix=f"{trial.name}-attempt-", dir=parent))
    iteration = trial / "iteration-native"
    iteration.mkdir()
    links = {
        "iteration-native/trace": local / "trace",
        "iteration-native/sessions": local / "sessions",
        "original-graph": local / "original-graph",
        "stdout.log": local / "stdout.log",
        "stderr.log": local / "stderr.log",
    }
    if config["runner"].get("local_work_root") is None:
        links["iteration-native/workdir"] = local / "workdir"
    for name, destination in links.items():
        if name.endswith(("trace", "sessions", "original-graph", "workdir")):
            destination.mkdir()
        (trial / name).symlink_to(destination, target_is_directory=
                                  destination.is_dir())
    _atomic(trial / "local-artifacts.json", {
        "schema_version": 1, "status": "allocated",
        "host": os.uname().nodename, "campaign_root": str(campaign),
        "trial": trial.name, "local_attempt_dir": str(local),
        "links": {name: str(destination) for name, destination in links.items()},
    })


def _close_trial_artifacts(trial: Path) -> str | None:
    """Commit a compact, hash-checked receipt before publishing result.json."""
    manifest_file = trial / "local-artifacts.json"
    if not manifest_file.is_file():
        return None
    manifest = _load(manifest_file)
    if manifest.get("status") != "allocated":
        raise ValueError("local trial artifacts are not in allocated state")
    if manifest.get("host") != os.uname().nodename:
        raise ValueError("local trial artifacts belong to another host")
    local = Path(manifest["local_attempt_dir"])
    if not local.is_dir():
        raise ValueError("local trial artifacts disappeared before completion")
    for name, destination in manifest["links"].items():
        link = trial / name
        if not link.is_symlink() or os.readlink(link) != destination:
            raise ValueError(f"local trial artifact link changed: {name}")
    files = sorted(path for path in local.rglob("*")
                   if path.is_file() or path.is_symlink())
    digest = hashlib.sha256()
    selected = {}
    total_bytes = 0
    selected_names = {
        "trace/streaming_trace_manifest.json", "trace/runtime_trace.jsonl",
        "trace/schedule.jsonl", "original-graph/summary.json",
        "stdout.log", "stderr.log",
    }
    for path in files:
        relative = path.relative_to(local).as_posix()
        if path.is_symlink():
            # JUnit data directories may themselves contain symlinks. Commit
            # their link text without following an untrusted external target.
            content_sha = hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
            marker = b"L"
            size = path.lstat().st_size
        else:
            content_sha = _sha(path)
            marker = b"F"
            size = path.stat().st_size
        digest.update(relative.encode("utf-8") + b"\0" +
                      marker + bytes.fromhex(content_sha))
        total_bytes += size
        if relative in selected_names:
            selected[relative] = content_sha
    manifest.update({"status": "closed", "file_count": len(files),
                     "total_bytes": total_bytes,
                     "tree_sha256": digest.hexdigest(),
                     "selected_sha256": selected})
    _atomic(manifest_file, manifest)
    return _sha(manifest_file)


def _junit_workdir(config: dict[str, Any], trial: Path) -> Path:
    """Give each attempt a fresh cwd; leave all receipts in the campaign."""
    configured = config["runner"].get("local_work_root")
    if configured is None:
        workdir = trial / "iteration-native" / "workdir"
        # With local_artifact_root this is already a symlink to the fresh
        # attempt directory. Path.mkdir(exist_ok=True) accepts that directory
        # while retaining the legacy in-campaign directory behavior.
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir
    campaign = trial.parent.parent.resolve()
    _validate_local_work_root(config, campaign)
    namespace = hashlib.sha256((str(campaign) + "\0" + config["case_id"])
                               .encode("utf-8")).hexdigest()[:24]
    parent = Path(configured).resolve() / namespace
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{trial.name}-attempt-", dir=parent))


def _runner_prefix(runner: dict[str, Any], iteration: Path) -> list[str]:
    return [str(iteration / "junit-result.json") if arg == "{trial_result_file}"
            else arg for arg in runner.get("args_before_test", [])]


def _mode_jvm_args(runner: dict[str, Any], weave: dict[str, Any],
                   iteration: Path, junit: dict[str, str]) -> list[str]:
    if runner.get("mode", "concolic") == "region_state":
        return ["-Dcausynth.trace.mode=region-state",
                f"-Dcausynth.trace.test={junit['class']}#{junit['method']}"]
    return [f"-Dcausynth.concolic.task.plan={Path(weave['task_plan']).resolve(strict=True)}",
            f"-Dcausynth.concolic.task.id={weave['task_id']}",
            f"-Dcausynth.concolic.results={iteration / 'vm-result.json'}"]


def _junit_result_marker(path: Path, marker: str) -> dict[str, Any]:
    """Verify one complete original JUnit result, including @Repeat expansion."""
    pattern = re.compile(rf"^{re.escape(marker)} run=(\d+) failures=(\d+) "
                         r"ignored=(\d+) expected=(\d+)$")
    matches = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith(marker):
                matches.append(pattern.fullmatch(line.rstrip("\r\n")))
    if len(matches) != 1 or matches[0] is None:
        return {"valid": False, "reason": "missing_ambiguous_or_malformed_marker"}
    run, failures, ignored, expected = map(int, matches[0].groups())
    return {"valid": run > 0 and run == expected and failures == 0 and ignored == 0,
            "run": run, "failures": failures, "ignored": ignored,
            "expected": expected}


def _execute_junit(config: dict[str, Any], admitted: dict[str, Any],
                   trial: Path, faults: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the same unchanged JUnit method in a fresh Zero VM."""
    iteration = trial / "iteration-native"
    workdir = _junit_workdir(config, trial)
    _atomic(iteration / "fault-plan.json", {"faults": faults})
    weave = admitted["weave_config"]
    runner = config["runner"]
    # JUnit cluster data directories must be fresh for every replay. The
    # caller can opt into this path in JVM properties without changing tests.
    # Java 8 Files.createDirectories rejects a symlink even when it points to
    # an existing directory. The local-artifact layout retains audited links
    # in the durable trial, but JVM output paths must name physical directories.
    jvm_args = _trial_jvm_args(runner, workdir.resolve(strict=True))
    cp = os.pathsep.join((
        str(Path(weave["output_classes"]).resolve(strict=True)),
        *(str(Path(item).resolve(strict=True)) for item in runner["classpath"]),
        str(JAR.resolve(strict=True)),
        DEPENDENCIES.read_text(encoding="utf-8").strip()))
    argv = [str(Path(runner["zero_vm_java"]).resolve(strict=True)),
            *_mode_jvm_args(runner, weave, iteration, config["junit"]),
            *jvm_args, "-cp", cp, runner["main_class"],
            *_runner_prefix(runner, iteration),
            config["junit"]["class"], config["junit"]["method"]]
    env = os.environ.copy()
    trace_dir = iteration / "trace"
    trace_dir.mkdir(parents=True, exist_ok=True)
    env.update({"CAUSYNTH_STATIC_SCOPE_MAP": str(Path(config["recording"][
        "static_scope_map"]).resolve(strict=True)),
                "CAUSYNTH_TRACE_OUTPUT_DIR": str(trace_dir.resolve(strict=True)),
                "MALLORY_NATIVE_FAULT_PLAN": str(iteration / "fault-plan.json"),
                "MALLORY_NATIVE_FAULT_EVENTS": str(iteration / "fault-events.jsonl")})
    if runner.get("mode", "concolic") == "concolic":
        sessions = iteration / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        env["CAUSYNTH_CONCOLIC_SESSIONS"] = str(sessions.resolve(strict=True))
    else:
        # RowRuntime's explicit concolic publisher steals ScheduleLog's sink
        # from the original REGION_STATE trace. Its schedule must stay beside
        # runtime_trace.jsonl for original Resolver/Recorder validation.
        env.pop("CAUSYNTH_CONCOLIC_SESSIONS", None)
    started = time.monotonic()
    with (trial / "stdout.log").open("wb") as stdout, (
            trial / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=workdir, env=env, stdout=stdout,
                                   stderr=stderr, start_new_session=True)
        process_receipt = {"pid": process.pid,
                           "start_ticks": _start_ticks(process.pid),
                           "argv": argv, "started_at": time.time(),
                           "host": os.uname().nodename}
        if (runner.get("local_work_root") is not None or
                runner.get("local_artifact_root") is not None):
            process_receipt["junit_workdir"] = str(workdir.resolve())
        _atomic(trial / "process.json", process_receipt)
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
    execution = {"return_code": code, "timed_out": timed_out,
                 "elapsed_seconds": round(time.monotonic() - started, 3)}
    if runner.get("result_marker"):
        execution["junit_result_marker"] = _junit_result_marker(
            trial / "stdout.log", runner["result_marker"])
    return execution


def _healthy_anchor_valid(row: Any) -> bool:
    if not isinstance(row, dict) or not isinstance(row.get("summary"), dict):
        return False
    summary = row["summary"]
    evidence = summary.get("targetEvidence")
    return (row.get("targetReached") is True and
            summary.get("targetReached") is True and
            summary.get("closureMembershipAuthority") ==
            "original_runtime_selected_region_finalizer" and
            isinstance(evidence, dict) and
            evidence.get("selectedOccurrenceAddress") == row.get(
                "occurrenceAddress") and
            isinstance(evidence.get("targetCheckOccurrenceIds"), list) and
            bool(evidence["targetCheckOccurrenceIds"]))


def _complete_multi_healthy(config: dict[str, Any], trial: Path,
                            result: dict[str, Any], events: list[dict[str, Any]],
                            bundle: dict[str, Any]) -> dict[str, Any]:
    """Seed one original GraphChecker closure and queue per exact activation."""
    _atomic(trial / "native-summary.json", bundle)
    result["native_session_sha256"] = _sha(trial / "native-summary.json")
    anchors = bundle.get("anchors", [])
    count = config["recording"]["multi_target_max_anchors"]
    if (bundle.get("status") != "multi_target_recorded" or
            not isinstance(anchors, list) or len(anchors) != count or
            bundle.get("retryExactOccurrences") or
            any(not _healthy_anchor_valid(row) for row in anchors)):
        result["status"] = "blocked_healthy_target"
        return result
    if result.get("raw_exact_target_throw_count") != 0:
        result["status"] = "blocked_healthy_target_exception"
        return result
    result["native_target_retained"] = True
    result["multi_anchor_addresses"] = [row["occurrenceAddress"]
                                         for row in anchors]
    result["native_target_occurrence_ids"] = sorted({identifier
        for row in anchors for identifier in row["summary"].get(
            "targetEvidence", {}).get("targetCheckOccurrenceIds", [])})
    recording = config["recording"]
    static_rpc_sites = (rpc_producer_sites(
        str(Path(recording["static_may_scope_map"]).resolve(strict=True)),
        recording["static_may_scope_map_sha256"], config["target_site"])
        if "static_may_scope_map" in recording else frozenset())
    doors = []
    for row in anchors:
        address = row["occurrenceAddress"]
        selected = _region_doors(events, row["summary"], None,
                                 static_rpc_sites)
        doors.extend({**door, "anchor_address": address} for door in selected
                     if door["tier"] == "observed_closure")
    result["eligible_doors"] = doors
    result["status"] = "healthy_seed"
    return result


def _run_region_trial(config: dict[str, Any], admitted: dict[str, Any],
                      trial: Path, faults: list[dict[str, Any]],
                      healthy: dict[str, Any] | None,
                      result: dict[str, Any], events: list[dict[str, Any]],
                      strict: bool, scheduler_version: int = SCHEDULER_VERSION,
                      anchor_address: str | None = None
                      ) -> dict[str, Any]:
    """Extract each run's graph from its own original CLOSED trace."""
    if not faults and not result["junit_passed"]:
        result["status"] = "blocked_healthy_junit"
        return result
    if faults and not strict:
        result["status"] = "unmatched"
        return result
    iteration = trial / "iteration-native"
    recording = config["recording"]
    try:
        _region_schedule(iteration, trial)
        loop_args = [arg.split("=", 1)[1] for arg in recording.get(
            "recorder_jvm_args", []) if arg.startswith(
                "-Dcausynth.loop.default.bound=")]
        loop_bound = int(loop_args[-1]) if loop_args else 3
        graph_options = {
            "test_id": recording["test_id"],
            "target_site": config["target_site"],
            "fault_events": iteration / "fault-events.jsonl",
            "static_scope_map": Path(recording["static_scope_map"]),
            "candidate_graph": Path(recording["candidate_graph"]),
            "region_skeletons": Path(recording["region_skeletons"]),
            "engine_jar": _analysis_engine_jar(config),
            "java": Path(admitted["weave_config"]["java"]),
            "loop_bound": loop_bound,
            "timeout_seconds": recording.get("graph_analysis_timeout_seconds", 300),
            "heap_mb": recording.get("graph_analysis_heap_mb", 3072),
            "target_throw": config["target_throw"],
        }
        multi_count = recording.get("multi_target_max_anchors")
        target_receipt = trial / "original-graph" / "target-occurrence.json"
        if multi_count is None:
            summary = record_region_state(
                iteration / "trace", trial / "original-graph",
                target_occurrence=recording.get("target_occurrence"),
                **graph_options)
        elif not faults:
            bundle = record_multiple_region_states(
                iteration / "trace", trial / "original-graph",
                max_anchors=multi_count, **graph_options)
            return _complete_multi_healthy(
                config, trial, result, events, bundle)
        else:
            if (healthy is None or healthy.get("schemaVersion") != 1 or
                    not isinstance(healthy.get("anchors"), list)):
                raise ValueError("missing pinned multi-target healthy graph")
            matching = [row for row in healthy["anchors"] if
                        row.get("occurrenceAddress") == anchor_address]
            if len(matching) != 1:
                raise ValueError("fault plan has no unique healthy target anchor")
            replay = record_pinned_region_states(
                iteration / "trace", trial / "original-graph",
                healthy_bundle={"schemaVersion": 1, "anchors": matching},
                **graph_options)
            result["anchor_replay_status"] = replay["status"]
            if replay["status"] == "retry_exact_missing":
                result["status"] = ("needs_causal_review" if result.get(
                    "raw_target_throw_differential_candidate") else "unmatched")
                result["analysis_error"] = "healthy exact target activation absent"
                result["native_target_retained"] = False
                result["eligible_doors"] = []
                _atomic(trial / "native-summary.json", replay)
                result["native_session_sha256"] = _sha(
                    trial / "native-summary.json")
                return result
            summary = replay["anchors"][0]["summary"]
            healthy = matching[0]["summary"]
            target_receipt = (trial / "original-graph" / "anchor-00" /
                              "target-occurrence.json")
            result["anchor_address"] = anchor_address
    except (ValueError, FileNotFoundError, subprocess.SubprocessError,
            OSError, RuntimeError) as failure:
        result["status"] = ("blocked_healthy_native_session" if not faults
                            else "invalid_native_session")
        result["analysis_error"] = str(failure)
        return result
    _atomic(trial / "native-summary.json", summary)
    result["native_session_sha256"] = _sha(trial / "native-summary.json")
    result["native_target_occurrence_ids"] = summary.get(
        "targetEvidence", {}).get("targetCheckOccurrenceIds", [])
    if not summary.get("targetReached"):
        result["status"] = "blocked_healthy_target" if not faults else "target_lost"
        return result
    result["native_target_retained"] = True
    if healthy is not None and summary.get("status") != "target_throw_unplanned":
        feedback = delta_region_state(healthy, summary)
        result["native_delta"] = feedback
        if not feedback["targetRetained"]:
            result["native_target_retained"] = False
            result["status"] = "target_lost"
            return result
    elif faults:
        result["native_delta"] = {"newNodeFamilies": [],
                                  "newClosureEdgeFamilies": [],
                                  "newBranchOutcomeIds": []}
    applied = [row for row in events if row["kind"] == "FAULT_APPLIED"]
    last = applied[-1] if applied else None
    if summary.get("status") == "target_throw_unplanned":
        # The exact throw is still evidence, but no original plan was emitted.
        closure_ids: set[str] = set()
    else:
        if summary.get("closureMembershipAuthority") != (
                "original_runtime_selected_region_finalizer"):
            raise ValueError("REGION_STATE summary lacks original closure authority")
        closure_ids = set(summary["closureOccurrenceIds"])
    if last is not None:
        result["fault_in_target_closure"] = last["occurrenceId"] in closure_ids
        post_fault = _post_fault_target_checks(events, summary, last)
        result["post_fault_target_check_observed"] = post_fault["observed"]
        result["post_fault_target_check_evidence"] = post_fault
    static_rpc_sites = (rpc_producer_sites(
        str(Path(recording["static_may_scope_map"]).resolve(strict=True)),
        recording["static_may_scope_map_sha256"], config["target_site"])
        if "static_may_scope_map" in recording else frozenset())
    result["eligible_doors"] = ([] if summary.get("status") ==
                                "target_throw_unplanned" else
                                _region_doors(events, summary, last,
                                              static_rpc_sites))
    if anchor_address is not None:
        result["eligible_doors"] = [door for door in result[
            "eligible_doors"] if door["tier"] == "observed_closure"]
        for door in result["eligible_doors"]:
            door["anchor_address"] = anchor_address
    if scheduler_version >= 8 and result["eligible_doors"] and static_rpc_sites:
        result["eligible_doors"], peer_receipt = rank_region_doors_by_peer(
            result["eligible_doors"],
            iteration / "trace" / "runtime_trace.jsonl",
            target_receipt,
            static_rpc_sites, events)
        _atomic(trial / "peer-ranking-receipt.json", peer_receipt)
        result["peer_ranking_receipt_sha256"] = _sha(
            trial / "peer-ranking-receipt.json")
    selected_ids = summary.get("targetEvidence", {}).get(
        "targetCheckOccurrenceIds")
    if (not isinstance(selected_ids, list) or not selected_ids or
            any(not isinstance(identifier, str) or not identifier
                for identifier in selected_ids)):
        result["status"] = ("blocked_healthy_native_session" if not faults else
                            "invalid_native_session")
        result["analysis_error"] = (
            "original selected target has no exact check occurrences")
        return result
    throws, admitted_temporal, reason, evidence = _region_throw_evidence(
        events, config["target_site"], config["target_throw"], last,
        set(selected_ids))
    result["target_exception_triggered"] = bool(throws)
    result["target_throw_rows"] = throws
    result["target_temporal_admitted"] = admitted_temporal
    result["target_temporal_reason"] = reason
    result["target_temporal_evidence"] = evidence
    result["status"] = ("blocked_healthy_target_exception" if not faults and
                        throws else "healthy_seed" if not faults else
                        "candidate" if throws and admitted_temporal else
                        "needs_causal_review" if throws else "checked")
    if (faults and anchor_address is not None and
            result.get("raw_target_throw_differential_candidate") and
            result["status"] == "checked"):
        result["status"] = "needs_causal_review"
    return result


def _run_trial(config: dict[str, Any], admitted: dict[str, Any],
               trial: Path, faults: list[dict[str, Any]],
               healthy: dict[str, Any] | None,
               healthy_raw_throw_count: int | None = None,
               scheduler_version: int = SCHEDULER_VERSION,
               anchor_address: str | None = None) -> dict[str, Any]:
    _verify_pins(config, admitted)
    trial.mkdir(parents=True, exist_ok=False)
    _prepare_trial_artifacts(config, trial)
    trial_started = time.monotonic()
    execution = _execute_junit(config, admitted, trial, faults)
    iteration = trial / "iteration-native"
    result: dict[str, Any] = {"schema_version": SCHEMA, "case_id": config["case_id"],
                              "faults": faults,
                              "runner_mode": config["runner"].get("mode", "concolic"),
                              **execution}
    if anchor_address is not None:
        result["anchor_address"] = anchor_address
    result["fault_events_sha256"] = (_sha(iteration / "fault-events.jsonl")
                                      if (iteration / "fault-events.jsonl").is_file()
                                      else None)
    result["strict_injection"] = False
    result["junit_passed"] = (execution["return_code"] == 0 and
                              not execution["timed_out"] and
                              execution.get("junit_result_marker", {"valid": True})["valid"])
    result["target_exception_triggered"] = False
    result["native_target_retained"] = False
    result["fault_in_target_closure"] = False
    result["post_fault_target_check_observed"] = False
    result["post_fault_target_check_evidence"] = None
    result["target_temporal_admitted"] = False
    result["target_temporal_reason"] = "no_applied_fault"
    result["target_temporal_evidence"] = None
    result["eligible_doors"] = []
    result["raw_exact_target_throw_after_applied_prefix"] = False
    result["raw_exact_target_throw_count"] = None
    result["healthy_raw_exact_target_throw_count"] = healthy_raw_throw_count
    result["raw_target_throw_differential_candidate"] = False
    result["raw_target_throw_observation"] = {
        "appliedPrefixCount": 0, "targetThrows": [],
        "lifecycleContext": "not_applicable", "causalAttribution": "unproven"}
    try:
        events = _rows(iteration / "fault-events.jsonl")
        strict, last_fault = _strict_faults(faults, events)
    except ValueError as failure:
        result["status"] = "invalid_fault_receipt"
        result["analysis_error"] = str(failure)
        return _save_trial_result(trial, result, trial_started)
    result["strict_injection"] = bool(faults and strict)
    result["raw_exact_target_throw_count"] = len(_target_throw_observations(
        events, config["target_site"], config["target_throw"]))
    raw = _raw_prefix_target_throws(
        faults, events, config["target_site"], config["target_throw"])
    result["raw_target_throw_observation"] = raw
    result["raw_exact_target_throw_after_applied_prefix"] = bool(
        raw["targetThrows"])
    result["raw_target_throw_differential_candidate"] = bool(
        faults and strict and healthy_raw_throw_count is not None and
        result["raw_exact_target_throw_count"] > healthy_raw_throw_count and
        raw["targetThrows"])
    if config["runner"].get("mode") == "region_state":
        if faults and not strict:
            prefix_size, successors = _unmatched_actor_successors(faults, events)
            result["applied_prefix_count"] = prefix_size
            result["observed_actor_successors"] = successors
        result = _run_region_trial(config, admitted, trial, faults, healthy,
                                   result, events, strict, scheduler_version,
                                   anchor_address)
        return _save_trial_result(trial, result, trial_started)
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
                        applied = [row for row in events if row["kind"] ==
                                   "FAULT_APPLIED"]
                        result["eligible_doors"] = _doors(
                            events, summary, applied[-1] if applied else None)
                        thrown = _exact_throws(events, summary,
                                               config["target_throw"], last_fault)
                        result["target_exception_triggered"] = bool(thrown)
                        result["target_throw_rows"] = thrown
                        if faults:
                            closure = {row["occurrenceId"] for row in summary[
                                "closureMembers"]}
                            result["fault_in_target_closure"] = bool(
                                applied and applied[-1]["occurrenceId"] in closure)
                            admitted, reason, evidence = _temporal_target(
                                events, summary, config["target_site"])
                            result["target_temporal_admitted"] = admitted
                            result["target_temporal_reason"] = reason
                            result["target_temporal_evidence"] = evidence
                        linked_throw = bool(thrown and result[
                            "target_temporal_evidence"] and any(
                                row["occurrenceId"] == result[
                                    "target_temporal_evidence"]["targetOccurrenceId"]
                                and any(
                                    check["kind"] == "TARGET_CHECK" and
                                    check.get("occurrenceId") == row["occurrenceId"] and
                                    check.get("targetAnchorSiteId") == config[
                                        "target_site"] and
                                    check["seq"] == result[
                                        "target_temporal_evidence"]["checkSeq"] and
                                    check.get("node") == row.get("node") and
                                    check.get("actorEpochOrdinal") == row.get(
                                        "actorEpochOrdinal") and
                                    row["seq"] > check["seq"]
                                    for check in events)
                                for row in thrown))
                        if faults and not result["target_temporal_admitted"]:
                            result["status"] = (
                                "needs_causal_review" if thrown or result[
                                    "target_temporal_reason"] in (
                                        "cross_occurrence_order_unproved",
                                        "target_check_not_recorded")
                                else "unrelated_target")
                        elif faults and thrown and not linked_throw:
                            result["status"] = "needs_causal_review"
                        else:
                            result["status"] = ("candidate" if linked_throw else
                                                "healthy_seed" if not faults
                                                else "checked")
        except (ValueError, FileNotFoundError, subprocess.SubprocessError,
                OSError) as failure:
            result["status"] = ("blocked_healthy_native_session" if not faults
                                else "invalid_native_session")
            result["analysis_error"] = str(failure)
    return _save_trial_result(trial, result, trial_started)


def _save_trial_result(trial: Path, result: dict[str, Any],
                       trial_started: float) -> dict[str, Any]:
    junit_seconds = result["elapsed_seconds"]
    local_manifest_sha = _close_trial_artifacts(trial)
    total_seconds = round(time.monotonic() - trial_started, 3)
    result["junit_elapsed_seconds"] = junit_seconds
    result["analysis_elapsed_seconds"] = round(max(0.0, total_seconds - junit_seconds), 3)
    result["elapsed_seconds"] = total_seconds
    if local_manifest_sha is not None:
        result["local_artifacts_manifest_sha256"] = local_manifest_sha
    _atomic(trial / "result.json", result)
    return result


def _verify_peer_ranking_receipt(trial: Path, result: dict[str, Any]) -> None:
    """Peer hints live outside the local raw-trace artifact manifest."""
    expected = result.get("peer_ranking_receipt_sha256")
    if expected is None:
        return
    receipt = trial / "peer-ranking-receipt.json"
    if (not isinstance(expected, str) or not SHA256_HEX.fullmatch(expected)
            or receipt.is_symlink() or not receipt.is_file() or
            _sha(receipt) != expected):
        raise ValueError("completed native trial peer ranking receipt changed")


def _verify_terminal_peer_ranking_receipts(root: Path,
                                           state: dict[str, Any]) -> None:
    """Recheck durable peer receipts when opening or sealing a terminal run."""
    recorded = [state.get("healthy"), *state.get("trials", [])]
    for item in recorded:
        if item is None:
            continue
        relative = item.get("result") if isinstance(item, dict) else None
        if (item is state.get("healthy") and relative is None and
                state.get("scheduler_version", 1) < 8):
            # Legacy terminal snapshots may record only the healthy name.
            continue
        if (not isinstance(relative, str) or
                not re.fullmatch(r"trials/r[0-9]{4,}/result\.json", relative)):
            raise ValueError("terminal native trial result path is invalid")
        result_file = root / relative
        if result_file.is_symlink() or not result_file.is_file():
            raise ValueError("terminal native trial result is missing")
        _verify_peer_ranking_receipt(result_file.parent, _load(result_file))


def _accept(state: dict[str, Any], result: dict[str, Any], name: str) -> None:
    active = state["active"]
    if (active is None or active["name"] != name or
            active["faults"] != result["faults"] or
            active.get("anchor_address") != result.get("anchor_address")):
        raise ValueError("native campaign active trial identity changed")
    state["elapsed_seconds"] = round(state["elapsed_seconds"] +
                                     result["elapsed_seconds"], 3)
    if active["index"] == 0:
        state["healthy"] = {"name": name, "status": result["status"],
                            "result": f"trials/{name}/result.json"}
        if result["status"] != "healthy_seed":
            state["status"] = result["status"]
        else:
            if "multi_target_max_anchors" in state.get("multi_anchor_config", {}):
                addresses = result.get("multi_anchor_addresses")
                if (not isinstance(addresses, list) or
                        len(addresses) != state["multi_anchor_config"][
                            "multi_target_max_anchors"] or
                        len(addresses) != len(set(addresses))):
                    raise ValueError("healthy multi-target anchor set changed")
                state["multi_anchor_addresses"] = addresses
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
        if active.get("anchor_address") is not None:
            record["anchor_address"] = active["anchor_address"]
        if "raw_target_throw_differential_candidate" in result:
            record["raw_target_throw_differential_candidate"] = result[
                "raw_target_throw_differential_candidate"]
            record["raw_exact_target_throw_count"] = result.get(
                "raw_exact_target_throw_count")
        if (result.get("runner_mode") == "region_state" and
                "post_fault_target_check_observed" in result):
            record["post_fault_target_check_observed"] = result[
                "post_fault_target_check_observed"]
        state["trials"].append(record)
        if state.get("scheduler_version", 1) >= 5:
            record["target_phase"] = active.get("target_phase", "unknown")
        if state.get("scheduler_version", 1) >= 6:
            record["selected_target_actor"] = active.get("selected_target_actor")
            record["target_order_distance"] = active.get("target_order_distance")
        if state.get("scheduler_version", 1) >= 8:
            record["peer_relation"] = active.get("peer_relation", "unknown")
        if state.get("scheduler_version", 1) >= 2:
            fault_id = _fault_id(active["faults"][-1])
            attempts = state["fault_id_attempts"]
            attempts[fault_id] = attempts.get(fault_id, 0) + 1
            if result["strict_injection"]:
                successes = state["fault_id_successes"]
                successes[fault_id] = successes.get(fault_id, 0) + 1
            record["last_fault_id"] = fault_id
        if (result["status"] == "unmatched" and
                result.get("runner_mode") == "region_state" and
                active.get("attempt", 0) < MAX_UNMATCHED_RETRIES):
            retry = {
                "faults": active["faults"], "key": active["key"],
                "tier": active["tier"], "novelty": active["novelty"],
                "enqueued_at": state["completed_fault_trials"],
                "attempt": active.get("attempt", 0) + 1}
            if active.get("anchor_address") is not None:
                retry["anchor_address"] = active["anchor_address"]
            if state.get("scheduler_version", 1) >= 5:
                retry["target_phase"] = active.get("target_phase", "unknown")
            if state.get("scheduler_version", 1) >= 6:
                retry["selected_target_actor"] = active.get("selected_target_actor")
                retry["target_order_distance"] = active.get("target_order_distance")
            if state.get("scheduler_version", 1) >= 8:
                retry["peer_relation"] = active.get("peer_relation", "unknown")
            if state.get("scheduler_version", 1) >= 10:
                retry["depth_feedback"] = active.get("depth_feedback", {})
            state["queue"].append(retry)
            record["retry_enqueued"] = active.get("attempt", 0) + 1
        if (state.get("scheduler_version", 1) >= 3 and
                result["status"] == "unmatched" and
                result.get("runner_mode") == "region_state" and
                active.get("anchor_address") is None and
                result.get("anchor_replay_status") != "retry_exact_missing"):
            prefix_size = result.get("applied_prefix_count", 0)
            successors = result.get("observed_actor_successors", [])
            if (not isinstance(prefix_size, int) or isinstance(prefix_size, bool)
                    or not 0 <= prefix_size < len(active["faults"]) or
                    not isinstance(successors, list)):
                raise ValueError("invalid unmatched actor successor receipt")
            before = len(state["queue"])
            _enqueue(state, successors, active["faults"][:prefix_size], 0,
                     anchor_address=active.get("anchor_address"))
            record["observed_actor_successors_enqueued"] = (
                len(state["queue"]) - before)
        if result["status"] in ("checked", "candidate"):
            # A graph may retain a target that was checked only before this
            # fault. Keep its exact descendants available for exploration,
            # but do not reward that graph delta as post-fault target feedback.
            novelty = (0 if result.get("runner_mode") == "region_state" and
                       "post_fault_target_check_observed" in result and
                       result["post_fault_target_check_observed"] is not True
                       else _novelty(state, result["native_delta"]))
            record["target_closure_novelty"] = novelty
            depth_feedback = None
            if state.get("scheduler_version", 1) >= 10:
                depth_feedback = _depth_feedback(active, result, novelty)
                record["depth_feedback"] = depth_feedback
            _enqueue(state, result["eligible_doors"], active["faults"],
                     novelty, depth_feedback,
                     anchor_address=active.get("anchor_address"))
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
    state = {"schema_version": SCHEMA, "case_id": config["case_id"],
            "scheduler_version": SCHEDULER_VERSION,
            "config_sha256": config_sha, "budget": config["budget"],
            "weave_receipt_sha256": _sha(Path(admitted["weave_config"][
                "output_classes"]) / "native-original-weave-receipt.json"),
            "origin": admitted["origin"],
            "zero_vm_sha256": admitted["zero_vm_sha256"],
            "runner_classpath_artifacts": admitted["runner_classpath_artifacts"],
            "status": "running", "terminal": False,
            "healthy": None, "trials": [], "queue": [], "seen_plan_keys": [],
            "seen_node_families": [], "seen_edge_families": [],
            "seen_context_boundary_families": [],
            "seen_value_read_from_families": [],
            "seen_branch_outcomes": [], "completed_fault_trials": 0,
            "fault_id_attempts": {}, "fault_id_successes": {},
            "elapsed_seconds": 0.0, "active": None, "next_trial_index": 1}
    if "multi_target_max_anchors" in config["recording"]:
        state["multi_anchor_config"] = {"multi_target_max_anchors":
            config["recording"]["multi_target_max_anchors"]}
    return state


def _predecessor_snapshot(config: dict[str, Any], root: Path,
                          state: dict[str, Any], *, verify_derived: bool = True
                          ) -> tuple[dict[str, Any], list[dict[str, Any]],
                                     list[tuple[list[dict[str, Any]],
                                                list[dict[str, Any]]]], set[str]]:
    """Read a terminal campaign as immutable, exact successor input.

    A source checkpoint includes untested queued plans as well as tested plan
    keys. Preserve the queue, but exclude every completed exact plan from the
    successor. Rebuild actor-drift plans only from hash-checked native receipts.
    """
    pins = config["predecessor_campaign"]
    paths = {name: Path(pins[name]).resolve(strict=True)
             for name in ("config", "checkpoint", "summary")}
    for name, path in paths.items():
        if not path.is_file() or _sha(path) != pins[name + "_sha256"]:
            raise ValueError(f"predecessor {name} SHA-256 mismatch")
    source_root = paths["checkpoint"].parent
    if (source_root == root.resolve() or
            paths["checkpoint"].name != "checkpoint.json" or
            paths["summary"] != source_root / "summary.json"):
        raise ValueError("predecessor must be a distinct terminal campaign root")
    source_config = _load(paths["config"])
    source = _load(paths["checkpoint"])
    summary = _load(paths["summary"])
    if (source.get("schema_version") != SCHEMA or
            source.get("config_sha256") != pins["config_sha256"] or
            source.get("case_id") != config["case_id"] or
            source.get("terminal") is not True or
            source.get("active") is not None or
            source.get("status") not in ("complete_trial_budget",
                                         "complete_time_budget",
                                         "complete_queue") or
            not isinstance(source.get("healthy"), dict) or
            source["healthy"].get("status") != "healthy_seed" or
            summary != {key: value for key, value in source.items()
                        if key not in ("queue", "seen_plan_keys", "active")}):
        raise ValueError("predecessor is not a consistent completed campaign")
    _verify_terminal_peer_ranking_receipts(source_root, source)
    # A new budget and scheduler are legitimate; workload, target, bytecode,
    # static scope, and original recorder identity must remain exact.
    for name in ("case_id", "target_site", "target_throw",
                 "target_actor_names", "native_weave_config", "recording",
                 "junit", "runner", "timeout_seconds"):
        if source_config.get(name) != config.get(name):
            raise ValueError(f"predecessor {name} differs from successor")
    for name in ("weave_receipt_sha256", "origin", "zero_vm_sha256",
                 "runner_classpath_artifacts"):
        if source.get(name) != state.get(name):
            raise ValueError(f"predecessor {name} pin differs from successor")
    source_budget = source_config.get("budget")
    checkpoint_budget = source.get("budget")
    successor_budget = config.get("budget")
    state_budget = state.get("budget")
    if any(not isinstance(budget, dict) for budget in (
            source_budget, checkpoint_budget, successor_budget, state_budget)):
        raise ValueError("predecessor fault-depth budget is malformed")
    source_depth = source_budget.get("max_faults_per_trial")
    checkpoint_depth = checkpoint_budget.get("max_faults_per_trial")
    successor_depth = successor_budget.get("max_faults_per_trial")
    state_depth = state_budget.get("max_faults_per_trial")
    if (not isinstance(source_depth, int) or isinstance(source_depth, bool) or
            not 1 <= source_depth <= MAX_FAULTS or
            not isinstance(checkpoint_depth, int) or
            isinstance(checkpoint_depth, bool) or checkpoint_depth != source_depth or
            not isinstance(successor_depth, int) or
            isinstance(successor_depth, bool) or
            not source_depth <= successor_depth <= MAX_FAULTS or
            not isinstance(state_depth, int) or isinstance(state_depth, bool) or
            state_depth != successor_depth):
        raise ValueError("predecessor fault-depth limit is not a valid monotonic extension")
    expanding_depth = successor_depth > source_depth
    all_events_pinned = "source_all_event_tree_sha256" in pins
    if expanding_depth and not all_events_pinned:
        raise ValueError("fault-depth extension needs an all-trial event SHA-256 pin")

    seen = source.get("seen_plan_keys")
    queue = source.get("queue")
    trials = source.get("trials")
    if (not isinstance(seen, list) or not isinstance(queue, list) or
            not isinstance(trials, list) or
            len(trials) != source.get("completed_fault_trials") or
            any(not isinstance(key, str) or not SHA256_HEX.fullmatch(key)
                for key in seen) or len(set(seen)) != len(seen)):
        raise ValueError("predecessor plan index is malformed")
    seen_set = set(seen)

    def plan_key(faults: Any) -> str:
        if (not isinstance(faults, list) or not 1 <= len(faults) <=
                source_depth):
            raise ValueError("predecessor exact fault sequence is invalid")
        for fault in faults:
            if (not isinstance(fault, dict) or
                    any(not isinstance(fault.get(field), str) or not fault[field]
                        for field in ("siteId", "node", "exceptionClass")) or
                    not isinstance(fault.get("actorEpochOrdinal"), int) or
                    isinstance(fault["actorEpochOrdinal"], bool) or
                    fault["actorEpochOrdinal"] < 0 or
                    not isinstance(fault.get("ordinal"), int) or
                    isinstance(fault["ordinal"], bool) or fault["ordinal"] <= 0):
                raise ValueError("predecessor exact fault selector is malformed")
        return _plan_key(faults)

    tested: set[str] = set()
    result_digest = hashlib.sha256()
    event_digest = hashlib.sha256()
    all_event_digest = hashlib.sha256()
    successors = []
    trial_names = set()
    for item in trials:
        if not isinstance(item, dict):
            raise ValueError("predecessor trial record is malformed")
        name = item.get("name")
        if (not isinstance(name, str) or not re.fullmatch(r"r[0-9]{4,}", name)
                or name in trial_names or
                item.get("result") != f"trials/{name}/result.json"):
            raise ValueError("predecessor trial path is invalid")
        trial_names.add(name)
        result_file = source_root / item["result"]
        if result_file.resolve(strict=True) != result_file:
            raise ValueError("predecessor trial result must not be a symlink")
        result = _load(result_file)
        _verify_peer_ranking_receipt(result_file.parent, result)
        if (result.get("case_id") != config["case_id"] or
                result.get("status") != item.get("status") or
                not isinstance(result.get("faults"), list) or
                not result["faults"]):
            raise ValueError("predecessor trial result disagrees with checkpoint")
        key = plan_key(result["faults"])
        if key not in seen_set:
            raise ValueError("predecessor tested plan is absent from plan index")
        if expanding_depth and key in tested:
            raise ValueError("predecessor executed plan key is duplicated")
        tested.add(key)
        result_digest.update(item["result"].encode("utf-8") + b"\0")
        result_digest.update(bytes.fromhex(_sha(result_file)))
        events_file = (source_root / "trials" / name / "iteration-native" /
                       "fault-events.jsonl")
        if all_events_pinned:
            if (not events_file.is_file() or
                    events_file.resolve(strict=True) != events_file or
                    _sha(events_file) != result.get("fault_events_sha256")):
                raise ValueError("predecessor all-trial native fault receipts changed")
            all_event_digest.update(events_file.relative_to(source_root).as_posix()
                                    .encode("utf-8") + b"\0")
            all_event_digest.update(bytes.fromhex(_sha(events_file)))
        if result["status"] == "unmatched" and result.get(
                "runner_mode") == "region_state":
            if (events_file.resolve(strict=True) != events_file or
                    _sha(events_file) != result.get("fault_events_sha256")):
                raise ValueError("predecessor native fault receipts changed")
            event_digest.update(events_file.relative_to(source_root).as_posix()
                                .encode("utf-8") + b"\0")
            event_digest.update(bytes.fromhex(_sha(events_file)))
            rows = _rows(events_file)
            prefix, alternatives = _unmatched_actor_successors(
                result["faults"], rows)
            if alternatives:
                successors.append((result["faults"][:prefix], alternatives))

    imported_queue = []
    queue_keys = set()
    for item in queue:
        if not isinstance(item, dict) or not isinstance(item.get("faults"), list):
            raise ValueError("predecessor pending plan is malformed")
        key = plan_key(item["faults"])
        if (key != item.get("key") or key not in seen_set or
                key in queue_keys):
            raise ValueError("predecessor pending plan index disagrees")
        queue_keys.add(key)
        if key not in tested:
            imported_queue.append({**item, "enqueued_at": 0, "attempt": 0})

    receipt = {
        "schema_version": 1, "source_root": str(source_root),
        "source_pins": {name: pins[name + "_sha256"]
                        for name in ("config", "checkpoint", "summary")},
        "source_status": source["status"],
        "source_fault_depth_limit": source_depth,
        "successor_fault_depth_limit": successor_depth,
        "source_completed_fault_trials": len(trials),
        "source_seen_plan_count": len(seen),
        "tested_plan_keys_sha256": hashlib.sha256("\n".join(sorted(tested))
                                                   .encode("ascii")).hexdigest(),
        "tested_plan_count": len(tested),
        "source_result_tree_sha256": result_digest.hexdigest(),
        "source_unmatched_event_tree_sha256": event_digest.hexdigest(),
        "pending_untested_plan_count": len(imported_queue),
        "observed_actor_successor_groups": len(successors),
    }
    if all_events_pinned:
        receipt["source_all_event_tree_sha256"] = all_event_digest.hexdigest()
    if verify_derived and any(receipt[name] != pins[name] for name in (
            "tested_plan_keys_sha256", "source_result_tree_sha256",
            "source_unmatched_event_tree_sha256") +
            (("source_all_event_tree_sha256",) if all_events_pinned else ())):
        raise ValueError("predecessor tested-plan or trial receipt hash changed")
    return receipt, imported_queue, successors, seen_set


def build_predecessor_pins(
        config_path: Path, terminal_root: Path, *,
        successor_max_faults_per_trial: int | None = None) -> dict[str, str]:
    """Build reviewable SHA pins for a completed campaign; never mutate it."""
    config_path = config_path.resolve(strict=True)
    terminal_root = terminal_root.resolve(strict=True)
    paths = {"config": config_path,
             "checkpoint": terminal_root / "checkpoint.json",
             "summary": terminal_root / "summary.json"}
    pins = {name: str(path) for name, path in paths.items()}
    pins.update({name + "_sha256": _sha(path) for name, path in paths.items()})
    prospective = _load(config_path)
    source_budget = prospective.get("budget")
    source_depth = (source_budget.get("max_faults_per_trial")
                    if isinstance(source_budget, dict) else None)
    if successor_max_faults_per_trial is not None:
        if (not isinstance(successor_max_faults_per_trial, int) or
                isinstance(successor_max_faults_per_trial, bool) or
                not isinstance(source_depth, int) or isinstance(source_depth, bool) or
                not source_depth <= successor_max_faults_per_trial <= MAX_FAULTS):
            raise ValueError("successor fault depth must monotonically extend source")
        prospective["budget"] = {**prospective["budget"],
                                  "max_faults_per_trial": successor_max_faults_per_trial}
        if successor_max_faults_per_trial > source_depth:
            pins["source_all_event_tree_sha256"] = "0" * 64
    prospective["predecessor_campaign"] = pins
    source = _load(paths["checkpoint"])
    successor_state = {**source, "budget": prospective["budget"]}
    receipt, _, _, _ = _predecessor_snapshot(
        prospective, terminal_root.parent, successor_state, verify_derived=False)
    derived_names = ("tested_plan_keys_sha256", "source_result_tree_sha256",
                     "source_unmatched_event_tree_sha256")
    if "source_all_event_tree_sha256" in pins:
        derived_names += ("source_all_event_tree_sha256",)
    for name in derived_names:
        pins[name] = receipt[name]
    return pins


def _import_predecessor(config: dict[str, Any], root: Path,
                        state: dict[str, Any]) -> None:
    receipt, queue, successors, seen = _predecessor_snapshot(config, root, state)
    source = _load(Path(config["predecessor_campaign"]["checkpoint"]))
    state["seen_plan_keys"] = sorted(seen)
    state["queue"] = queue
    for name in ("seen_node_families", "seen_edge_families",
                 "seen_context_boundary_families",
                 "seen_value_read_from_families",
                 "seen_branch_outcomes", "fault_id_attempts", "fault_id_successes"):
        state[name] = source.get(name, {} if name.startswith("fault_id_") else [])
    before = len(state["queue"])
    for prefix, alternatives in successors:
        _enqueue(state, alternatives, prefix, 0)
    receipt["new_actor_successor_plan_count"] = len(state["queue"]) - before
    state["predecessor_import"] = receipt
    _atomic(root / "predecessor-import.json", receipt)


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
                "faults") != active["faults"] or result.get(
                "anchor_address") != active.get("anchor_address"):
            raise ValueError("completed native trial disagrees with checkpoint")
        local_sha = result.get("local_artifacts_manifest_sha256")
        if local_sha is not None and _sha(trial / "local-artifacts.json") != local_sha:
            raise ValueError("completed native trial local artifact receipt changed")
        _verify_peer_ranking_receipt(trial, result)
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
            if (isinstance(pid, int) and
                    process_receipt.get("host", os.uname().nodename) ==
                    os.uname().nodename):
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
    healthy_raw_throw_count = None
    if active["index"] > 0:
        healthy_result = _load(root / "trials" / "r0000" / "result.json")
        if state.get("multi_anchor_addresses"):
            healthy_file = root / "trials" / "r0000" / "native-summary.json"
            if (_sha(healthy_file) != healthy_result.get("native_session_sha256")
                    or not isinstance(healthy, dict) or
                    [row.get("occurrenceAddress") for row in healthy.get(
                        "anchors", [])] != state["multi_anchor_addresses"]):
                raise ValueError("healthy multi-target graph bundle changed")
            for index, row in enumerate(healthy["anchors"]):
                graph_file = (root / "trials" / "r0000" / "original-graph" /
                              f"anchor-{index:02d}" / "summary.json")
                if (not graph_file.is_file() or
                        _sha(graph_file) != row.get("summarySha256") or
                        _load(graph_file) != row.get("summary")):
                    raise ValueError("healthy exact target graph changed")
        healthy_raw_throw_count = healthy_result.get("raw_exact_target_throw_count")
        if (healthy_raw_throw_count is not None and
                (not isinstance(healthy_raw_throw_count, int) or
                 isinstance(healthy_raw_throw_count, bool) or
                 healthy_raw_throw_count < 0)):
            raise ValueError("invalid healthy exact target throw count")
    version_arg = ({"scheduler_version": state["scheduler_version"]}
                   if "scheduler_version" in state else {})
    if active["index"] > 0:
        result = _run_trial(config, admitted, trial, active["faults"], healthy,
                            healthy_raw_throw_count,
                            anchor_address=active.get("anchor_address"),
                            **version_arg)
    else:
        result = _run_trial(config, admitted, trial, active["faults"], healthy,
                            **version_arg)
    _accept(state, result, name)
    _atomic(root / "checkpoint.json", state)


def run_campaign(config_path: Path, root: Path,
                 stop_after_fault_trials: int | None = None) -> dict[str, Any]:
    config_path = config_path.resolve(strict=True)
    config = _load(config_path)
    _validate_config(config)
    if stop_after_fault_trials is not None and (
            not isinstance(stop_after_fault_trials, int) or
            isinstance(stop_after_fault_trials, bool) or
            not 0 < stop_after_fault_trials <= config["budget"]["fault_trials"]):
        raise ValueError("stop_after_fault_trials must be within the formal fault budget")
    config_sha = _sha(config_path)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _validate_local_work_root(config, root)
    _validate_local_artifact_root(config, root)
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
            if config.get("predecessor_campaign") is not None:
                receipt, _, _, _ = _predecessor_snapshot(config, root, state)
                saved = state.get("predecessor_import")
                if (not isinstance(saved, dict) or
                        {key: value for key, value in saved.items()
                         if key != "new_actor_successor_plan_count"} != receipt or
                        _load(root / "predecessor-import.json") != saved):
                    raise ValueError("predecessor import receipt changed")
            elif "predecessor_import" in state:
                raise ValueError("native checkpoint unexpectedly imports a predecessor")
        else:
            state = _new_state(config, config_sha, admitted)
            if config.get("predecessor_campaign") is not None:
                _import_predecessor(config, root, state)
            _atomic(checkpoint, state)
        saved_stop = state.get("stop_after_completed_fault_trials")
        if (stop_after_fault_trials is not None and saved_stop is not None and
                stop_after_fault_trials != saved_stop):
            raise ValueError("CLI stop bound conflicts with checkpoint stop bound")
        bounded_stop = (stop_after_fault_trials if stop_after_fault_trials is not None
                        else saved_stop)
        if bounded_stop is not None and (
                not isinstance(bounded_stop, int) or isinstance(bounded_stop, bool) or
                bounded_stop < 0):
            raise ValueError("invalid completed fault trial stop bound")
        if (bounded_stop is not None and
                state["completed_fault_trials"] >= bounded_stop and
                state["active"] is not None):
            raise ValueError("bounded stop requires an accepted checkpoint")
        if state["terminal"]:
            _verify_terminal_peer_ranking_receipts(root, state)
            return state
        (root / "trials").mkdir(exist_ok=True)
        if state["healthy"] is None and state["active"] is None:
            state["active"] = {"index": 0, "name": "r0000", "faults": []}
            _atomic(checkpoint, state)
        _resume_active(config, admitted, root, state)
        # A bounded stop is a durable pause, not a terminal disposition.
        # Re-evaluate the formal budget when the same checkpoint is resumed.
        if state["status"] == "bounded_checkpoint_stop" and not state["terminal"]:
            if state["active"] is not None:
                raise ValueError("bounded stop requires an accepted checkpoint")
            state["status"] = "running"
        while not state["terminal"]:
            _finish_status(state)
            if state["terminal"]:
                break
            if bounded_stop is not None:
                if state["completed_fault_trials"] >= bounded_stop:
                    if state["active"] is not None:
                        raise ValueError("bounded stop requires an accepted checkpoint")
                    state["status"] = "bounded_checkpoint_stop"
                    break
            if state["active"] is None:
                selected = _pick(state)
                index = state["next_trial_index"]
                state["next_trial_index"] += 1
                state["active"] = {"index": index, "name": f"r{index:04d}",
                                   "faults": selected["faults"],
                                   "key": selected["key"],
                                   "tier": selected["tier"],
                                   "novelty": selected["novelty"],
                                   "attempt": selected.get("attempt", 0)}
                if "anchor_address" in selected:
                    state["active"]["anchor_address"] = selected[
                        "anchor_address"]
                if state.get("scheduler_version", 1) >= 5:
                    state["active"]["target_phase"] = selected.get(
                        "target_phase", "unknown")
                if state.get("scheduler_version", 1) >= 6:
                    state["active"]["selected_target_actor"] = selected.get(
                        "selected_target_actor")
                    state["active"]["target_order_distance"] = selected.get(
                        "target_order_distance")
                if state.get("scheduler_version", 1) >= 8:
                    state["active"]["peer_relation"] = selected.get(
                        "peer_relation", "unknown")
                if state.get("scheduler_version", 1) >= 10:
                    state["active"]["depth_feedback"] = selected.get(
                        "depth_feedback", {})
                _atomic(checkpoint, state)
            _resume_active(config, admitted, root, state)
        _atomic(checkpoint, state)
        _atomic(root / "summary.json", {key: value for key, value in state.items()
                                         if key not in ("queue", "seen_plan_keys", "active")})
        _verify_terminal_peer_ranking_receipts(root, state)
        return state
