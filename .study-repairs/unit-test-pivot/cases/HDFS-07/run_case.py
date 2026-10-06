"""Isolated Hadoop 3.4.3 MiniJournalCluster trial for HDFS-07.

The workload is the original TestQuorumJournalManager JUnit method.  All
weaving, traces, and temporary cluster state live in the case directory.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
HADOOP = Path.home() / ".baseline-deps/hadoop-3.4.3"
GRAPH = Path.home() / ".graphchecker-builds/unit-test-core-dd4bcd000-2572d2fee254.jar"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
TARGET_CLASS = "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager"
TARGET_METHOD = "testRecoverAfterIncompleteRecovery"
TARGET_TEST = TARGET_CLASS + "#" + TARGET_METHOD
TARGET_STEM = "org/apache/hadoop/hdfs/qjournal/server/Journal"
STATIC = HERE / "static"
SCOPE = HERE / "scope"
LINEAGE = HERE / "lineage"
WOVEN = HERE / "instrumented"


def logged(command: list[str], path: Path, timeout: int, *, cwd: Path | None = None,
           env: dict[str, str] | None = None) -> dict:
    started = time.monotonic()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        try:
            result = subprocess.run(command, cwd=cwd, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
            status = result.returncode
        except subprocess.TimeoutExpired:
            status = 124
    return {"exit": status, "elapsed_seconds": round(time.monotonic() - started, 3),
            "log": str(path)}


def classpath() -> str:
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                   env=env, text=True).strip()
    tools = os.pathsep.join(str(path) for path in sorted(
        (HADOOP / "share/hadoop/tools/lib").glob("*.jar")))
    test_dependencies = [
        HERE / "deps/mockito-core-4.9.0.jar",
        HERE / "deps/byte-buddy-1.12.16.jar",
        HERE / "deps/byte-buddy-agent-1.12.16.jar",
        HERE / "deps/objenesis-3.3.jar",
    ]
    for dependency in test_dependencies:
        if not dependency.is_file():
            raise FileNotFoundError(dependency)
    return os.pathsep.join((
        str(Path.home() / ".graphchecker-sources/hadoop-3.4.3/"
            "hadoop-hdfs-project/hadoop-hdfs/src/test/resources"),
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        *(str(path) for path in test_dependencies), base, tools))


def prepare_scope() -> int:
    count = 0
    with ZipFile(HDFS) as archive:
        for name in archive.namelist():
            if not name.endswith(".class"):
                continue
            data = archive.read(name)
            lineage = LINEAGE / name
            lineage.parent.mkdir(parents=True, exist_ok=True)
            lineage.write_bytes(data)
            if name == TARGET_STEM + ".class" or name.startswith(TARGET_STEM + "$"):
                scope = SCOPE / name
                scope.parent.mkdir(parents=True, exist_ok=True)
                scope.write_bytes(data)
                count += 1
    return count


def static() -> None:
    STATIC.mkdir(parents=True, exist_ok=True)
    count = prepare_scope()
    target = STATIC / "target.yaml"
    target.write_text("exception_target: hdfs-adhoc-07 "
                      "org.apache.hadoop.hdfs.qjournal.server.Journal "
                      "926 AssertionError\n")
    cp = classpath()
    command = [str(JDK / "java"), "-Xmx4g",
               "-Dcausynth.output.dir=" + str(STATIC),
               "-Dcausynth.target.spec=" + str(target),
               "-Dcausynth.lineage.roots=" + str(LINEAGE),
               "-Dcausynth.loop.default.bound=8", "-cp",
               str(GRAPH) + os.pathsep + cp,
               "edu.uva.liftlab.graphchecker.GraphCheckerMain",
               "-i", str(SCOPE), "-x", cp, "-o", str(HERE / "woven-static")]
    result = logged(command, STATIC / "static.log", 300)
    result.update({"scope_class_files": count,
                   "target_spec": target.read_text().strip(),
                   "artifacts": {name: (STATIC / name).is_file() for name in (
                       "candidate_dataflow_edges.jsonl.gz", "static_scope_map.jsonl",
                       "region_skeletons.jsonl.gz")}})
    (STATIC / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def weave() -> None:
    cp = classpath()
    command = [str(JDK / "java"), "-Xmx3g",
               "-Dcausynth.trace.mode=region-state",
               "-Dcausynth.region.skeletons=" + str(STATIC / "region_skeletons.jsonl.gz"),
               "-Dcausynth.region.preserve.failure-target=true",
               "-cp", str(GRAPH) + os.pathsep + cp,
               "edu.uva.liftlab.graphchecker.GraphCheckerMain",
               "-i", str(SCOPE), "-x", cp, "-o", str(WOVEN)]
    result = logged(command, HERE / "weave.log", 300)
    (HERE / "weave.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def summarize_trace(path: Path) -> dict:
    counts: dict[str, int] = {}
    methods: set[str] = set()
    branches: set[tuple[str, str]] = set()
    target_events = []
    with path.open() as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            event = str(row.get("event") or row.get("kind") or "")
            counts[event] = counts.get(event, 0) + 1
            method = str(row.get("method") or "")
            site = str(row.get("siteId") or row.get("site") or "")
            if event == "METHOD_ENTER" and method:
                methods.add(method)
            if event in ("BRANCH", "BRANCH_DECISION") and site:
                branches.add((site, str(row.get("branchTaken", row.get("outcome")))))
            if ("Journal: void acceptRecovery(" in method
                    or "Journal#acceptRecovery(" in site):
                if event in ("METHOD_ENTER", "BRANCH", "BRANCH_DECISION",
                             "THROW", "REGION_ENTER", "REGION_EXIT"):
                    target_events.append({k: row.get(k) for k in (
                        "event", "kind", "siteId", "method", "branchTaken", "outcome",
                        "regionId", "callId", "nodeId", "requestId", "threadId",
                        "requestApi") if k in row})
    return {"event_counts": counts, "method_coverage": len(methods),
            "branch_outcome_coverage": len(branches),
            "target_events": target_events}


def selected_guard_occurrence(path: Path) -> str:
    calls = {}
    guards = []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if (row.get("event") == "METHOD_ENTER"
                and "Journal: void acceptRecovery(" in str(row.get("method"))):
            calls[row.get("callId")] = row.get("occurrenceAddress", "")
        elif (row.get("event") == "BRANCH"
              and str(row.get("siteId", "")).endswith("#u97")
              and "Journal: void acceptRecovery(" in str(row.get("method"))):
            guards.append(row.get("callId"))
    chosen = {calls.get(call, "") for call in guards}
    chosen.discard("")
    if len(chosen) != 1:
        raise RuntimeError(f"expected one exact HDFS-07 guard occurrence, saw {chosen}")
    return chosen.pop()


def aggregate_existing(out: Path, graph: Path, static_dir: Path = STATIC,
                       test_method: str = TARGET_METHOD) -> dict:
    trace = out / "trace"
    trace_file = trace / "runtime_trace.jsonl"
    if not trace_file.is_file():
        raise FileNotFoundError(trace_file)
    selected = selected_guard_occurrence(trace_file)
    cp = classpath()
    target = ("HDFS-07=" + ",".join(str(static_dir / name) for name in (
        "candidate_dataflow_edges.jsonl.gz", "static_scope_map.jsonl",
        "region_skeletons.jsonl.gz")) + "," + str(trace))
    command = [str(JDK / "java"), "-Xmx3g", "-Dcausynth.loop.default.bound=8",
               "-cp", str(graph) + os.pathsep + cp,
               "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
               "--trace-dir", str(trace), "--test", TARGET_CLASS + "#" + test_method,
               "--target", target, "--target-occurrence", selected,
               "--summary", str(trace / "summary.json")]
    return {"selected_guard_occurrence": selected,
            "aggregate": logged(command, out / "aggregate.log", 240)}


def run(trial: Path | None, ipc: bool, door: bool, rpc: bool, control: bool,
        run_name: str | None, test_method: str) -> None:
    out = HERE / (run_name or ("trial-" + trial.stem + ("-ipc" if ipc else "")
                               if trial else "healthy-ipc-door" if ipc and door
                               else "healthy-ipc" if ipc else "healthy"))
    scratch = out / "scratch"
    trace = out / "trace"
    if scratch.exists():
        shutil.rmtree(scratch)
    if trace.exists():
        shutil.rmtree(trace)
    for directory in (scratch / "data", scratch / "tmp", trace):
        directory.mkdir(parents=True, exist_ok=True)
    cp = classpath()
    test_classes = HERE / "test-classes"
    test_classes.mkdir(exist_ok=True)
    compile_result = logged([
        str(JDK / "javac"), "-cp", str(GRAPH) + os.pathsep + cp,
        "-d", str(test_classes), str(HERE / "OriginalHdfs07Test.java")],
        out / "compile.log", 60)
    if compile_result["exit"] != 0:
        raise RuntimeError("original JUnit adapter did not compile: "
                           + str(out / "compile.log"))
    command = [str(JDK / "java"), "-ea", "-Xmx3g",
               "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
               "-Dorg.slf4j.simpleLogger.defaultLogLevel="
               + ("debug" if rpc else "warn"),
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dcausynth.trace.mode=region-state",
               "-Dcausynth.trace.start.paused=true",
               "-Dcausynth.trace.test=" + TARGET_CLASS + "#" + test_method,
               "-Dhdfs07.test.method=" + test_method,
               "-Dcausynth.junit.record.test.body=true",
               "-Dcausynth.region.preserve.failure-target=true",
               "-Dcausynth.region.skeletons=" + str(STATIC / "region_skeletons.jsonl.gz")]
    if trial:
        command.append("-Dcausynth.fault.trial=" + str(trial.resolve()))
    graph = (HERE / "deps/unit-test-hdfs-c41dc5ee3-273672a0053c.jar"
             if ipc else GRAPH)
    static_dir = (HERE / "static-control-door" if control else
                  HERE / "static-rpc-door" if rpc else
                  HERE / "static-door" if door else STATIC)
    woven = (HERE / "instrumented-control-door" if control else
             HERE / "instrumented-rpc-door" if rpc else
             HERE / "instrumented-door" if door else WOVEN)
    command = [part.replace(str(STATIC / "region_skeletons.jsonl.gz"),
                            str(static_dir / "region_skeletons.jsonl.gz"))
               for part in command]
    prefix = (str(HERE / ("control-overlay" if control else
                          "rpc-overlay" if rpc else "ipc-overlay")),) if ipc else ()
    command.extend(["-cp", os.pathsep.join((str(test_classes), *prefix,
                                             str(woven), str(graph), cp)),
                    "edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner",
                    "OriginalHdfs07Test", "originalJournalRecovery"])
    env = dict(os.environ, JAVA_HOME=str(JDK.parent),
               CAUSYNTH_TRACE_OUTPUT_DIR=str(trace))
    result = {"test": TARGET_CLASS + "#" + test_method,
              "trial": str(trial) if trial else None,
              "ipc_adapter": ipc, "file_io_doors": door,
              "rpc_doors": rpc, "control_scope": control,
              "compile": compile_result,
              "runtime": logged(command, out / "runtime.log", 360,
                                cwd=scratch, env=env)}
    trace_file = trace / "runtime_trace.jsonl"
    if trace_file.is_file():
        result["trace"] = summarize_trace(trace_file)
        (out / "target-events.json").write_text(json.dumps(
            result["trace"].pop("target_events"), indent=2) + "\n")
        try:
            result.update(aggregate_existing(out, graph, static_dir, test_method))
        except RuntimeError as error:
            result["selected_guard_occurrence_error"] = str(error)
    (out / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("static", "weave", "run", "aggregate"))
    parser.add_argument("--trial", type=Path)
    parser.add_argument("--ipc", action="store_true")
    parser.add_argument("--door", action="store_true")
    parser.add_argument("--rpc", action="store_true")
    parser.add_argument("--control", action="store_true")
    parser.add_argument("--run-name")
    parser.add_argument("--test-method", default=TARGET_METHOD)
    options = parser.parse_args()
    if options.step == "static":
        static()
    elif options.step == "weave":
        weave()
    elif options.step == "aggregate":
        out = HERE / (options.run_name or ("healthy-ipc" if options.ipc else "healthy"))
        graph = (HERE / "deps/unit-test-hdfs-c41dc5ee3-273672a0053c.jar"
                 if options.ipc else GRAPH)
        static_dir = (HERE / "static-control-door" if options.control else
                      HERE / "static-rpc-door" if options.rpc else
                      HERE / "static-door" if options.door else STATIC)
        print(json.dumps(aggregate_existing(out, graph, static_dir,
                                            options.test_method), indent=2))
    else:
        run(options.trial, options.ipc, options.door, options.rpc, options.control,
            options.run_name, options.test_method)
