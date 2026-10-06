"""Run one original Hadoop 3.4.3 parameterized HDFS-11 JUnit child.

Uses the isolated JUnitMethodRunner patch, the existing HDFS-11 region-state
weave, and Hadoop's released test jar.  No test workload source is rewritten.
"""

import json
import os
from pathlib import Path
import argparse
import shutil
import subprocess
import time


HERE = Path(__file__).resolve().parent
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
GRAPH = Path("/users/ZhenyuLi/.graphchecker-builds/unit-test-core-0889fb01f-fea8c862bb5c.jar")
WOVEN = HERE / "hdfs11-param-smoke/instrumented"
STATIC = HERE / "hdfs11-param-smoke/static"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
OUT = HERE / "hdfs11-param-smoke"
TEST_CLASS = "org.apache.hadoop.hdfs.TestEncryptedTransfer"
TEST_METHOD = "testEncryptedReadDefaultAlgorithmCipherSuite"
TEST = TEST_CLASS + "#" + TEST_METHOD + "[0]"


def run(argv, log, env=None, cwd=None, timeout=240):
    begin = time.monotonic()
    with log.open("w") as stream:
        try:
            status = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT,
                                    env=env, cwd=cwd, timeout=timeout,
                                    check=False).returncode
        except subprocess.TimeoutExpired:
            status = 124
    return {"exit": status, "seconds": round(time.monotonic() - begin, 3),
            "log": str(log)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expanded", action="store_true",
                        help="use the 22-class HDFS11 closure/fault weave")
    parser.add_argument("--sasl-identity", action="store_true",
                        help="overlay the isolated DataNode SASL request identity adapter")
    parser.add_argument("--server-door", action="store_true",
                        help="use the isolated server-side SASL read door and its static plan")
    parser.add_argument("--fault-trial", type=Path,
                        help="exact GraphChecker exception trial JSON; original JUnit operations remain unchanged")
    options = parser.parse_args()
    graph_scope = (HERE / "hdfs11-server-door/instrumented" if options.server_door
                   else HERE / "hdfs11-param-expanded/instrumented" if options.expanded
                   else WOVEN)
    static = (HERE / "hdfs11-server-door/static" if options.server_door
              else HERE / "hdfs11-static-probe" if options.expanded else STATIC)
    output = (HERE / "hdfs11-server-door/trials" / options.fault_trial.stem
              if options.server_door and options.fault_trial else
              HERE / "hdfs11-server-door/healthy" if options.server_door
              else HERE / "hdfs11-param-identity" if options.sasl_identity
              else HERE / "hdfs11-param-expanded" if options.expanded
              else OUT)
    overlay = (HERE / "hdfs11-server-door/overlay" if options.server_door
               else HERE / "hdfs11-sasl-identity/overlay")
    if options.server_door and not options.sasl_identity:
        raise SystemExit("server door needs the SASL request identity overlay")
    if not GRAPH.is_file() or not graph_scope.is_dir():
        raise SystemExit("build GraphChecker patch and region-state weave first")
    if options.sasl_identity and not (overlay / "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer.class").is_file():
        raise SystemExit("build the SASL identity overlay first")
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    trace = output / "trace"
    shutil.rmtree(scratch, ignore_errors=True)
    shutil.rmtree(trace, ignore_errors=True)
    for path in (scratch / "data", scratch / "tmp", trace):
        path.mkdir(parents=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent),
               CAUSYNTH_TRACE_OUTPUT_DIR=str(trace))
    hadoop_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    tools_lib = os.pathsep.join(str(path) for path in sorted(
        (HADOOP / "share/hadoop/tools/lib").glob("*.jar")))
    test_cp = os.pathsep.join((
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        hadoop_cp, tools_lib))
    cp = os.pathsep.join((str(overlay), str(graph_scope), str(GRAPH), test_cp)
                         if options.sasl_identity else
                         os.pathsep.join((str(graph_scope), str(GRAPH), test_cp)))
    command = [
        str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
        "-Djava.net.preferIPv4Stack=true",
        "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
        "-Dtest.build.data=" + str(scratch / "data"),
        "-Djava.io.tmpdir=" + str(scratch / "tmp"),
        "-Dcausynth.trace.mode=region-state",
        "-Dcausynth.trace.start.paused=true",
        "-Dcausynth.trace.test=" + TEST,
        "-Dcausynth.junit.record.test.body=true",
    ]
    if options.fault_trial:
        command.append("-Dcausynth.fault.trial=" + str(options.fault_trial.resolve()))
    command.extend([
        "-cp", cp,
        "edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner",
        TEST_CLASS, TEST_METHOD, "0",
    ])
    manifest = {"test": TEST, "junitChildIndex": 0,
                "workload": "unmodified released Hadoop 3.4.3 test jar",
                "wovenScope": str(graph_scope),
                "saslIdentityOverlay": str(overlay) if options.sasl_identity else "",
                "runtime": run(command, output / "runtime.log", env, scratch)}
    trace_file = trace / "runtime_trace.jsonl"
    if trace_file.is_file():
        kinds = {}
        target_branches = 0
        for line in trace_file.read_text().splitlines():
            row = json.loads(line)
            kind = str(row.get("event") or row.get("kind"))
            kinds[kind] = kinds.get(kind, 0) + 1
            if ("retrieveDataEncryptionKey(int,byte[])" in str(row.get("method"))
                    and str(row.get("siteId", row.get("site", ""))).endswith("#u8")
                    and kind in ("BRANCH", "BRANCH_DECISION")):
                target_branches += 1
        manifest["trace"] = {"rows": sum(kinds.values()), "events": kinds,
                             "targetGuardBranches": target_branches}
    if (not options.fault_trial and manifest["runtime"]["exit"] == 0
            and trace_file.is_file()):
        target = "HDFS-11=" + ",".join(map(str, (
            static / "candidate_dataflow_edges.jsonl.gz",
            static / "static_scope_map.jsonl",
            static / "region_skeletons.jsonl.gz", trace)))
        aggregator = [
            str(JDK / "java"), "-Xmx2g", "-Dcausynth.loop.default.bound=8",
            "-cp", os.pathsep.join((str(GRAPH), test_cp)),
            "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
            "--trace-dir", str(trace), "--test", TEST,
            "--target", target, "--summary", str(trace / "summary.json"),
        ]
        manifest["aggregate"] = run(aggregator, output / "aggregate.log")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
