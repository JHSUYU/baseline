#!/usr/bin/env python3
"""Compile the tagged encrypted Balancer JUnit with a bounded test adaptation."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
TEST = (SOURCE / "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/"
        "hadoop/hdfs/server/balancer/TestBalancerWithEncryptedTransfer.java")
BUILD = HERE / "build"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("serial", "timeout-only", "one-node"), default="serial")
    parser.add_argument("--timeout-ms", type=int, default=180000)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("hdfs55_run_control", CASE / "run_control.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = TEST.read_text()
    original = "    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);"
    replacement = original + ("\n" + (
        "    conf.setInt(DFSConfigKeys.DFS_BALANCER_MOVERTHREADS_KEY, 1);\n"
        "    conf.setInt(DFSConfigKeys.DFS_DATANODE_BALANCE_MAX_NUM_CONCURRENT_MOVES_KEY, 1);")
        if args.variant in ("serial", "one-node") else "")
    test_header = "@Test(timeout=60000)\n  public void testEncryptedBalancer0()"
    adapted_header = ("@Test(timeout=" + str(args.timeout_ms)
                      + ")\n  public void testEncryptedBalancer0()")
    if source.count(original) != 1 or source.count(test_header) != 1:
        raise RuntimeError("tagged TestBalancerWithEncryptedTransfer setup changed")
    method_call = "    new TestBalancer().testBalancer0Internal(conf);"
    if source.count(method_call) != 1:
        raise RuntimeError("tagged TestBalancerWithEncryptedTransfer workload changed")
    adapted = source.replace(original, replacement).replace(test_header, adapted_header)
    if args.variant == "one-node":
        adapted = adapted.replace(method_call,
                                  "    new TestBalancer().integrationTest(conf);")
    generated = (BUILD / f"{args.variant}-fixture-src/org/apache/hadoop/hdfs/server/balancer/"
                 "TestBalancerWithEncryptedTransfer.java")
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(adapted)
    output = BUILD / f"{args.variant}-test-overlay"
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, JAVA_HOME=str(module.JDK.parent))
    hadoop_cp = subprocess.check_output([str(module.HADOOP / "bin/hadoop"),
        "classpath", "--glob"], env=env, text=True).strip()
    cp = os.pathsep.join([str(module.TESTS), str(module.COMMON_TESTS),
                          str(module.JUNIT), hadoop_cp])
    subprocess.run([str(module.JDK / "javac"), "-proc:none", "-cp", cp,
                    "-d", str(output), str(generated)], check=True)
    (BUILD / f"{args.variant}-fixture.json").write_text(json.dumps({
        "source_version": "3.4.3", "source_file": str(TEST),
        "test": "TestBalancerWithEncryptedTransfer#testEncryptedBalancer0",
        "adaptation": ({"dfs.balancer.moverThreads": 1,
                        "dfs.datanode.balance.max.concurrent.moves": 1,
                        "test_timeout_ms": args.timeout_ms,
                        "original_test_balancer_helper": "integrationTest" if args.variant == "one-node" else "testBalancer0Internal"}
                       if args.variant in ("serial", "one-node")
                       else {"test_timeout_ms": args.timeout_ms}),
        "test_overlay": str(output)}, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
