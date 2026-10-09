#!/usr/bin/env python3
"""Index uncommitted raw JaCoCo exec files by path and SHA-256."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


CASE = Path(__file__).resolve().parent
CASE_ID = CASE.name
HOST = {"HDFS-20": "node1", "HDFS-21": "node2"}[CASE_ID]
REMOTE = f"ZhenyuLi@{HOST}"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", REMOTE]
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
PHASES = ({
    "HDFS-20": [
        ("independent-coverage-io", "campaign", "healthy/instrumented"),
        ("independent-ha", "campaign", "healthy/instrumented"),
        ("independent-ha-hot", "campaign-v2", "healthy/identity-fixed"),
    ],
    "HDFS-21": [
        ("independent-coverage-io", "campaign", "healthy/instrumented"),
    ],
})[CASE_ID]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main() -> None:
    entries = []
    for phase_name, campaign_name, healthy_name in PHASES:
        phase = CASE / phase_name
        state = json.loads((phase / campaign_name / "checkpoint.json").read_text())
        names = [healthy_name] + [
            f"{campaign_name}/{row['trial']}" for row in state["completed"]]
        for name in names:
            output = phase / name
            manifest = json.loads((output / "manifest.json").read_text())
            if not manifest.get("coverage"):
                raise RuntimeError(f"missing coverage run: {output}")
            execution = Path(manifest["jacoco_exec"])
            if not execution.is_absolute() or execution != output / "jacoco.exec":
                raise RuntimeError(f"unexpected raw execution path: {execution}")
            coverage = output / "coverage.tsv"
            if not coverage.is_file():
                raise RuntimeError(f"coverage feedback absent: {coverage}")
            runner = phase / "system-test/run_original.py"
            parser = phase / "system-test/run_coverage.py"
            method = manifest["test"].rsplit("#", 1)[1]
            runner_cmd = ["python3", str(runner), "--method", method,
                          "--name", name, "--probe", "--coverage"]
            if manifest.get("fault_plan"):
                runner_cmd += ["--plan", manifest["fault_plan"]]
            if manifest.get("timeout_seconds"):
                runner_cmd += ["--timeout-seconds",
                               str(manifest["timeout_seconds"])]
            entries.append({
                "phase": phase_name, "run": name, "host": HOST,
                "raw_exec_absolute_path": str(execution),
                "manifest": str(output / "manifest.json"),
                "manifest_sha256": sha(output / "manifest.json"),
                "coverage_tsv": str(coverage),
                "coverage_tsv_sha256": sha(coverage),
                "runner_command": runner_cmd,
                "coverage_parser_command": [
                    "python3", str(parser), "--exec", str(execution),
                    "--output", str(coverage)],
                "runner_source_sha256": sha(runner),
                "coverage_parser_source_sha256": sha(parser),
                "source_provenance": str(phase / "source-provenance.json"),
            })
    paths = [entry["raw_exec_absolute_path"] for entry in entries]
    if len(paths) != len(set(paths)):
        raise RuntimeError("duplicate raw JaCoCo path")
    hashed = subprocess.run(SSH + ["sha256sum"] + paths, check=True,
                            capture_output=True, text=True).stdout.splitlines()
    remote_hashes = {}
    for row in hashed:
        digest, path = row.split(maxsplit=1)
        remote_hashes[path] = digest
    if set(remote_hashes) != set(paths):
        raise RuntimeError("remote JaCoCo files do not match local manifests")
    for entry in entries:
        entry["raw_exec_sha256"] = remote_hashes[entry["raw_exec_absolute_path"]]
    hdfs = HADOOP / "share/hadoop/hdfs"
    class_jars = [hdfs / "hadoop-hdfs-3.4.3.jar",
                  hdfs / "hadoop-hdfs-client-3.4.3.jar"]
    source_jars = sorted({Path(record["source_jar"])
                          for phase_name, _, _ in PHASES
                          for record in json.loads((CASE / phase_name /
                              "source-provenance.json").read_text())["files"]})
    result = {
        "case_id": CASE_ID,
        "raw_exec_files": len(entries),
        "note": "Raw jacoco.exec files remain on the named cluster-test host; "
                "committed coverage TSV archives and this digest index permit "
                "feedback review without committing duplicate raw binaries.",
        "release_class_jars": [{"path": str(path), "sha256": sha(path)}
                               for path in class_jars],
        "release_source_jars": [{"path": str(path), "sha256": sha(path)}
                                for path in source_jars],
        "jacoco_agents": [{"phase": phase_name,
                           "path": str(CASE / phase_name / "deps/jacoco-agent-0.8.15.jar"),
                           "sha256": sha(CASE / phase_name /
                                         "deps/jacoco-agent-0.8.15.jar")}
                          for phase_name, _, _ in PHASES],
        "entries": entries,
    }
    output = CASE / "coverage-provenance.json"
    atomic_json(output, result)
    print(json.dumps({"case_id": CASE_ID, "raw_exec_files": len(entries),
                      "output": str(output)}))


if __name__ == "__main__":
    main()
