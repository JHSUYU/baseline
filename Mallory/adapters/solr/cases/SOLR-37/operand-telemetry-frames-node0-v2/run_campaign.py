#!/usr/bin/env python3
"""Offline preflight and GO-gated, one-trial SOLR-37 operand telemetry run."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
CASE = HERE.parent.name
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
OUT_ROOT = ROOT / "data/mallory/solr37_operand_telemetry_frames_healthy_v2_node0" / CASE
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def preflight(mode: str) -> dict:
    if mode != "healthy":
        raise ValueError("only healthy mode is admitted")
    manifest = read(HERE / "sha-manifest.json")
    if manifest["case_id"] != CASE:
        raise ValueError("wrong package manifest")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local file changed: {name}")
    config_path = HERE / "config-healthy-node0.json"
    config = read(config_path)
    if config["case_id"] != CASE or config["site_file"] != str(HERE / "sites.json"):
        raise ValueError("wrong case or site file")
    if config["budget"] != {"trials": 1, "seconds": 600,
                            "max_faults_per_trial": 1, "trial_timeout_seconds": 480}:
        raise ValueError("healthy budget changed")
    if (config["calibration_only"] is not True or
            config["auto_promote_if_healthy"] is not False or
            config.get("fault_types") != ["EXCEPTION"] or
            config.get("require_event_time_paths") is not True or
            config.get("reject_coarse_roots") is not True):
        raise ValueError("mode or fault admission changed")
    if config["core_release"] != str(RELEASE) or not Path(campaign.__file__).resolve().is_relative_to(RELEASE):
        raise ValueError("graph-order core is not pinned")
    sites = read(HERE / "sites.json")
    watcher_class = "org.apache.solr.common.cloud.ZkStateReader$StateWatcher"
    reader_class = "org.apache.solr.common.cloud.ZkStateReader"
    expected_door = {
        "class": reader_class,
        "callee": ("org.apache.solr.common.cloud.SolrZkClient#getData"
                   "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                   "Lorg/apache/zookeeper/data/Stat;Z)[B"),
        "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException",
    }
    if sites["doors"] != [expected_door]:
        raise ValueError("watcher catalog must select only the typed getData call")
    watcher_region = {"clazz": watcher_class,
                      "descriptor": "(Lorg/apache/zookeeper/Watcher$Event$EventType;)V",
                      "method": "refreshAndWatch"}
    if watcher_region not in sites["regions"]:
        raise ValueError("StateWatcher region missing")
    if not {reader_class, watcher_class}.issubset(config["agent_include"]):
        raise ValueError("watcher or reader instrumentation omitted")
    if (config["agent_properties"]["adapter.jar"] !=
            str(HERE / "release/adapter.jar")):
        raise ValueError("SOLR-37 operand telemetry adapter required")
    if config["command"][1] != str(ROOT / "Mallory/adapters/solr/releases/v46/run_pilot.py"):
        raise ValueError("v46 direct-JUnit wrapper required for v46 adapter")
    target_lines = {(row["clazz"], row["line"]) for row in sites["targets"]}
    for check in [*config["target"]["check_sites"], config["target"]["throw_site"]]:
        clazz, line = check.split("#", 1)[0], int(check.rsplit("@", 1)[1].split(":", 1)[0])
        if (clazz, line) not in target_lines:
            raise ValueError("selected target absent from site catalog")
    request = read(HERE / "admission-request.json")
    if (request.get("go") is not False or request.get("execution_status") != "not_launched"
            or request.get("case_id") != CASE or request.get("host") != "node0"
            or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("modes", {}).get("healthy", {}).get("config_sha256") != sha(config_path)
            or request["modes"]["healthy"].get("intended_output") != str(OUT_ROOT / "healthy")):
        raise ValueError("healthy-only admission request changed")
    if not sites["doors"] or not sites["regions"]:
        raise ValueError("injectable I/O or target region missing")
    for row in config["runtime_artifacts"]:
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    source = Path(config["cwd"])
    if not source.is_dir() or config["source_equivalent_root"] != str(source):
        raise ValueError("source checkout missing")
    if (subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                text=True).strip() !=
            "e27f44e3d78dfcec230c97e0a1240e3751daeff9" or
            subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"],
                                    text=True).strip()):
        raise ValueError("node0 Solr source revision or cleanliness changed")
    inventory = read(ROOT / "Mallory/adapters/solr/releases/v20/inventory.json")
    row = next(item for item in inventory["cases"] if item["case_id"] == CASE)
    test_rel = row["workload"]["test_source_path"]
    if sha(source / test_rel) != config["mapping"]["test_source_sha256"]:
        raise ValueError("selected JUnit source changed")
    if sha(source / config["target"]["source_path"]) != config["mapping"]["target_source_sha256"]:
        raise ValueError("target source changed")
    compiled = Path(config["mapping"]["compiled_jar"])
    if sha(compiled) != config["mapping"]["compiled_jar_sha256"]:
        raise ValueError("compiled JAR changed")
    member = config["target"]["check_sites"][0].split("#", 1)[0].replace(".", "/") + ".class"
    with zipfile.ZipFile(compiled) as archive:
        class_hash = hashlib.sha256(archive.read(member)).hexdigest()
    if class_hash != config["mapping"]["compiled_class_sha256"]:
        raise ValueError("compiled target class changed")
    watcher_source = source / "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"
    if sha(watcher_source) != config["mapping"]["watcher_source_sha256"]:
        raise ValueError("watcher source changed")
    lines = watcher_source.read_text().splitlines()
    required_lines = {1384: "fetchCollectionState(coll, this, collectionPath)",
                      1390: "KeeperException.ConnectionLossException",
                      1641: "zkClient.getData(collectionPath, watcher, stat, true)"}
    for line, fragment in required_lines.items():
        if fragment not in lines[line - 1]:
            raise ValueError(f"watcher source site moved: {line}")
    solrj = Path(config["mapping"]["compiled_solrj_jar"])
    if sha(solrj) != config["mapping"]["compiled_solrj_jar_sha256"]:
        raise ValueError("compiled SolrJ JAR changed")
    with zipfile.ZipFile(solrj) as archive:
        for member, expected in config["mapping"]["watcher_class_sha256"].items():
            if hashlib.sha256(archive.read(member)).hexdigest() != expected:
                raise ValueError(f"compiled watcher class changed: {member}")
    campaign.validate_config(config)
    return {"config_sha256": sha(config_path), "site_sha256": sha(HERE / "sites.json"),
            "agent_sha256": sha(Path(config["agent_jar"])),
            "adapter_sha256": sha(Path(config["agent_properties"]["adapter.jar"])),
            "core_manifest_sha256": sha(RELEASE / "manifest.json")}


def check_go(mode: str, path: Path, config_sha: str, out: Path) -> str:
    if path.resolve() != HERE / "admission-healthy-node0.json":
        raise ValueError("case-local node0 GO receipt required")
    receipt = read(path)
    if (receipt.get("go") is not True or receipt.get("host") != "node0"
            or receipt.get("case_id") != CASE or receipt.get("mode") != mode
            or receipt.get("config_sha256") != config_sha
            or receipt.get("runner_sha256") != sha(Path(__file__))
            or receipt.get("intended_output") != str(out)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = ("healthy",)
    parser.add_argument("--mode", choices=modes, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight(args.mode)
    out = OUT_ROOT / args.mode
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", "case_id": CASE,
                          "mode": args.mode, **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.mode, args.admission_receipt,
                                            metadata["config_sha256"], out)
    print(json.dumps({"preflight": "passed", "case_id": CASE,
                      "mode": args.mode, **metadata}, sort_keys=True), flush=True)
    if socket.gethostname().split(".", 1)[0] != "node0" or out.exists():
        raise ValueError("node0 and a fresh healthy output are required")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    locks = []
    try:
        for name in ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks.append(handle)
        if out.exists():
            raise ValueError("healthy output appeared while acquiring locks")
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("insufficient free disk")
        available_kib = next(int(row.split()[1]) for row in
                             Path("/proc/meminfo").read_text().splitlines()
                             if row.startswith("MemAvailable:"))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available RAM")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"] for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node0")
        state = campaign.run(HERE / "config-healthy-node0.json", out)
    finally:
        for handle in reversed(locks):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
