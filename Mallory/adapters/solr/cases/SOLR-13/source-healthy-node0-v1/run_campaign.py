#!/usr/bin/env python3
"""Pinned, GO-gated, one-trial SOLR-13 healthy source admission on node0."""

from __future__ import annotations

import argparse
import copy
import fcntl
import getpass
import hashlib
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
ORIGINAL = HERE.parent / "source-admission-v1"
RELEASE = ROOT / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
OUT = ROOT / "data/mallory/solr13_source_healthy_node0_v1/healthy"
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def preflight() -> dict:
    subprocess.run([sys.executable, str(ORIGINAL / "preflight.py")], check=True,
                   stdout=subprocess.DEVNULL)
    config_path = HERE / "config-healthy-node0.json"
    config = read(config_path)
    expected = copy.deepcopy(read(ORIGINAL / "healthy-node2-lane3.json"))
    expected["revision"] = "SOLR-13-source-healthy-node0-v1"
    expected["admission"].update({
        "host": "node0.baseline.silentfailure-pg0.utah.cloudlab.us",
        "lane": "solr-node0-v1", "output": str(OUT),
        "scope": "healthy_only_no_faults_no_full_promotion",
        "required_fresh_evidence": [
            "unchanged passing MiniSolrCloudCluster JUnit and exact @348 target check on a named actor",
            "named Overseer-side @2259 BadVersionException door before target",
            "report observed event-time graph paths separately; do not infer a path from temporal proximity",
        ],
    })
    if config != expected:
        raise ValueError("node0 config differs from pinned node2 source admission")
    if not Path(campaign.__file__).resolve().is_relative_to(RELEASE):
        raise ValueError("source-admission campaign core was not loaded from pinned release")
    campaign.validate_config(config)
    manifest = read(HERE / "sha-manifest.json")
    if (manifest.get("case_id") != "SOLR-13" or
            manifest.get("original_manifest_sha256") != sha(ORIGINAL / "manifest.json")):
        raise ValueError("source admission manifest changed")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local file changed: {name}")
    request = read(HERE / "admission-request.json")
    if (request.get("go") is not False or request.get("execution_status") != "not_launched"
            or request.get("host") != "node0" or request.get("case_id") != "SOLR-13"
            or request.get("mode") != "healthy" or request.get("config_sha256") != sha(config_path)
            or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("intended_output") != str(OUT)):
        raise ValueError("node0 admission request changed")
    return {"config_sha256": sha(config_path), "runner_sha256": sha(Path(__file__)),
            "manifest_sha256": sha(HERE / "sha-manifest.json"),
            "original_manifest_sha256": sha(ORIGINAL / "manifest.json"),
            "intended_output": str(OUT)}


def check_go(path: Path, config_sha: str) -> str:
    if path.resolve() != HERE / "admission-healthy-node0.json":
        raise ValueError("case-local dispatch GO receipt required")
    receipt = read(path)
    if (receipt.get("go") is not True or receipt.get("host") != "node0"
            or receipt.get("case_id") != "SOLR-13" or receipt.get("mode") != "healthy"
            or receipt.get("config_sha256") != config_sha
            or receipt.get("runner_sha256") != sha(Path(__file__))
            or receipt.get("intended_output") != str(OUT)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("healthy",), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", "case_id": "SOLR-13", "mode": "healthy",
                          "go": False, **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.admission_receipt,
                                             metadata["config_sha256"])
    if socket.gethostname().split(".", 1)[0] != "node0" or OUT.exists():
        raise ValueError("node0 and a fresh healthy output are required")
    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    locks = []
    try:
        for name in ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_root / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks.append(handle)
        if OUT.exists():
            raise ValueError("healthy output appeared while acquiring locks")
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("insufficient free disk for isolated Solr JUnit")
        available_kib = next(int(row.split()[1]) for row in
                             Path("/proc/meminfo").read_text().splitlines()
                             if row.startswith("MemAvailable:"))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available RAM")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"] for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node0")
        print(json.dumps({"preflight": "passed", "case_id": "SOLR-13",
                          "mode": "healthy", **metadata}, sort_keys=True), flush=True)
        state = campaign.run(HERE / "config-healthy-node0.json", OUT,
                             calibration_only=True)
    finally:
        for handle in reversed(locks):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return subprocess.run([sys.executable, str(HERE / "audit_healthy.py"), str(OUT)],
                          check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
