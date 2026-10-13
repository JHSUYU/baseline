"""Shared ZooKeeper original-GraphChecker preparation command.

The profile contains immutable classpaths and build inputs, never a target
branch, I/O door, fault site, or test selector. Those come from the inventory
request and original GraphChecker static/runtime receipts. A native protocol
gate must be accepted before this command can launch a heavy stage.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

from Mallory.instrumentation.graphchecker_port import native_original_weave as weave
from Mallory.native_graphchecker_campaign import campaign as native
from .preparation import _atomic, _digest, _object, _sha

PROFILE_MODE = "original_graphchecker_zookeeper_profile"
GATE_MODE = "original_graphchecker_zookeeper_protocol_gate"
SITE = re.compile(r"^<([^:]+): (.+)>#u([0-9]+)$")


def _paths(values: object, label: str) -> list[Path]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} requires nonempty pinned paths")
    paths = [Path(value) for value in values]
    if any(not path.is_absolute() or not path.exists() or path.is_symlink()
           for path in paths):
        raise ValueError(f"{label} has an absent or mutable path")
    return paths


def _profile(request: dict, profile_file: Path) -> dict:
    profile = _object(profile_file)
    if (profile.get("schema_version") != 1 or
            profile.get("mode") != PROFILE_MODE or
            request.get("system") != "zookeeper" or
            request.get("system_version") != profile.get("system_version") or
            not isinstance(profile.get("analysis"), dict) or
            any(key in profile["analysis"] for key in
                ("target", "check_line", "doors", "io_points", "fault_sites"))):
        raise ValueError("ZooKeeper profile is not a shared native adapter")
    for key in ("analysis_classpath", "scope_planner_classpath",
                "runtime_classpath", "runner_classpath", "post_weave_classpath"):
        _paths(profile.get(key), key)
    for key in ("source_root", "source_classes", "communication_mapping",
                "java", "protocol_gate"):
        path = Path(profile.get(key, ""))
        if not path.is_absolute() or not path.exists() or path.is_symlink():
            raise ValueError(f"ZooKeeper {key} is absent or mutable")
    if (not isinstance(profile.get("budget"), dict) or
            not isinstance(profile.get("timeout_seconds"), int) or
            profile["timeout_seconds"] <= 0 or
            not isinstance(profile.get("max_jobs"), int) or
            profile["max_jobs"] <= 0):
        raise ValueError("ZooKeeper profile lacks bounded campaign settings")
    runner_args = profile.get("runner_jvm_args", [])
    if (not isinstance(runner_args, list) or
            not all(isinstance(arg, str) and arg.startswith("-D")
                    for arg in runner_args) or
            any(arg.startswith(("-Djava.io.tmpdir=", "-Dbuild.test.dir="))
                for arg in runner_args)):
        raise ValueError("ZooKeeper runner args must preserve fresh trial directories")
    source = Path(profile["source_root"])
    target = request["target"]
    source_file = (source / target["source_path"]).resolve(strict=True)
    if (not source_file.is_relative_to(source.resolve(strict=True)) or
            _sha(source_file) != target.get("source_sha256")):
        raise ValueError("ZooKeeper original target source changed")
    junit = request["original_junit"]
    test_file = (source / junit["source_path"]).resolve(strict=True)
    if (not test_file.is_relative_to(source.resolve(strict=True)) or
            f"{junit['method']}(" not in test_file.read_text(encoding="utf-8")):
        raise ValueError("ZooKeeper original cluster JUnit source is absent")
    gate = _object(Path(profile["protocol_gate"]))
    source_classes = Path(profile["source_classes"])
    mapping = Path(profile["communication_mapping"])
    ports = gate.get("typedWirePorts")
    def verified_file(name: str, sha_name: str) -> None:
        path = Path(gate.get(name, ""))
        if (not path.is_absolute() or not path.is_file() or path.is_symlink() or
                _sha(path) != gate.get(sha_name)):
            raise ValueError(f"ZooKeeper protocol gate input changed: {name}")

    if (gate.get("mode") != GATE_MODE or gate.get("accepted") is not True or
            gate.get("typed_quorum_send_receive") is not True or
            gate.get("original_session_target_reached") is not True or
            gate.get("engine_jar_sha256") != _sha(native.JAR) or
            gate.get("source_tree_sha256") != weave.file_tree_digest(source) or
            gate.get("source_classes_sha256") != weave.class_tree_digest(
                source_classes) or
            gate.get("communication_mapping_sha256") != _sha(mapping) or
            gate.get("junitPassed") is not True or
            not isinstance(gate.get("junitClass"), str) or
            not gate["junitClass"] or
            not isinstance(gate.get("junitMethod"), str) or
            not gate["junitMethod"] or
            not isinstance(gate.get("targetSiteId"), str) or
            not gate["targetSiteId"] or
            not isinstance(gate.get("targetOccurrence"), str) or
            not gate["targetOccurrence"] or
            not isinstance(gate.get("targetClosureWireEdges"), int) or
            isinstance(gate["targetClosureWireEdges"], bool) or
            gate["targetClosureWireEdges"] <= 0 or
            gate.get("blockingGaps") != 0 or
            not isinstance(ports, list) or
            not all(isinstance(port, str) for port in ports) or
            not {"FOLLOWERINFO", "LEADERINFO"}.issubset(set(ports))):
        raise ValueError("ZooKeeper native quorum/actor protocol gate pending")
    verified_file("static_map_path", "static_map_sha256")
    verified_file("session_manifest_path", "session_manifest_sha256")
    postweave = Path(gate.get("postweave_class_tree_path", ""))
    if (not postweave.is_absolute() or not postweave.is_dir() or
            weave.class_tree_digest(postweave) != gate.get(
                "postweave_class_tree_sha256")):
        raise ValueError("ZooKeeper gate postweave class tree changed")
    adapter_build = Path(gate.get("adapter_build_path", ""))
    if (not adapter_build.is_absolute() or not adapter_build.exists() or
            adapter_build.is_symlink() or
            (_sha(adapter_build) if adapter_build.is_file() else
             weave.file_tree_digest(adapter_build)) != gate.get(
                "adapter_build_sha256")):
        raise ValueError("ZooKeeper gate adapter build changed")
    if _object(Path(gate["session_manifest_path"])).get("closed") is not True:
        raise ValueError("ZooKeeper gate original session did not close")
    return profile


def _target(request: dict) -> tuple[str, str, int]:
    target = request["target"]
    match = SITE.fullmatch(target["site_id"])
    function = target["function"]
    if not match or not isinstance(function, str):
        raise ValueError("inventory target is not an exact original Soot throw")
    clazz = match.group(1)
    method = function.split("(", 1)[0].rsplit(".", 1)[-1]
    if not function.startswith(clazz + ".") or not method:
        raise ValueError("inventory target method differs from exact site")
    line = target.get("compiled_throw_source_line") or target["source_line"]
    if not isinstance(line, int) or line <= 0:
        raise ValueError("inventory throw line is invalid")
    return clazz, method, line


def _cp(paths: list[Path]) -> str:
    return os.pathsep.join(str(path.resolve(strict=True)) for path in paths)


def _run(stage: str, argv: list[str], output: Path, timeout: int,
         env: dict[str, str] | None = None) -> None:
    (output / "commands").mkdir(exist_ok=True)
    _atomic(output / "commands" / f"{stage}.json", {"argv": argv})
    with (output / "commands" / f"{stage}.stdout").open("wb") as stdout, (
            output / "commands" / f"{stage}.stderr").open("wb") as stderr:
        result = subprocess.run(argv, cwd=output, env=env,
                                stdout=stdout, stderr=stderr, timeout=timeout)
    if result.returncode:
        raise ValueError(f"original GraphChecker {stage} failed: {result.returncode}")


def select_target_task(plan_file: Path, occurrence: dict) -> dict:
    """Select an admitted original scheduler task for the resolved guard."""
    candidates = []
    for line in plan_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        branch = row.get("targetBranch") or {}
        if (row.get("goalKind") == "TARGET_REACH_CLOSURE" and
                row.get("occurrenceId") == occurrence["selectedOccurrenceAddress"] and
                branch.get("siteId") == occurrence["checkSiteId"] and
                row.get("admission", {}).get("state") == "EXECUTABLE" and
                isinstance(branch.get("occurrence"), int) and
                branch["occurrence"] >= 0 and
                isinstance(row.get("taskId"), str)):
            candidates.append(row)
    if len(candidates) != 1:
        raise ValueError("original scheduler did not yield one exact target task")
    return candidates[0]


def _original_cp(extra: list[Path]) -> str:
    dependencies = native.DEPENDENCIES.read_text(encoding="utf-8").strip()
    return os.pathsep.join((str(native.JAR.resolve(strict=True)), dependencies,
                            _cp(extra)))


def prepare(request_file: Path, output: Path, profile_file: Path) -> dict:
    request = _object(request_file)
    profile = _profile(request, profile_file)
    if output.exists() and any(output.iterdir()):
        raise ValueError("native adapter output must start empty")
    output.mkdir(parents=True, exist_ok=True)
    clazz, method, line = _target(request)
    source_classes = Path(profile["source_classes"]).resolve(strict=True)
    process_classes_sha = weave.class_tree_digest(source_classes)
    java = str(Path(profile["java"]).resolve(strict=True))
    map_file = str(Path(profile["communication_mapping"]).resolve(strict=True))
    analysis_cp = _paths(profile["analysis_classpath"], "analysis_classpath")
    extra = _paths(profile["runtime_classpath"], "runtime_classpath")
    scope_cp = _paths(profile["scope_planner_classpath"], "scope_planner_classpath")
    if native.JAR.resolve(strict=True) not in scope_cp:
        raise ValueError("static planner did not load the pinned source-built engine")
    original = output / "original"
    analysis = dict(profile["analysis"])
    analysis.update(process_dirs=[str(source_classes)],
                    classpath=[str(path.resolve(strict=True)) for path in analysis_cp],
                    original_graphchecker_seed=True,
                    original_engine_output_dir=str(original))
    scope_input = output / "scope-input.json"
    _atomic(scope_input, {"case_id": request["case_id"],
                          "target": {"class": clazz, "method": method,
                                     "line": line, "kind": "THROW",
                                     "exception": request["target"]["target_exception"]},
                          "analysis": analysis})
    scope_out = output / "scope"
    _run("static", [java, f"-Dcausynth.communication.mappings={map_file}",
                    "-Xmx4g", "-cp", _cp(scope_cp),
                    "edu.uva.liftlab.mallory.scope.ScopePlanner",
                    str(scope_input), str(scope_out)], output, 1800)
    report = _object(scope_out / "analysis.json")
    if (report.get("analysisKind") != "original_graphchecker_seed_backward" or
            report.get("throwSiteId") != request["target"]["site_id"] or
            report.get("sootDependencyClasspathSha256") != hashlib.sha256(
                _cp(analysis_cp).encode("utf-8")).hexdigest() or
            weave.class_tree_digest(source_classes) != process_classes_sha):
        raise ValueError("Soot scope did not resolve the inventory throw")
    graph = original / "candidate_dataflow_edges.jsonl.gz"
    scope = original / "static_scope_map.jsonl"
    skeletons = original / "region_skeletons.jsonl.gz"
    for path in (graph, scope, skeletons, scope_out / "weave_manifest.json"):
        if not path.is_file():
            raise ValueError("original GraphChecker static output incomplete")
    _atomic(output / "static-scope-receipt.json", {
        "schema_version": 1, "mode": "original_graphchecker_static_scope",
        "case_id": request["case_id"], "request_sha256": _digest(request),
        "analysis_kind": report["analysisKind"],
        "analysis_path": str(scope_out / "analysis.json"),
        "analysis_sha256": _sha(scope_out / "analysis.json"),
        "scope_input_path": str(scope_input),
        "scope_input_sha256": _sha(scope_input),
        "engine_jar_sha256": _sha(native.JAR),
        "process_classes_path": str(source_classes),
        "process_classes_sha256": process_classes_sha,
        "ordered_analysis_classpath_sha256": hashlib.sha256(
            _cp(analysis_cp).encode("utf-8")).hexdigest(),
        "candidate_graph_sha256": _sha(graph),
        "static_scope_map_sha256": _sha(scope),
        "region_skeletons_sha256": _sha(skeletons)})
    recorded_classes = output / "recording-classes"
    _run("region-state-weave", [
        java, f"-Dcausynth.communication.mappings={map_file}",
        "-Dcausynth.trace.mode=region-state",
        f"-Dcausynth.region.skeletons={skeletons}",
        f"-Dcausynth.output.dir={output / 'recording-artifacts'}",
        "-cp", _original_cp(extra),
        "edu.uva.liftlab.graphchecker.GraphCheckerMain", "-i",
        str(source_classes), "-x", _cp(extra), "-o", str(recorded_classes)],
        output, 1800)
    if weave.class_tree_digest(source_classes) != process_classes_sha:
        raise ValueError("recording weave preimage changed since static Soot analysis")
    post = _paths(profile["post_weave_classpath"], "post_weave_classpath")
    _run("recording-postweave", [java, "-cp", _cp(post),
        "edu.uva.liftlab.mallory.nativecampaign.NativeZooKeeperCombinedPostWeave",
        str(recorded_classes), _cp(extra)], output, 600)
    _atomic(output / "recording-weave-receipt.json", {
        "schema_version": 1, "mode": "original_graphchecker_region_state_weave",
        "case_id": request["case_id"], "request_sha256": _digest(request),
        "engine_jar_sha256": _sha(native.JAR),
        "input_classes": str(source_classes),
        "input_classes_sha256": weave.class_tree_digest(source_classes),
        "output_classes": str(recorded_classes),
        "output_classes_sha256": weave.class_tree_digest(recorded_classes)})
    trace = output / "healthy-trace"
    junit = request["original_junit"]
    runner_cp = _paths(profile["runner_classpath"], "runner_classpath")
    run_root = output / "healthy-junit"
    (run_root / "tmp").mkdir(parents=True)
    (run_root / "data").mkdir()
    env = os.environ.copy()
    env.update(CAUSYNTH_TRACE_OUTPUT_DIR=str(trace),
               CAUSYNTH_STATIC_SCOPE_MAP=str(scope))
    _run("healthy-junit", [java, "-Xmx3g",
        f"-Djava.io.tmpdir={run_root / 'tmp'}",
        f"-Dbuild.test.dir={run_root / 'data'}",
        "-Dcausynth.trace.mode=region-state",
        f"-Dcausynth.trace.test={junit['selector']}",
        "-cp", _original_cp([recorded_classes, *runner_cp]),
        "edu.uva.liftlab.graphchecker.runtime.NativeRecordingJUnitMethodRunner",
        junit["class"], junit["method"]], output,
        profile["timeout_seconds"], env)
    stdout = (output / "commands/healthy-junit.stdout").read_text(
        encoding="utf-8", errors="replace")
    manifest = _object(trace / "streaming_trace_manifest.json")
    if ("NATIVE_RECORDING_JUNIT_RESULT passed=1 failed=0" not in stdout or
            manifest.get("closed") is not True):
        raise ValueError("unchanged original JUnit or healthy recording did not close")
    occurrence_file = output / "target-occurrence.json"
    _run("target-occurrence", [java, "-cp", _original_cp([]),
        "edu.uva.liftlab.graphchecker.runtime.MalloryTargetOccurrenceResolver",
        "--trace-dir", str(trace), "--test", junit["selector"],
        "--candidate-graph", str(graph), "--static-scope-map", str(scope),
        "--region-skeletons", str(skeletons),
        "--output", str(occurrence_file)], output, 300)
    occurrence = _object(occurrence_file)
    if (occurrence.get("kind") != "MALLORY_OBSERVED_TARGET_OCCURRENCE" or
            occurrence.get("reachedEventCount", 0) < 1):
        raise ValueError("original runtime found no observed target check")
    recorded = output / "recorded-plan"
    scheduled = output / "scheduled-plan"
    target_arg = f"target={graph},{scope},{skeletons},{recorded}"
    selector = occurrence["selectedOccurrenceAddress"]
    _run("original-recorder", [java, "-cp", _original_cp([]),
        "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
        "--trace-dir", str(trace), "--test", junit["selector"],
        "--target", target_arg, "--target-occurrence", selector], output, 300)
    _run("original-scheduler", [java, "-cp", _original_cp([]),
        "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler",
        "--region-plan", str(recorded / "concolic_region_plan.jsonl"),
        "--candidate-graph", str(graph), "--static-scope-map", str(scope),
        "--output-dir", str(scheduled), "--max-jobs", str(profile["max_jobs"]),
        "--target-occurrence", selector], output, 300)
    plan = scheduled / "execution_task_plan.jsonl"
    task = select_target_task(plan, occurrence)
    branch = task["targetBranch"]
    anchor = f"{branch['siteId']}#{branch['occurrence']}"
    weave_file = output / "native-weave.json"
    _atomic(weave_file, {
        "java": java, "input_classes": str(source_classes),
        "output_classes": str(output / "concolic-classes"),
        "task_plan": str(plan), "task_id": task["taskId"],
        "region_skeletons": str(recorded / "region_skeletons.jsonl"),
        "dependency_classpath": _cp(extra),
        "native_fault_manifest": str(scope_out / "weave_manifest.json"),
        "post_weave": {"classpath": _cp(post),
            "main_class":
                "edu.uva.liftlab.mallory.nativecampaign.NativeZooKeeperCombinedPostWeave",
            "args": ["{woven_classes}", _cp(extra)]},
        "timeout_seconds": 1800})
    weave.run(weave_file)
    native_weave_receipt = _object(
        output / "concolic-classes/native-original-weave-receipt.json")
    if native_weave_receipt.get("input_classes_sha256") != process_classes_sha:
        raise ValueError("concolic weave preimage differs from static Soot analysis")
    config = {
        "case_id": request["case_id"], "target_site": anchor,
        "target_throw": {"siteId": request["target"]["site_id"],
                         "exceptionClass": request["target"]["target_exception"]},
        "native_weave_config": str(weave_file),
        "recording": {"trace_dir": str(trace), "test_id": junit["selector"],
                      "target_name": "target", "candidate_graph": str(graph),
                      "static_scope_map": str(scope),
                      "region_skeletons": str(skeletons),
                      "target_occurrence": selector,
                      "max_jobs": profile["max_jobs"]},
        "junit": {"class": junit["class"], "method": junit["method"]},
        "runner": {"zero_vm_java": java,
                   "main_class":
                       "edu.uva.liftlab.graphchecker.runtime.NativeJUnitMethodRunner",
                   "classpath": [str(path) for path in runner_cp],
                   "jvm_args": ["-Djava.io.tmpdir={trial_workdir}",
                                "-Dbuild.test.dir={trial_workdir}",
                                *profile.get("runner_jvm_args", [])]},
        "budget": profile["budget"],
        "timeout_seconds": profile["timeout_seconds"]}
    native._validate_config(config)
    _atomic(output / "case.json", config)
    proof = {
        "schema_version": 1, "mode": "original_graphchecker_native_adapter",
        "case_id": request["case_id"], "request_sha256": _digest(request),
        "original_cluster_junit_verified": True,
        "scope_generated_by_original_graphchecker": True,
        "recording_closed": True,
        "junit": {"class": junit["class"], "method": junit["method"]},
        "source_evidence_paths": [str(Path(profile["source_root"]) /
                                      request["target"]["source_path"]),
                                  str(Path(profile["source_root"]) /
                                      junit["source_path"])],
        "static_scope_receipt_path": str(output / "static-scope-receipt.json"),
        "recording_weave_receipt_path": str(output / "recording-weave-receipt.json"),
        "target_occurrence_receipt_path": str(occurrence_file),
        "target_occurrence_receipt_sha256": _sha(occurrence_file),
        "protocol_gate_path": profile["protocol_gate"],
        "protocol_gate_sha256": _sha(Path(profile["protocol_gate"]))}
    _atomic(output / "adapter-proof.json", proof)
    return proof


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: python -m Mallory.native_graphchecker_dispatch."
                         "zookeeper_native_adapter PROFILE REQUEST OUTPUT")
    print(json.dumps(prepare(Path(sys.argv[2]), Path(sys.argv[3]),
                             Path(sys.argv[1])), sort_keys=True))


if __name__ == "__main__":
    main()
