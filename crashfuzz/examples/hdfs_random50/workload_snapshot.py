"""Create snapshot references, then clean them through rename and deletion."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(TEN))
import workload  # noqa: E402


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    rows = []

    def run(name, subcommand, args):
        result = workload.hdfs(subcommand, args, run_dir)
        result["name"] = name
        rows.append(result)
        (run_dir / "snapshot-steps.json").write_text(
            json.dumps(rows, indent=2) + "\n")

    run("mkdir-snapshot-directories", "dfs", [
        "-mkdir", "-p", "/adhoc-snap/source", "/adhoc-snap/dest"])
    run("put-snapshot-file", "dfs", [
        "-put", "/work/input.bin", "/adhoc-snap/source/file"])
    run("put-rename-probe", "dfs", [
        "-put", "/work/input.bin", "/adhoc-snap/source/rename-probe"])
    run("mkdir-directory-probe", "dfs", [
        "-mkdir", "-p", "/adhoc-snap/source/dir-probe"])
    run("put-directory-probe", "dfs", [
        "-put", "/work/input.bin", "/adhoc-snap/source/dir-probe/file"])
    run("allow-source-snapshot", "dfsadmin", [
        "-allowSnapshot", "/adhoc-snap/source"])
    run("allow-sibling-snapshot", "dfsadmin", [
        "-allowSnapshot", "/adhoc-snap/dest"])
    run("create-source-snapshot", "dfs", [
        "-createSnapshot", "/adhoc-snap/source", "before"])
    run("append-after-snapshot", "dfs", [
        "-appendToFile", "/work/input.bin", "/adhoc-snap/source/file"])
    run("overwrite-after-snapshot", "dfs", [
        "-put", "-f", "/work/input.bin", "/adhoc-snap/source/file"])
    run("move-across-snapshot", "dfs", [
        "-mv", "/adhoc-snap/source/rename-probe",
        "/adhoc-snap/dest/rename-probe"])
    run("move-directory-across-snapshot", "dfs", [
        "-mv", "/adhoc-snap/source/dir-probe",
        "/adhoc-snap/dest/dir-probe"])
    # WithName.assertReferences is checked by the offline fsimage validator,
    # so save an image while the cross-snapshot reference still exists.
    run("enter-safemode", "dfsadmin", ["-safemode", "enter"])
    run("save-namespace", "dfsadmin", ["-saveNamespace"])
    run("leave-safemode", "dfsadmin", ["-safemode", "leave"])
    listed = subprocess.run(workload.DOCKER + [
        "exec", "adhocfuzz-hdfs-key-nn", "ls", "-1", "/data/nn/current"],
        capture_output=True, text=True, timeout=30, check=True)
    images = sorted(name for name in listed.stdout.splitlines()
                    if re.fullmatch(r"fsimage_\d+", name))
    if not images:
        raise RuntimeError("saveNamespace produced no fsimage")
    # The fsimage lives in the NameNode's /data mount, not in the short-lived
    # client container used by workload.hdfs().
    validated = subprocess.run(workload.DOCKER + [
        "exec", "adhocfuzz-hdfs-key-nn", "/opt/hadoop/bin/hdfs",
        "fsImageValidation", "/data/nn/current/" + images[-1]],
        capture_output=True, text=True, timeout=120)
    rows.append({"name": "validate-snapshot-image",
                 "returncode": validated.returncode,
                 "stdout": validated.stdout[-3000:],
                 "stderr": validated.stderr[-3000:]})
    (run_dir / "snapshot-steps.json").write_text(
        json.dumps(rows, indent=2) + "\n")
    run("remove-destination-file", "dfs", [
        "-rm", "-skipTrash", "/adhoc-snap/dest/rename-probe"])
    run("remove-destination-directory", "dfs", [
        "-rm", "-r", "-skipTrash", "/adhoc-snap/dest/dir-probe"])
    run("delete-source-snapshot", "dfs", [
        "-deleteSnapshot", "/adhoc-snap/source", "before"])
    run("disallow-source-snapshot", "dfsadmin", [
        "-disallowSnapshot", "/adhoc-snap/source"])
    run("disallow-sibling-snapshot", "dfsadmin", [
        "-disallowSnapshot", "/adhoc-snap/dest"])
    run("remove-snapshot-dirs", "dfs", [
        "-rm", "-r", "-skipTrash", "/adhoc-snap"])


if __name__ == "__main__":
    main()
