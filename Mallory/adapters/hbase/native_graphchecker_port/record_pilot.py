#!/usr/bin/env python3
"""Record an unchanged HBase JUnit with the source-built GraphChecker engine.

This is a narrow integration pilot. The static input and GraphChecker output
must have been produced together; the script never chooses fault sites.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
ENGINE = Path(
    "/proj/silentfailure-PG0/ZhenyuLi/Mallory/runtime-pins/"
    "original-engine-0059dfd3a3f9bd5d.jar"
)
DEPENDENCIES = Path(
    "/proj/silentfailure-PG0/ZhenyuLi/mallory-hbase-native-original/"
    "original-engine-dependencies.txt"
)
RUNNER = "edu.uva.liftlab.graphchecker.runtime.NativeHBaseJUnitRunner"
MIN_ANALYSIS_HEAP_MB = 1024
MAX_ANALYSIS_HEAP_MB = 32768


def analysis_heap_mb(value: str) -> int:
    """Bound caller-supplied GraphChecker heaps without changing old defaults."""
    try:
        megabytes = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("analysis heap must be an integer in MiB") from error
    if not MIN_ANALYSIS_HEAP_MB <= megabytes <= MAX_ANALYSIS_HEAP_MB:
        raise argparse.ArgumentTypeError(
            f"analysis heap must be between {MIN_ANALYSIS_HEAP_MB} and "
            f"{MAX_ANALYSIS_HEAP_MB} MiB"
        )
    return megabytes


def jvm_heap_arg(megabytes: int) -> str:
    return (f"-Xmx{megabytes // 1024}g" if megabytes % 1024 == 0
            else f"-Xmx{megabytes}m")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(stage: str, argv: list[str], root: Path, *, env=None, timeout=1800):
    commands = root / "commands"
    commands.mkdir(exist_ok=True)
    (commands / f"{stage}.json").write_text(json.dumps(argv, indent=2) + "\n")
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    with (commands / f"{stage}.stdout").open("wb") as out, (
        commands / f"{stage}.stderr"
    ).open("wb") as err:
        result = subprocess.run(argv, cwd=root, env=env, stdout=out,
                                stderr=err, timeout=timeout, check=False)
    (commands / f"{stage}.timing.json").write_text(json.dumps({
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }, indent=2) + "\n")
    (commands / f"{stage}.exit").write_text(str(result.returncode) + "\n")
    if result.returncode:
        raise RuntimeError(f"{stage} failed: {result.returncode}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("static_input", type=Path)
    parser.add_argument("static_output", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("junit_class")
    parser.add_argument("junit_method")
    parser.add_argument("--engine", type=Path, default=ENGINE)
    parser.add_argument("--fault-adapter", type=Path)
    parser.add_argument("--fault-hooks", action="store_true")
    parser.add_argument("--diagnostic-engine-mismatch", action="store_true")
    parser.add_argument("--diagnostic-partial-static", action="store_true")
    parser.add_argument("--recording-weave-heap-mb", type=analysis_heap_mb,
                        default=8192)
    parser.add_argument("--target-resolver-heap-mb", type=analysis_heap_mb,
                        default=4096)
    args = parser.parse_args()
    source = json.loads(args.static_input.read_text())
    analysis = source["analysis"]
    process = analysis["process_dirs"]
    cp_entries = analysis["classpath"]
    if len(process) != 1 or len(cp_entries) != 1:
        raise ValueError("pilot requires one original class directory and exact CP")
    original = args.static_output / "original"
    candidate = original / "candidate_dataflow_edges.jsonl.gz"
    scope = original / "static_scope_map.jsonl"
    skeletons = original / "region_skeletons.jsonl.gz"
    manifest = args.static_output / "weave_manifest.json"
    analysis_file = args.static_output / "analysis.json"
    if analysis_file.is_file():
        report = json.loads(analysis_file.read_text())
        if report.get("analysisKind") != "original_graphchecker_seed_backward":
            raise ValueError("static run did not complete original GraphChecker seed")
    elif not args.diagnostic_partial_static:
        raise ValueError("static run has no completed analysis receipt")
    elif not (args.static_output / "exit").is_file():
        raise ValueError("diagnostic partial static run has no terminal exit receipt")
    for path in (candidate, scope, skeletons, manifest):
        if not path.is_file():
            raise ValueError(f"missing GraphChecker static output: {path}")
    selected = json.loads(manifest.read_text())
    if args.fault_hooks and not selected.get("doors"):
        raise ValueError("static scope selected no injectable I/O doors")
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    cp = cp_entries[0]
    engine = args.engine.resolve(strict=True)
    engine_in_static_cp = str(engine) in cp.split(os.pathsep)
    if not engine_in_static_cp and not args.diagnostic_engine_mismatch:
        raise ValueError("recording engine is absent from the exact static CP")
    fault_adapter = args.fault_adapter.resolve(strict=True) if args.fault_adapter else None
    if fault_adapter and str(fault_adapter) not in cp.split(os.pathsep) \
            and not args.diagnostic_engine_mismatch:
        raise ValueError("recording fault adapter is absent from the exact static CP")
    if args.fault_hooks and not fault_adapter:
        raise ValueError("fault hooks require a pinned fault adapter")
    dependencies = DEPENDENCIES.read_text().strip()
    # Soot's tooling may use its own dependency order.  The unchanged HBase
    # MiniCluster must load the HBase dependency set first: its bundled HDFS
    # still calls the two-argument Guava Futures.addCallback API.
    adapter_cp = (str(fault_adapter) + os.pathsep) if fault_adapter else ""
    weave_cp = os.pathsep.join((str(engine), adapter_cp + dependencies, cp))
    runtime_cp = os.pathsep.join((str(engine), adapter_cp + cp, dependencies))
    (out / "pins.json").write_text(json.dumps({
        "static_input": str(args.static_input),
        "static_input_sha256": sha(args.static_input),
        "static_analysis_sha256": sha(analysis_file) if analysis_file.is_file() else None,
        "diagnostic_partial_static": args.diagnostic_partial_static,
        "static_exit": (args.static_output / "exit").read_text().strip()
        if (args.static_output / "exit").is_file() else None,
        "manifest_sha256": sha(manifest),
        "candidate_graph_sha256": sha(candidate),
        "scope_sha256": sha(scope),
        "skeletons_sha256": sha(skeletons),
        "engine_sha256": sha(engine),
        "fault_adapter_sha256": sha(fault_adapter) if fault_adapter else None,
        "engine_in_exact_static_cp": engine_in_static_cp,
        "diagnostic_engine_mismatch": args.diagnostic_engine_mismatch,
        "process_dir": process[0],
        "junit_class": args.junit_class,
        "junit_method": args.junit_method,
        "recording_weave_heap_mb": args.recording_weave_heap_mb,
        "target_resolver_heap_mb": args.target_resolver_heap_mb,
        "static_scope_map_bytes": scope.stat().st_size,
    }, indent=2) + "\n")
    woven = out / "recording-classes"
    woven.mkdir()
    artifacts = out / "weave-artifacts"
    artifacts.mkdir()
    shutil.copy2(candidate, artifacts / candidate.name)
    shutil.copy2(scope, artifacts / scope.name)
    weave = [JAVA, jvm_heap_arg(args.recording_weave_heap_mb),
             "-Dcausynth.trace.mode=region-state",
             f"-Dcausynth.region.skeletons={skeletons}",
             f"-Dcausynth.output.dir={artifacts}"]
    if args.fault_hooks:
        weave.append(f"-Dmallory.native.fault.manifest={manifest}")
    weave.extend(("-cp", weave_cp,
                  "edu.uva.liftlab.graphchecker.GraphCheckerMain",
                  "-i", process[0], "-x", cp, "-o", str(woven)))
    run("recording-weave", weave, out)
    trace = out / "healthy-trace"
    work = out / "junit"
    (work / "tmp").mkdir(parents=True)
    (work / "data").mkdir()
    env = dict(os.environ,
               CAUSYNTH_TRACE_OUTPUT_DIR=str(trace),
               CAUSYNTH_STATIC_SCOPE_MAP=str(scope))
    if args.fault_hooks:
        healthy_plan = out / "healthy-fault-plan.json"
        healthy_plan.write_text('{"faults":[]}\n')
        env["MALLORY_NATIVE_FAULT_PLAN"] = str(healthy_plan)
        env["MALLORY_NATIVE_FAULT_EVENTS"] = str(out / "healthy-fault-events.jsonl")
    selector = args.junit_class + "#" + args.junit_method
    run("healthy-junit", [
        JAVA, "-Xmx4g", f"-Djava.io.tmpdir={work / 'tmp'}",
        f"-Dbuild.test.dir={work / 'data'}",
        "-Dcausynth.trace.mode=region-state",
        f"-Dcausynth.trace.test={selector}",
        "-cp", str(woven) + os.pathsep + runtime_cp,
        RUNNER, args.junit_class, args.junit_method,
    ], out, env=env, timeout=900)
    junit_err = (out / "commands/healthy-junit.stderr").read_text(errors="replace")
    if "NATIVE_HBASE_JUNIT run=1 failed=0 ignored=0 exception=false" not in junit_err:
        raise RuntimeError("unchanged HBase JUnit did not pass exactly once")
    trace_manifest = json.loads((trace / "streaming_trace_manifest.json").read_text())
    if trace_manifest.get("status") != "CLOSED" and not trace_manifest.get("closed"):
        raise RuntimeError("healthy original GraphChecker session did not close")
    if args.fault_hooks and not (out / "healthy-fault-events.jsonl").is_file():
        raise RuntimeError("static-selected native fault hooks produced no receipt file")
    occurrence = out / "target-occurrence.json"
    run("target-occurrence", [
        JAVA, jvm_heap_arg(args.target_resolver_heap_mb), "-cp", weave_cp,
        "edu.uva.liftlab.graphchecker.runtime.MalloryTargetOccurrenceResolver",
        "--trace-dir", str(trace), "--test", selector,
        "--candidate-graph", str(candidate),
        "--static-scope-map", str(scope),
        "--region-skeletons", str(skeletons),
        "--output", str(occurrence),
    ], out, timeout=600)
    observed = json.loads(occurrence.read_text())
    if observed.get("reachedEventCount", 0) < 1:
        raise RuntimeError("healthy original JUnit did not reach selected target")
    print(json.dumps({"status": ("HEALTHY_TARGET_REACHED_DIAGNOSTIC"
                                 if args.diagnostic_partial_static else
                                 "HEALTHY_TARGET_REACHED"),
                      "target_occurrence": observed,
                      "output": str(out)}, indent=2))


if __name__ == "__main__":
    main()
