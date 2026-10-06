"""Record HDFS-12 with Hadoop's unmodified parameterized MiniDFSCluster test."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from zipfile import ZipFile

from static_probe import CLASSES, GRAPH, HADOOP as HADOOP_SHARE, jar_for


HERE = Path(__file__).resolve().parent
HADOOP = HADOOP_SHARE.parents[1]
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
STATIC = HERE / "static"
SCOPE = HERE / "scope"
WOVEN = HERE / "instrumented"
OUT = HERE / "run"
TEST_CLASS = "org.apache.hadoop.hdfs.TestEncryptedTransfer"
TEST_METHOD = "testEncryptedReadDefaultAlgorithmCipherSuite"
TEST = f"{TEST_CLASS}#{TEST_METHOD}[0]"
METHOD = "<org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager: byte[] retrievePassword(org.apache.hadoop.hdfs.security.token.block.BlockTokenIdentifier)>"
GUARD = METHOD + "#u25"
TARGET = METHOD + "#u37"


def execute(argv: list[str], log: Path, *, env: dict[str, str] | None = None,
            cwd: Path | None = None, timeout: int = 180) -> dict:
    started = time.monotonic()
    with log.open("w") as output:
        try:
            status = subprocess.run(argv, cwd=cwd, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=timeout,
                                    check=False).returncode
        except subprocess.TimeoutExpired:
            status = 124
    return {"exit": status, "seconds": round(time.monotonic() - started, 3),
            "log": str(log)}


def classpath() -> tuple[str, dict[str, str]]:
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    tools_lib = os.pathsep.join(str(path) for path in sorted(
        (HADOOP / "share/hadoop/tools/lib").glob("*.jar")))
    return os.pathsep.join((
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        hadoop_cp, tools_lib)), env


def extract_scope() -> int:
    count = 0
    for module, stems in CLASSES.items():
        with ZipFile(jar_for(module)) as archive:
            for name in archive.namelist():
                if not name.endswith(".class") or not any(
                    name == stem + ".class" or name.startswith(stem + "$")
                    for stem in stems
                ):
                    continue
                destination = SCOPE / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(name))
                count += 1
    return count


def trace_summary(path: Path) -> dict:
    counts: dict[str, int] = {}
    guards = []
    target_enters = 0
    fatal_exits = []
    fault_points = []
    for raw in path.read_text().splitlines():
        row = json.loads(raw)
        kind = str(row.get("event") or row.get("kind"))
        counts[kind] = counts.get(kind, 0) + 1
        method = str(row.get("method") or "")
        site = str(row.get("siteId") or row.get("site") or "")
        if kind == "METHOD_ENTER" and method == METHOD:
            target_enters += 1
        if kind == "BRANCH" and site == GUARD:
            guards.append({"seq": row.get("seq"),
                           "branchTaken": row.get("branchTaken"),
                           "sourceKey": row.get("sourceKey"),
                           "occurrenceAddress": row.get("occurrenceAddress")})
        if kind == "METHOD_EXIT_THROW" and method == METHOD:
            fatal_exits.append(row.get("seq"))
        if kind == "FAULT_POINT_OBSERVED":
            fault_points.append({k: row.get(k) for k in (
                "seq", "marker", "siteId", "occurrenceAddress", "sourceKey",
                "hitOrdinal")})
    return {"rows": sum(counts.values()), "events": counts,
            "targetMethodEntries": target_enters, "targetGuardEvents": guards,
            "targetMethodThrowExits": fatal_exits,
            "observedFaultPoints": len(fault_points)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-weave", action="store_true")
    parser.add_argument("--static", type=Path, default=STATIC)
    parser.add_argument("--woven", type=Path, default=WOVEN)
    parser.add_argument("--graph-jar", type=Path, default=GRAPH)
    parser.add_argument("--catalog-overlay", type=Path)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--overlay", type=Path,
                        help="isolated Hadoop SASL identity overlay, first on classpath")
    parser.add_argument("--fault-trial", type=Path)
    parser.add_argument("--test-method", default=TEST_METHOD)
    args = parser.parse_args()
    test = f"{TEST_CLASS}#{args.test_method}[0]"
    static = args.static.resolve()
    woven = args.woven.resolve()
    graph_jar = args.graph_jar.resolve()
    output = args.output.resolve()
    output.mkdir(exist_ok=True)
    cp, env = classpath()
    manifest = {"caseId": "HDFS-12", "test": test,
                "workload": "unmodified released Hadoop 3.4.3 JUnit child [0]",
                "graphJar": str(graph_jar),
                "scopeClassFiles": len(list((static.parent / "scope").rglob("*.class")))
                if (static.parent / "scope").is_dir() else extract_scope(),
                "targetGuardSite": GUARD, "targetThrowSite": TARGET}
    if not args.skip_weave:
        woven.mkdir(exist_ok=True)
        command = [str(JDK / "java"), "-Xmx3g",
                   "-Dcausynth.trace.mode=region-state",
                   "-Dcausynth.region.skeletons="
                   + str(static / "region_skeletons.jsonl.gz"),
                   "-cp", str(graph_jar) + os.pathsep + cp,
                   "edu.uva.liftlab.graphchecker.GraphCheckerMain",
                   "-i", str(SCOPE), "-x", cp, "-o", str(woven)]
        manifest["weave"] = execute(command, output / "weave.log", timeout=180)
        if manifest["weave"]["exit"] != 0:
            (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            raise SystemExit("HDFS-12 region-state weave failed")
    trial_name = (args.fault_trial.stem if args.fault_trial else "healthy")
    result_dir = output / trial_name
    scratch = result_dir / "scratch"
    trace = result_dir / "trace"
    shutil.rmtree(result_dir, ignore_errors=True)
    for path in (scratch / "data", scratch / "tmp", trace):
        path.mkdir(parents=True)
    if args.overlay and not args.overlay.is_dir():
        raise SystemExit("HDFS-12 overlay directory does not exist")
    if args.catalog_overlay and not args.catalog_overlay.is_dir():
        raise SystemExit("HDFS-12 catalog overlay directory does not exist")
    runtime_cp = os.pathsep.join(
        ((str(args.overlay.resolve()),) if args.overlay else ())
        + ((str(args.catalog_overlay.resolve()),) if args.catalog_overlay else ())
        + (str(woven), str(graph_jar), cp))
    manifest["overlay"] = str(args.overlay.resolve()) if args.overlay else None
    manifest["catalogOverlay"] = (str(args.catalog_overlay.resolve())
                                  if args.catalog_overlay else None)
    manifest["staticDir"] = str(static)
    manifest["wovenDir"] = str(woven)
    runtime = [str(JDK / "java"), "-ea", "-Xmx3g",
               "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
               "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dcausynth.trace.mode=region-state",
               "-Dcausynth.trace.start.paused=true",
               "-Dcausynth.trace.test=" + test,
               "-Dcausynth.junit.record.test.body=true"]
    if args.fault_trial:
        runtime.append("-Dcausynth.fault.trial=" + str(args.fault_trial.resolve()))
    runtime.extend(["-cp", runtime_cp,
                    "edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner",
                    TEST_CLASS, args.test_method, "0"])
    manifest["runtime"] = execute(
        runtime, result_dir / "runtime.log", cwd=scratch,
        env=dict(env, CAUSYNTH_TRACE_OUTPUT_DIR=str(trace)), timeout=240)
    trace_file = trace / "runtime_trace.jsonl"
    if trace_file.exists():
        manifest["trace"] = trace_summary(trace_file)
    if trace_file.exists() and (trace / "streaming_trace_manifest.json").exists():
        target = "HDFS-12=" + ",".join(map(str, (
            static / "candidate_dataflow_edges.jsonl.gz",
            static / "static_scope_map.jsonl",
            static / "region_skeletons.jsonl.gz", trace)))
        aggregate = [str(JDK / "java"), "-Xmx2g",
                     "-Dcausynth.loop.default.bound=8",
                     "-cp", str(graph_jar) + os.pathsep + cp,
                     "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
            "--trace-dir", str(trace), "--test", test,
                     "--target", target, "--summary", str(trace / "summary.json")]
        manifest["aggregate"] = execute(
            aggregate, result_dir / "aggregate.log", timeout=120)
    (result_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
