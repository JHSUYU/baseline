#!/usr/bin/env python3
"""Run the original encrypted Balancer JUnit with HDFS-55 target/IO probes."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
CONTROL = HERE.parents[1] / "known-bug-controls/HDFS-17899"
BUILD = HERE / "build"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
SOURCE_RESOURCES = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
MOCKITO = Path("/users/ZhenyuLi/.m2/repository/org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar")
BYTE_BUDDY = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar")
BYTE_BUDDY_AGENT = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar")
OBJENESIS = Path("/users/ZhenyuLi/.m2/repository/org/objenesis/objenesis/3.3/objenesis-3.3.jar")
TEST_CLASS = "org.apache.hadoop.hdfs.server.balancer.TestBalancerWithEncryptedTransfer"
TEST_METHOD = "testEncryptedBalancer0"
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
ASM_ROOT = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM_ROOT / name / "9.6" / (name + "-9.6.jar")
            for name in ("asm", "asm-tree", "asm-commons")]
COVERAGE_TOOL = HERE.parents[1] / "cases/HDFS-50/probe/build/classes"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--test-overlay", type=Path,
                        help="case-local compilation of original JUnit with cluster configuration")
    parser.add_argument("--inject", action="store_true")
    parser.add_argument("--first-attempt", type=int, default=1)
    parser.add_argument("--max-faults", type=int, default=24)
    parser.add_argument("--plan", type=Path,
                        help="exact outbound SASL ordinal plan; separate from stateful policy")
    parser.add_argument("--runtime-prefix-faults", type=int, default=0,
                        help="inject first N runtime-ordered cached-key SASL attempts")
    parser.add_argument("--dn-reject-cached-key", type=int, default=0,
                        help="reject a runtime-identified cached Balancer key on the DN handshake")
    parser.add_argument("--dn-reject-persistent", action="store_true",
                        help="one persistent rejected-DEK state; cap repeated responses at 1000")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if (args.runtime_prefix_faults < 0 or args.dn_reject_cached_key < 0 or
            (args.dn_reject_persistent and args.dn_reject_cached_key) or
            sum(bool(item) for item in (args.plan, args.runtime_prefix_faults,
                                        args.dn_reject_cached_key,
                                        args.dn_reject_persistent)) > 1 or
            ((args.runtime_prefix_faults or args.dn_reject_cached_key or
              args.dn_reject_persistent) and not args.inject)):
        parser.error("one fault policy at a time; prefix and DN rejection need --inject")
    dn_rejection_limit = 1000 if args.dn_reject_persistent else args.dn_reject_cached_key
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for leaf in ("data", "tmp", "logs"):
        (scratch / leaf).mkdir(parents=True)
    BUILD.mkdir(exist_ok=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"),
        "classpath", "--glob"], env=env, text=True).strip()
    tool_jars = [TESTS, COMMON_TESTS, JUNIT, MOCKITO,
                 BYTE_BUDDY, BYTE_BUDDY_AGENT, OBJENESIS]
    tool_jars += sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar"))
    cp = os.pathsep.join([*(str(p) for p in tool_jars), hadoop_cp])
    wrapper = (HERE / "campaign/RunOneJUnitExit.java"
               if args.plan or args.runtime_prefix_faults or dn_rejection_limit
               else CONTROL / "RunOneJUnit.java")
    subprocess.run([str(JDK / "javac"), "-cp", cp, "-d", str(BUILD),
        str(wrapper)], check=True)
    if args.overlay and not args.overlay.is_dir():
        raise FileNotFoundError(args.overlay)
    if args.test_overlay and not args.test_overlay.is_dir():
        raise FileNotFoundError(args.test_overlay)
    run_cp = os.pathsep.join([*(str(p.resolve()) for p in
        ([args.test_overlay] if args.test_overlay else []) +
        ([args.overlay] if args.overlay else [])),
        str(SOURCE_RESOURCES), str(BUILD), cp])
    command = [str(JDK / "java"), "-ea", "-Xmx3g",
        "-javaagent:" + str(JACOCO) + "=destfile=" + str(output / "jacoco.exec") + ",append=false",
        "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
        "-Dtest.build.data=" + str(scratch / "data"),
        "-Djava.io.tmpdir=" + str(scratch / "tmp"),
        "-Dhadoop.log.dir=" + str(scratch / "logs"),
        "-Dhdfs17899.inject=" + str(args.inject).lower(),
        "-Dhdfs55.firstAttempt=" + str(args.first_attempt),
        "-Dhdfs55.maxFaults=" + str(args.max_faults),
        "-Dhdfs55.runtimePrefixFaults=" + str(args.runtime_prefix_faults),
        "-Dhdfs55.dnRejectCachedKey=" + str(dn_rejection_limit),
        *(["-Dhdfs55.plan=" + str(args.plan.resolve())] if args.plan else []),
        "-cp", run_cp, "RunOneJUnitExit" if args.plan or args.runtime_prefix_faults
        or dn_rejection_limit
        else "RunOneJUnit",
        TEST_CLASS, TEST_METHOD]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            rc = subprocess.run(command, cwd=scratch, env=env,
                stdout=log, stderr=subprocess.STDOUT,
                timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    manifest = {"case_id": "HDFS-55", "known_issue": "HDFS-17899", "source_version": "3.4.3",
        "test": TEST_CLASS + "#" + TEST_METHOD,
        "returncode": rc, "elapsed_seconds": round(time.monotonic()-started,3),
        "overlay": str(args.overlay.resolve()) if args.overlay else None,
        "test_overlay": str(args.test_overlay.resolve()) if args.test_overlay else None,
        "fault_injection_enabled": args.inject,
        "first_attempt": args.first_attempt,
        "max_faults": args.max_faults,
        "exact_plan": str(args.plan.resolve()) if args.plan else None,
        "planned_exact_faults": (sum(1 for line in args.plan.read_text().splitlines()
                                     if line.strip()) if args.plan else None),
        "runtime_prefix_faults": args.runtime_prefix_faults,
        "dn_reject_cached_key": args.dn_reject_cached_key,
        "dn_reject_persistent": args.dn_reject_persistent,
        "dn_rejection_safety_cap": dn_rejection_limit if args.dn_reject_persistent else None,
        "logical_faults_planned": 1 if args.dn_reject_persistent else None,
        "junit_wrapper": "RunOneJUnitExit" if args.plan or args.runtime_prefix_faults
        or dn_rejection_limit
        else "RunOneJUnit",
        "log": str(output / "junit.log"),
        "coverage": str(output / "jacoco.exec"), "graph_used": False,
        "container_used": False}
    execution = output / "jacoco.exec"
    if execution.is_file() and execution.stat().st_size:
        covered = output / "covered_probes.txt"
        with covered.open("w") as stream:
            subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join(
                [str(COVERAGE_TOOL), str(JACOCO_CORE),
                 *(str(path) for path in ASM_JARS)]),
                "CoverageHdfs50", str(execution),
                str(args.overlay.resolve()) if args.overlay else str(BUILD),
                str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"),
                str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"),
                str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar")],
                stdout=stream, check=True)
        for kind in ("probes", "methods", "branch_counts", "lines"):
            path = (covered if kind == "probes" else
                    output / f"covered_{kind}.txt")
            manifest[f"covered_{kind}"] = sum(1 for _ in path.open())
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(manifest))
    if rc: raise SystemExit(rc)


if __name__ == "__main__":
    main()
