"""Exercise quota, xattr, concat, snapshot, and edit-log replay paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(TEN))
import workload  # noqa: E402


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    observations = []

    def run(name, subcommand, args):
        result = workload.hdfs(subcommand, args, run_dir)
        result["name"] = name
        observations.append(result)
        (run_dir / "rich-steps.json").write_text(
            json.dumps(observations, indent=2) + "\n")

    run("set-storage-policy", "storagepolicies", [
        "-setStoragePolicy", "-path", "/adhoc-random/blob", "-policy", "HOT"])
    run("setrep-two", "dfs", ["-setrep", "2", "/adhoc-random/blob"])
    run("setrep-three", "dfs", ["-setrep", "3", "/adhoc-random/blob"])
    run("set-xattr", "dfs", [
        "-setfattr", "-n", "user.adhoc", "-v", "value", "/adhoc-random/blob"])
    run("get-xattr", "dfs", [
        "-getfattr", "-n", "user.adhoc", "/adhoc-random/blob"])
    run("put-concat-target", "dfs", [
        "-put", "/work/input.bin", "/adhoc-random/concat-target"])
    run("put-concat-source", "dfs", [
        "-put", "/work/input.bin", "/adhoc-random/concat-source"])
    run("put-concat-source-two", "dfs", [
        "-put", "/work/input.bin", "/adhoc-random/concat-source-two"])
    run("concat", "dfs", [
        "-concat", "/adhoc-random/concat-target",
        "/adhoc-random/concat-source",
        "/adhoc-random/concat-source-two"])
    run("allow-snapshot", "dfsadmin", ["-allowSnapshot", "/adhoc-random"])
    run("create-snapshot", "dfs", [
        "-createSnapshot", "/adhoc-random", "before"])
    run("put-snapshot-version", "dfs", [
        "-put", "/work/input.bin", "/adhoc-random/snapshot-file"])
    run("rename-snapshot", "dfs", [
        "-renameSnapshot", "/adhoc-random", "before", "after"])
    run("delete-snapshot", "dfs", [
        "-deleteSnapshot", "/adhoc-random", "after"])
    run("disallow-snapshot", "dfsadmin", [
        "-disallowSnapshot", "/adhoc-random"])
    run("roll-edits", "dfsadmin", ["-rollEdits"])
    restarted = subprocess.run(workload.DOCKER + [
        "restart", "--time", "10", "adhocfuzz-hdfs-key-nn"],
        capture_output=True, text=True, timeout=45)
    observations.append({"name": "restart-namenode",
                         "returncode": restarted.returncode,
                         "stderr": restarted.stderr[-1000:]})
    if restarted.returncode:
        raise RuntimeError("NameNode restart failed: " + restarted.stderr)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = workload.hdfs("dfsadmin", ["-safemode", "get"], run_dir)
        if result["returncode"] == 0:
            observations.append({"name": "namenode-ready", "returncode": 0})
            break
        time.sleep(2)
    else:
        raise RuntimeError("NameNode restart did not complete")
    (run_dir / "rich-steps.json").write_text(
        json.dumps(observations, indent=2) + "\n")


if __name__ == "__main__":
    main()
