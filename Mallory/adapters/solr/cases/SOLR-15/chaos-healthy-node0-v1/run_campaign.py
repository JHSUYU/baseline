#!/usr/bin/env python3
"""Pinned, GO-gated, one-trial SOLR-15 healthy observation on node0."""

from __future__ import annotations

import argparse
import copy
import fcntl
import getpass
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
ORIGINAL = HERE.parent / "chaos-target-discovery-v1"
OUT = ROOT / "data/mallory/solr15_chaos_healthy_node0_v1/healthy"
sys.path.insert(0, str(ORIGINAL.parents[2]))
from fault_discovery_runner import campaign, preflight as original_preflight, read, sha  # noqa: E402


def preflight() -> dict:
    original_preflight(ORIGINAL, "healthy")
    config_path = HERE / "config-healthy-node0.json"
    config = read(config_path)
    expected = copy.deepcopy(read(ORIGINAL / "config-healthy-node2.json"))
    expected["budget"] = {"trials": 1, "seconds": 600,
                          "max_faults_per_trial": 1, "trial_timeout_seconds": 480}
    expected["target_absent_bootstrap"]["max_trials"] = 1
    expected["target_absent_bootstrap"]["max_faults_per_trial"] = 1
    expected["revision"] = "SOLR-15-chaos-healthy-node0-v1"
    if config != expected:
        raise ValueError("node0 config differs from the pinned chaos JUnit healthy seed")
    campaign.validate_config(config)
    manifest = read(HERE / "sha-manifest.json")
    if (manifest["case_id"] != "SOLR-15" or
            manifest["original_package_manifest_sha256"] !=
            sha(ORIGINAL / "sha-manifest.json")):
        raise ValueError("wrong package manifest")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local file changed: {name}")
    request = read(HERE / "admission-request.json")
    if (request.get("go") is not False or request.get("execution_status") != "not_launched"
            or request.get("host") != "node0" or request.get("case_id") != "SOLR-15"
            or request.get("mode") != "healthy" or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("config_sha256") != sha(config_path)
            or request.get("intended_output") != str(OUT)):
        raise ValueError("node0 admission request changed")
    source = Path(config["cwd"])
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                       text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"],
                                    text=True).strip()
    if revision != config["mapping"]["source_git_revision"] or dirty:
        raise ValueError("Solr source revision or cleanliness changed")
    if config["cluster_test"] != "org.apache.solr.cloud.api.collections.ShardSplitTest#testSplitWithChaosMonkey":
        raise ValueError("wrong original cluster JUnit")
    return {"config_sha256": sha(config_path), "runner_sha256": sha(Path(__file__)),
            "manifest_sha256": sha(HERE / "sha-manifest.json"),
            "source_revision": revision, "intended_output": str(OUT)}


def check_go(path: Path, config_sha: str) -> str:
    if path.resolve() != HERE / "admission-healthy-node0.json":
        raise ValueError("case-local dispatch GO receipt required")
    receipt = read(path)
    if (receipt.get("go") is not True or receipt.get("host") != "node0"
            or receipt.get("case_id") != "SOLR-15" or receipt.get("mode") != "healthy"
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
        print(json.dumps({"preflight": "passed", "case_id": "SOLR-15", "mode": "healthy",
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
        print(json.dumps({"preflight": "passed", "case_id": "SOLR-15",
                          "mode": "healthy", **metadata}, sort_keys=True), flush=True)
        state = campaign.run(HERE / "config-healthy-node0.json", OUT)
    finally:
        for handle in reversed(locks):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return subprocess.run([sys.executable, str(HERE / "audit_healthy.py"), str(OUT)],
                          check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
