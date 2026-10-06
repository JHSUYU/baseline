#!/usr/bin/env python3
"""Run the original three-JournalNode JUnit with a direct epoch-file I/O probe."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil

from run_original import HERE, GRAPH, JDK, TARGET, classpath, logged


def run(name, node=None, ordinal=None, exception="IOException", operation="WRITE_FILE"):
    out = HERE / name
    scratch = out / "scratch"
    trace = out / "trace"
    for directory in (scratch, trace):
        if directory.exists():
            shutil.rmtree(directory)
    for directory in (scratch / "data", scratch / "tmp", trace):
        directory.mkdir(parents=True, exist_ok=True)
    cp = classpath()
    test_classes = HERE / "test-classes"
    test_classes.mkdir(exist_ok=True)
    compile_result = logged([str(JDK / "javac"), "-cp", str(GRAPH) + os.pathsep + cp,
                             "-d", str(test_classes), str(HERE / "OriginalHdfs10Test.java")],
                            out / "compile.log", 60)
    if compile_result["exit"] != 0:
        raise RuntimeError("original JUnit wrapper compile failed")
    command = [str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true", "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
               "-Dtest.build.data=" + str(scratch / "data"), "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dcausynth.trace.mode=discovery", "-Dcausynth.trace.start.paused=true",
               "-Dcausynth.trace.test=" + TARGET + "#testSingleWriter",
               "-Dhdfs10.test.method=testSingleWriter", "-Dcausynth.junit.record.test.body=true",
               "-Dhdfs10.epoch.events=" + str(out / "epoch-events.tsv")]
    if node is not None:
        command += ["-Dhdfs10.epoch.node=" + str(node), "-Dhdfs10.epoch.ordinal=" + str(ordinal),
                    "-Dhdfs10.epoch.exception=" + exception, "-Dhdfs10.epoch.operation=" + operation]
    command += ["-cp", os.pathsep.join((str(test_classes), str(HERE / "epoch-overlay"),
                str(HERE / "control-overlay"), str(HERE / "instrumented-control-door"), str(GRAPH), cp)),
                "edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner", "OriginalHdfs10Test", "originalSingleWriter"]
    env = dict(os.environ, JAVA_HOME=str(JDK.parent), CAUSYNTH_TRACE_OUTPUT_DIR=str(trace))
    runtime = logged(command, out / "runtime.log", 360, cwd=scratch, env=env)
    result = {"test": TARGET + "#testSingleWriter", "epoch_fault":
              {"node": node, "ordinal": ordinal, "exception": exception, "operation": operation} if node is not None else None,
              "compile": compile_result, "runtime": runtime,
              "trace": str(trace / "runtime_trace.jsonl"), "events": str(out / "epoch-events.tsv")}
    (out / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--node", type=int)
    ap.add_argument("--ordinal", type=int)
    ap.add_argument("--exception", choices=("IOException", "FileNotFoundException"), default="IOException")
    ap.add_argument("--operation", choices=("WRITE_FILE", "OPEN"), default="WRITE_FILE")
    args = ap.parse_args()
    run(args.run_name, args.node, args.ordinal, args.exception, args.operation)
