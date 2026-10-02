"""Broad healthy workload for ten randomly selected HDFS checks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hdfs_key"))
from prepare import AGENT, DOCKER, HADOOP, IMAGE, JAVA_HOME, JAVA_OPTIONS, NETWORK, PROPERTIES  # noqa: E402


def hdfs(subcommand: str, args: list[str], run_dir: Path) -> dict:
    command = DOCKER + [
        "run", "--rm", "--network", NETWORK,
        "--add-host=host.docker.internal:host-gateway",
        "-e", "JAVA_HOME=" + JAVA_HOME,
        "-e", "HADOOP_HOME=/opt/hadoop",
        "-e", "HADOOP_CONF_DIR=/conf",
        "-e", "HADOOP_OPTS=" + JAVA_OPTIONS,
        "-e", "ADHOCFUZZ_NODE_ID=client",
        "-e", "ADHOCFUZZ_TRACE_DIR=/traces",
        "-e", "ADHOCFUZZ_CONTROLLER_HOST=" +
              os.environ["ADHOCFUZZ_CONTROLLER_HOST"],
        "-e", "ADHOCFUZZ_CONTROLLER_PORT=" +
              os.environ["ADHOCFUZZ_CONTROLLER_PORT"],
        "-v", str(HADOOP) + ":/opt/hadoop:ro",
        "-v", str(run_dir / "conf") + ":/conf:ro",
        "-v", str(run_dir / "traces") + ":/traces",
        "-v", str(run_dir) + ":/work",
        "-v", str(AGENT) + ":/agent.jar:ro",
        "-v", str(PROPERTIES) + ":/agent.properties:ro",
        "--entrypoint", "/opt/hadoop/bin/hdfs", IMAGE, subcommand,
    ] + args
    result = subprocess.run(command, text=True, capture_output=True,
                            timeout=120)
    return {"subcommand": subcommand, "args": args,
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]}


def main() -> None:
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    source = run_dir / "input.bin"
    source.write_bytes(bytes(range(256)) * 32768)
    observations = []

    def run(name: str, subcommand: str, args: list[str], required=False) -> None:
        result = hdfs(subcommand, args, run_dir)
        result["name"] = name
        observations.append(result)
        (run_dir / "workload-steps.json").write_text(
            json.dumps(observations, indent=2) + "\n")
        if required and result["returncode"]:
            raise RuntimeError(name + " failed: " + result["stderr"])

    run("mkdir", "dfs", ["-mkdir", "-p", "/adhoc-random"], True)
    run("put", "dfs", ["-put", "-f", "/work/input.bin",
                       "/adhoc-random/blob"], True)
    run("get", "dfs", ["-get", "-f", "/adhoc-random/blob",
                       "/work/output.bin"], True)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    observed = hashlib.sha256((run_dir / "output.bin").read_bytes()).hexdigest()
    if expected != observed:
        raise RuntimeError("readback SHA-256 mismatch")
    (run_dir / "hashes.txt").write_text(expected + "\n" + observed + "\n")

    # Optional operations probe ACL, block metadata, caching, and storage
    # statistics. Their exit codes are retained; each target can be judged
    # against whether its relevant operation actually succeeded.
    run("set-acl", "dfs", ["-setfacl", "-m", "user:adhoc:rwx",
                           "/adhoc-random"])
    run("remove-acl", "dfs", ["-setfacl", "-b", "/adhoc-random"])
    run("setrep-four", "dfs", ["-setrep", "4", "/adhoc-random/blob"])
    time.sleep(2)
    run("metasave", "dfsadmin", ["-metasave", "adhoc-random.meta"])
    run("datanode-report", "dfsadmin", ["-report"])
    run("add-cache-pool", "cacheadmin", ["-addPool", "adhoc-random-pool"])
    run("add-cache-directive", "cacheadmin", [
        "-addDirective", "-path", "/adhoc-random/blob", "-pool",
        "adhoc-random-pool", "-replication", "1"])
    time.sleep(2)
    print("healthy HDFS workload SHA-256=" + expected)


if __name__ == "__main__":
    main()
