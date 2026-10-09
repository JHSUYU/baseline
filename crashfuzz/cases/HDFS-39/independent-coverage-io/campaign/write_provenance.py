#!/usr/bin/env python3
"""Record hashes of the uncommitted raw JaCoCo exec data and release JARs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

CASE = Path(__file__).resolve().parents[1]
STATE = CASE / "campaign/checkpoint.json"
OUTPUT = CASE / "coverage-provenance.json"
REMOTE = "ZhenyuLi@node1"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", REMOTE]


def hash_file(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(),
            "bytes": path.stat().st_size}


def main() -> None:
    state = json.loads(STATE.read_text())
    rows = state["completed"]
    paths = [str(CASE / "healthy/probed/jacoco.exec"),
             str(CASE / "healthy/probed-v2/jacoco.exec")]
    paths.extend(str(CASE / "campaign" / row["trial"] / "jacoco.exec")
                 for row in rows)
    replay_paths = [str(path.parent / "jacoco.exec") for path in
                    sorted((CASE / "replay").glob("*/manifest.json"))]
    script = """import hashlib,json,pathlib,sys
for name in sys.argv[1:]:
    path=pathlib.Path(name)
    if not path.is_file():
        raise FileNotFoundError(path)
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1<<20), b''):
            h.update(block)
    print(json.dumps({'path':str(path),'sha256':h.hexdigest(),'bytes':path.stat().st_size}))
"""
    hadoop = Path.home() / ".baseline-deps/hadoop-3.4.3/share/hadoop"
    jars = [
        hadoop / "hdfs/hadoop-hdfs-3.4.3.jar",
        hadoop / "hdfs/hadoop-hdfs-client-3.4.3.jar",
        hadoop / "hdfs/hadoop-hdfs-3.4.3-tests.jar",
        hadoop / "common/hadoop-common-3.4.3.jar",
        hadoop / "hdfs/sources/hadoop-hdfs-3.4.3-sources.jar",
        hadoop / "hdfs/sources/hadoop-hdfs-3.4.3-test-sources.jar",
        hadoop / "hdfs/sources/hadoop-hdfs-client-3.4.3-sources.jar",
        hadoop / "common/sources/hadoop-common-3.4.3-sources.jar",
        CASE / "deps/jacoco-agent-0.8.15.jar",
        CASE / "deps/jacoco-core-0.8.15.jar",
    ]
    remote_command = shlex.join(
        ["python3", "-c", script, *paths, *replay_paths,
         *(str(path) for path in jars)])
    completed = subprocess.run(SSH + [remote_command],
                               check=True, stdout=subprocess.PIPE, text=True)
    remote_hashes = [json.loads(line) for line in completed.stdout.splitlines()]
    raw = remote_hashes[:len(paths)]
    replay = remote_hashes[len(paths):len(paths) + len(replay_paths)]
    remote_jars = remote_hashes[len(paths) + len(replay_paths):]
    local_jars = [hash_file(path) for path in jars]
    assert len(remote_jars) == len(local_jars)
    assert all(remote["sha256"] == local["sha256"]
               for remote, local in zip(remote_jars, local_jars))
    provenance = {
        "case_id": "HDFS-39", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_jacoco_exec": raw, "replay_jacoco_exec": replay,
        "release_jars": remote_jars,
        "generation_command": (
            "java -ea -javaagent:<case>/deps/jacoco-agent-0.8.15.jar="
            "destfile=<trial>/jacoco.exec,append=false -cp "
            "<case>/system-test/probe-classes:<released Hadoop classpath> "
            "OriginalHdfs39Test testMultipleAppends"),
        "coverage_analysis_command": (
            "python3 <case>/system-test/run_coverage.py --exec "
            "<trial>/jacoco.exec --output <trial>/coverage.tsv"),
        "instrumentation": (
            "case-local pristine-source overrides; Client.getRpcResponse in "
            "trials 1-23, with additional Client.sendRpcRequest from trial 24; "
            "no graph artifacts"),
        "committed_coverage_archive": "coverage-evidence.tar.gz",
    }
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    temporary.replace(OUTPUT)
    print(json.dumps({"raw_exec_count": len(raw),
                      "replay_exec_count": len(replay),
                      "release_jars": len(jars),
                      "output": str(OUTPUT)}))


if __name__ == "__main__":
    main()
