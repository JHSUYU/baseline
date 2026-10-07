#!/usr/bin/env python3
"""Two no-fault original SessionUpgradeTest JUnits under the shared node1 gate."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time


sys.path.insert(0, "/users/ZhenyuLi/zk03-supplement-assets")
import campaign as base  # noqa: E402: pinned stage and shared launch gate
from receipt_validator import parse_events  # noqa: E402


BASE = Path("/users/ZhenyuLi/zk03-upgrade-seed")
ROOT = Path(os.environ.get("ZK03_UPGRADE_RUN_ROOT", str(BASE)))
AGENT = BASE / "assets/zk03-session-upgrade-agent.jar"
BUILD = BASE / "assets/build-receipt.json"
TEST = "org.apache.zookeeper.test.SessionUpgradeTest"
METHOD = "testUpgradeWithEphemeralOnFollower"
CHECK = "SessionTrackerImpl#setOwner:329:missingOrClosing"
SLOT = 15
WORKERS = 16


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assets():
    _, parent = base.verify_assets()
    receipt = json.loads(BUILD.read_text())
    if receipt["original_commit"] != base.ORIGINAL_SOURCE or \
            sha(AGENT) != receipt["agent_sha256"] or \
            parent["agent_sha256"] != receipt["generic_agent_sha256"]:
        raise RuntimeError("upgrade or original actor agent changed")
    for name, digest in receipt["original_classes_sha256"].items():
        class_root = (base.SOURCE / "zookeeper-server/target/test-classes") \
            if "/test/" in name else \
            (base.SOURCE / "zookeeper-server/target/classes")
        if sha(class_root / (name + ".class")) != digest:
            raise RuntimeError("original class changed: " + name)
    return parent, receipt


def write_json(path, value):
    base.atomic_json(path, value)


def run_one(label, timeout, parent, build):
    dest = ROOT / label
    if dest.exists():
        raise FileExistsError(dest)
    dest.mkdir(parents=True)
    (dest / "temp").mkdir()
    cp = base.classpath() + ":" + str(AGENT)
    command = [str(base.JAVA), "-Xverify:all", "-ea", "-Xmx1g",
               "-Djava.awt.headless=true", "-Dsun.reflect.noInflation=true",
               "-Djava.io.tmpdir=" + str(dest / "temp"),
               "-Dbuild.test.dir=" + str(dest / "test-data"),
               "-Dtest.junit.threads=" + str(WORKERS),
               "-Dzookeeper.junit.threadid=" + str(SLOT),
               "-Dzk.actor.plan=",
               "-Dzk.actor.events.output=" + str(dest / "events.tsv"),
               "-Dzk.actor.coverage.output=" + str(dest / "coverage.tsv"),
               "-javaagent:" + str(AGENT), "-cp", cp,
               "independent.OriginalJUnitRunner", TEST, METHOD]
    start = time.monotonic()
    with (dest / "junit.log").open("w") as log:
        with base.START_LOCK.open("r+") as launch_lock:
            fcntl.flock(launch_lock, fcntl.LOCK_EX)
            gate = base.preflight(SLOT, WORKERS)
            process = subprocess.Popen(command, cwd=base.SOURCE / "zookeeper-server",
                                       stdout=log, stderr=subprocess.STDOUT)
            write_json(dest / "launch.json", {"pid": process.pid,
                        "agent_sha256": build["agent_sha256"],
                        "parent_agent_sha256": parent["agent_sha256"],
                        "started_wall": time.time()})
            fcntl.flock(launch_lock, fcntl.LOCK_UN)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            code = 124
    receipt = {"run_id": label, "original_junit": TEST + "#" + METHOD,
               "exit_code": code, "elapsed_seconds": round(time.monotonic() - start, 3),
               "gate": gate, "agent_sha256": build["agent_sha256"],
               "original_commit": base.ORIGINAL_SOURCE,
               "original_test_class_sha256": build["original_classes_sha256"][
                   "org/apache/zookeeper/test/SessionUpgradeTest"],
               "events_sha256": sha(dest / "events.tsv") if (dest / "events.tsv").is_file() else None,
               "coverage_sha256": sha(dest / "coverage.tsv") if (dest / "coverage.tsv").is_file() else None}
    write_json(dest / "run.json", receipt)
    shutil.rmtree(dest / "temp", ignore_errors=True)
    shutil.rmtree(dest / "test-data", ignore_errors=True)
    return receipt


def audit_one(label, receipt):
    events = parse_events(ROOT / label / "events.tsv")
    kinds = {}
    for _, kind, _ in events:
        kinds[kind] = kinds.get(kind, 0) + 1
    leaders = [fields[0] for _, kind, fields in events if kind == "LEADER_BIND"]
    peers = [fields[0] for _, kind, fields in events if kind == "PEER_BIND"]
    bindings = [fields for _, kind, fields in events if kind == "SESSION_BIND"
                and len(fields) >= 3 and fields[2] == "upgradedSession"]
    raws = {fields[0] for fields in bindings}
    phases = [fields[0] for _, kind, fields in events
              if kind == "UPGRADE_PHASE" and fields]
    guards = [(seq, fields) for seq, kind, fields in events
              if kind == "TARGET_GUARD" and len(fields) >= 6 and
              fields[0] == CHECK and fields[2] == "leader" and
              fields[4] == "upgradedSession"]
    owners = [fields for _, kind, fields in events if kind == "OWNER_BIND"
              and len(fields) >= 4 and fields[1] in raws]
    valid_guard = bool(guards) and all(fields[5] == "present-open" and
        fields[1] == "peer:" + leaders[0] and fields[3] == leaders[0]
        for _, fields in guards) if len(leaders) == 1 else False
    usable = (receipt["exit_code"] == 0 and len(peers) == 5 and
              len(set(peers)) == 5 and len(leaders) == 1 and len(raws) == 1 and
              {x[1] for x in bindings} >= {"initial", "reconnected"} and
              phases == ["reconnect-begin", "reconnect-end-before-close"] and
              valid_guard and bool(owners) and
              kinds.get("TARGET_THROW", 0) == 0 and
              kinds.get("FAULT_APPLIED", 0) == 0 and
              kinds.get("BINDING_ERROR", 0) == 0)
    return {"run_id": label, "usable": usable, "leader_sid": leaders[0] if len(leaders) == 1 else None,
            "raw_session": next(iter(raws)) if len(raws) == 1 else None,
            "peer_count": len(peers), "phase_events": phases,
            "global_target_guards": len(guards),
            "expected_local_tracker_guards_ignored": kinds.get("IGNORED_LOCAL_TRACKER_GUARD", 0),
            "selected_target_throws": kinds.get("TARGET_THROW", 0),
            "binding_errors": kinds.get("BINDING_ERROR", 0),
            "faults_applied": kinds.get("FAULT_APPLIED", 0),
            "elapsed_seconds": receipt["elapsed_seconds"],
            "events_sha256": receipt["events_sha256"],
            "coverage_sha256": receipt["coverage_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not socket.gethostname().startswith("node1"):
        raise RuntimeError("isolated healthy calibration reserved for node1")
    parent, build = assets()
    if not args.run:
        print(json.dumps({"status": "prepared_no_jvm", "agent_sha256": build["agent_sha256"],
                          "original_commit": build["original_commit"],
                          "original_test": TEST + "#" + METHOD}, sort_keys=True))
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "health.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        audits = []
        for label in ("healthy-a", "healthy-b"):
            path = ROOT / label / "run.json"
            receipt = json.loads(path.read_text()) if path.is_file() else \
                run_one(label, args.timeout, parent, build)
            audit = audit_one(label, receipt)
            audits.append(audit)
            write_json(ROOT / "health-calibration.json",
                       {"status": "calibrating", "audits": audits,
                        "original_junit": TEST + "#" + METHOD})
            print(json.dumps(audit, sort_keys=True), flush=True)
            if not audit["usable"]:
                print(json.dumps({"status": "unusable_no_selected_global_target"},
                                 sort_keys=True), flush=True)
                return
        distinct = audits[0]["raw_session"] != audits[1]["raw_session"]
        consistent = audits[0]["leader_sid"] == audits[1]["leader_sid"]
        status = "healthy_target_calibrated" if distinct and consistent else \
                 "unusable_identity_unstable"
        write_json(ROOT / "health-calibration.json", {"status": status,
                   "audits": audits, "independent_raw_sessions": distinct,
                   "stable_leader_sid": consistent,
                   "original_junit": TEST + "#" + METHOD,
                   "agent_sha256": build["agent_sha256"]})
        print(json.dumps({"status": status}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
