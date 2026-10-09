#!/usr/bin/env python3
"""Resume a fixed 63-plan original ZooKeeper JUnit supplement.

The default command verifies the staged assets without starting a JVM.
Only --run executes the unchanged embedded-cluster QuorumTest on node1.
"""

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
import tarfile
import time
import xml.etree.ElementTree as ET

from receipt_validator import ReceiptError, parse_events, validate_rows

HERE = Path(__file__).resolve().parent
ASSETS = Path(os.environ.get("ZK03_SUPPLEMENT_ASSETS",
                             "/users/ZhenyuLi/zk03-supplement-assets"))
ROOT = Path(os.environ.get("ZK03_SUPPLEMENT_RUN_ROOT",
                           "/users/ZhenyuLi/zk03-supplement-runs"))
SOURCE = ASSETS / "source"
AGENT = ASSETS / "agent/zk03-actor-v2-agent.jar"
BUILD_RECEIPT = ASSETS / "agent/build-receipt.json"
RUNNER = ASSETS / "runner/independent-runner.jar"
REPORT = ASSETS / "classpath/QuorumRestartTest.xml"
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar")
JAVA = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/java")
START_LOCK = Path("/users/ZhenyuLi/baseline/crashfuzz/jvm-start.lock")
CHECK = "SessionTrackerImpl#setOwner:329:missingOrClosing"
ORIGINAL_TEST = "org.apache.zookeeper.test.QuorumTest#testSessionMoved"
ORIGINAL_SOURCE = "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae"
MIN_FREE = 10 * 1024**3
MAX_JAVA = 4


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def manifest():
    path = ASSETS / "plan-manifest.json"
    data = json.loads(path.read_text())
    plans = [tuple(job["plan"]) for job in data["jobs"]]
    if data["source_commit"] != ORIGINAL_SOURCE or len(plans) != 63 \
            or len(set(plans)) != 63 or data["old_selected_attempts"] != 480:
        raise RuntimeError("supplement manifest changed or contains duplicate plans")
    return data


def classpath():
    properties = ET.parse(REPORT).getroot().findall("./properties/property")
    original = next(p.get("value") for p in properties
                    if p.get("name") == "java.class.path")
    original = original.replace("/tmp/zk387-unit-smoke-20261006", str(SOURCE))
    cp = os.pathsep.join((str(ASM), original, str(RUNNER), str(AGENT)))
    if "graphchecker" in cp.lower() or "skeleton" in cp.lower():
        raise RuntimeError("non-original graph runtime in JUnit classpath")
    missing = [part for part in cp.split(os.pathsep)
               if part and "*" not in part and not Path(part).exists()]
    if missing:
        raise FileNotFoundError("classpath missing " + repr(missing[:12]))
    return cp


def verify_assets():
    data = manifest()
    receipt = json.loads(BUILD_RECEIPT.read_text())
    revision = json.loads((ASSETS / "source-revision.json").read_text())["commit"]
    if revision != ORIGINAL_SOURCE or receipt["source_commit"] != ORIGINAL_SOURCE:
        raise RuntimeError("original ZooKeeper source revision changed")
    file_hashes = json.loads((ASSETS / "asset-file-sha256.json").read_text())
    for rel, digest in file_hashes.items():
        target = ASSETS / rel
        if not target.is_file() or sha(target) != digest:
            raise RuntimeError("staged asset file differs: " + rel)
    if sha(AGENT) != receipt["agent_sha256"]:
        raise RuntimeError("staged agent jar differs from build receipt")
    if sorted(receipt["agent_sources_sha256"].values()) != \
            data["legacy_agent_source_hashes"]:
        raise RuntimeError("staged agent source differs from legacy fault hooks")
    if receipt["original_classes_sha256"] != data["legacy_original_classes_sha256"] or \
            receipt["original_test_source_sha256"] != \
            data["legacy_original_test_source_sha256"] or \
            receipt["original_target_source_sha256"] != \
            data["legacy_original_target_source_sha256"]:
        raise RuntimeError("staged production/test classes or source differ from legacy")
    if receipt["original_test_class_sha256"] != \
            data["original_test_class_sha256"]:
        raise RuntimeError("original compiled QuorumTest differs from legacy campaign")
    for name, digest in receipt["original_classes_sha256"].items():
        base = (SOURCE / "zookeeper-server/target/test-classes") if name.endswith(
            "/QuorumTest") else (SOURCE / "zookeeper-server/target/classes")
        if sha(base / (name + ".class")) != digest:
            raise RuntimeError("original compiled class changed: " + name)
    if sha(SOURCE / "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java") != \
            receipt["original_test_source_sha256"] or \
            sha(SOURCE / "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java") != \
            receipt["original_target_source_sha256"]:
        raise RuntimeError("selected original test or target source changed")
    if not JAVA.is_file() or not RUNNER.is_file() or not START_LOCK.is_file():
        raise FileNotFoundError("Java 8, original JUnit runner, or shared JVM lock absent")
    if sha(ASSETS / "legacy/raw-runs.tar.gz") != data["legacy_archive_sha256"]:
        raise RuntimeError("legacy checkpoint archive differs from fixed 63-plan manifest")
    cp = classpath()
    return data, {"source_commit": revision, "agent_sha256": sha(AGENT),
                  "agent_source_equivalent_to_legacy": True,
                  "legacy_agent_sha256": data["legacy_agent_sha256"],
                  "asset_manifest_sha256": sha(ASSETS / "asset-file-sha256.json"),
                  "runner_sha256": sha(RUNNER),
                  "original_test_class_sha256": data["original_test_class_sha256"],
                  "classpath_sha256": hashlib.sha256(cp.encode()).hexdigest()}


def port_window(slot, workers):
    span = (32767 - 11221) // workers
    low = 11221 + (slot - 1) * span
    return low, low + span - 1


def preflight(slot, workers):
    free = shutil.disk_usage(ROOT.parent).free
    java_ps = subprocess.run(["ps", "-C", "java", "-o", "pid="],
                             capture_output=True, text=True)
    # procps exits 1 when its selection is empty; zero Java processes pass.
    if java_ps.returncode not in (0, 1):
        raise RuntimeError("cannot count Java processes: " + java_ps.stderr)
    java_count = len(java_ps.stdout.splitlines())
    if free < MIN_FREE or java_count >= MAX_JAVA:
        raise RuntimeError(f"resource gate: free={free} java={java_count}")
    low, high = port_window(slot, workers)
    occupied = []
    for line in subprocess.check_output(["ss", "-H", "-ltn"], text=True).splitlines():
        try:
            port = int(line.split()[3].rsplit(":", 1)[1])
        except (ValueError, IndexError):
            continue
        if low <= port <= high:
            occupied.append(port)
    if occupied:
        raise RuntimeError(f"reserved ZooKeeper port window occupied: {occupied}")
    return {"free_bytes": free, "java_processes_before": java_count,
            "port_window": [low, high]}


def run_one(run_id, plan, slot, workers, timeout, assets):
    dest = ROOT / run_id
    if dest.exists():
        raise FileExistsError(dest)
    dest.mkdir(parents=True)
    (dest / "temp").mkdir()
    cp = classpath()
    command = [str(JAVA), "-Xverify:all", "-ea", "-Xmx1g",
               "-Djava.awt.headless=true", "-Dsun.reflect.noInflation=true",
               "-Djava.io.tmpdir=" + str(dest / "temp"),
               "-Dbuild.test.dir=" + str(dest / "test-data"),
               "-Dtest.junit.threads=" + str(workers),
               "-Dzookeeper.junit.threadid=" + str(slot),
               "-Dzk.actor.plan=" + "|||".join(plan),
               "-Dzk.actor.events.output=" + str(dest / "events.tsv"),
               "-Dzk.actor.coverage.output=" + str(dest / "coverage.tsv"),
               "-javaagent:" + str(AGENT), "-cp", cp,
               "independent.OriginalJUnitRunner",
               "org.apache.zookeeper.test.QuorumTest", "testSessionMoved"]
    start = time.monotonic()
    with (dest / "junit.log").open("w") as log:
        with START_LOCK.open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            gate = preflight(slot, workers)
            process = subprocess.Popen(command, cwd=SOURCE / "zookeeper-server",
                                       stdout=log, stderr=subprocess.STDOUT)
            atomic_json(dest / "launch.json", {"pid": process.pid,
                        "started_wall": time.time(),
                        "agent_sha256": assets["agent_sha256"],
                        "plan_sha256": hashlib.sha256(
                            json.dumps(plan, sort_keys=True).encode()).hexdigest()})
            fcntl.flock(lock, fcntl.LOCK_UN)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            code = 124
    receipt = {"run_id": run_id, "plan": plan, "worker_slot": slot,
               "worker_count": workers, "preflight": gate,
               "elapsed_seconds": round(time.monotonic() - start, 3),
               "exit_code": code, "agent_sha256": assets["agent_sha256"],
               "runner_sha256": assets["runner_sha256"],
               "classpath_sha256": assets["classpath_sha256"],
               "original_source_commit": ORIGINAL_SOURCE,
               "original_test": ORIGINAL_TEST,
               "events_sha256": sha(dest / "events.tsv") if (dest / "events.tsv").is_file() else None,
               "coverage_sha256": sha(dest / "coverage.tsv") if (dest / "coverage.tsv").is_file() else None}
    atomic_json(dest / "run.json", receipt)
    shutil.rmtree(dest / "temp", ignore_errors=True)
    shutil.rmtree(dest / "test-data", ignore_errors=True)
    return receipt


def selected_owner(rows, strict):
    target_seq = strict["target_sequence"]
    target = next((f for s, kind, f in rows
                   if s == target_seq and kind == "TARGET_GUARD"), None)
    if target is None or len(target) < 7:
        return None
    leader = [f[0] for _, kind, f in rows if kind == "LEADER_BIND"]
    raw = {f[0] for _, kind, f in rows if kind == "SESSION_BIND"
           and len(f) >= 4 and f[2] == "movedSession"}
    if len(leader) != 1 or len(raw) != 1 or target[1] != "peer:" + leader[0] \
            or target[3] != leader[0]:
        return None
    owners = [f for s, kind, f in rows if kind == "OWNER_BIND" and s < target_seq
              and len(f) >= 5 and f[-1] == target[-1] and f[0] == leader[0]
              and f[1] in raw and f[3] == target[5]
              and f[2].startswith(("local:", "forwarder:"))]
    if not owners:
        return None
    return {"peer": leader[0], "raw_session": owners[-1][1],
            "requested_owner": owners[-1][2], "session_state": owners[-1][3]}


def audit_one(job, receipt, covered, seen_families):
    dest = ROOT / receipt["run_id"]
    rows = parse_events(dest / "events.tsv") if (dest / "events.tsv").is_file() else []
    reason = None
    try:
        strict = validate_rows(rows, {"plan": job["plan"],
                                      "fault_relations": job["relations"],
                                      "target": {"check": CHECK, "actor": "*",
                                                 "role": "leader", "peer": "*",
                                                 "session_tag": "movedSession"}})
        owner = selected_owner(rows, strict)
        if owner is None:
            raise ReceiptError("postfault selected guard lacks raw-session owner receipt")
    except (ReceiptError, ValueError, IndexError) as error:
        strict, owner, reason = None, None, str(error)
    last_fault = max((s for s, kind, _ in rows if kind == "FAULT_APPLIED"), default=0)
    throws = [f for s, kind, f in rows if strict and kind == "TARGET_THROW"
              and s > last_fault and len(f) >= 7 and f[:5] ==
              [CHECK, strict["target_actor"], "leader", owner["peer"], "movedSession"]]
    coverage = set((dest / "coverage.tsv").read_text().splitlines()) \
        if (dest / "coverage.tsv").is_file() else set()
    future = [f for s, kind, f in rows if strict and kind == "IO"
              and last_fault < s < strict["target_sequence"]
              and len(f) >= 8 and f[6] == "movedSession"]
    families = {"@@".join(f[:3]) for f in future}
    return {"run_id": receipt["run_id"], "supplement_id": job["supplement_id"],
            "parent": job["parent"], "plan": job["plan"],
            "fault_count": len(job["plan"]), "exact": strict is not None,
            "effective": strict is not None, "target_after_final_fault": strict is not None,
            "strict_receipt": strict, "selected_owner_receipt": owner,
            "invalid_reason": reason, "selected_target_throws": len(throws),
            "bug_mark": "candidate_needs_source_review" if throws else "none",
            "new_coverage_lines": len(coverage - covered) if strict else 0,
            "new_io_families": len(families - seen_families) if strict else 0,
            "coverage": sorted(coverage) if strict else [],
            "io_families": sorted(families) if strict else [],
            "elapsed_seconds": receipt["elapsed_seconds"],
            "junit_exit": receipt["exit_code"],
            "events_sha256": receipt["events_sha256"],
            "coverage_sha256": receipt["coverage_sha256"]}


def archive_legacy_feedback():
    legacy = ASSETS / "legacy/raw-runs.tar.gz"
    with tarfile.open(legacy, "r:gz") as archive:
        stream = archive.extractfile("v2-campaign.json")
        if stream is None:
            raise RuntimeError("legacy checkpoint absent")
        cp = json.loads(stream.read())
    return set(cp["seen_coverage"]), set(cp["seen_families"])


def write_ledger(state):
    contents = "".join(json.dumps(row, sort_keys=True) + "\n"
                       for row in state["results"])
    path = ROOT / "supplement-trials.jsonl"
    temporary = path.with_suffix(".jsonl.tmp")
    temporary.write_text(contents)
    os.replace(temporary, path)


def initial_state(data, assets):
    old_coverage, old_families = archive_legacy_feedback()
    return {"schema": 1, "status": "calibrating", "assets": assets,
            "legacy_attempts": 480, "legacy_effective": 37,
            "supplement_cap": 63, "next_trial": 1,
            "healthy": [], "pending_ids": [j["supplement_id"] for j in data["jobs"]],
            "inflight": None, "results": [],
            "seen_coverage": sorted(old_coverage),
            "seen_families": sorted(old_families),
            "started_at": time.time()}


def complete(state, job, receipt):
    if receipt["plan"] != job["plan"] or receipt["agent_sha256"] != \
            state["assets"]["agent_sha256"]:
        raise RuntimeError("run receipt differs from fixed plan or staged agent")
    row = audit_one(job, receipt, set(state["seen_coverage"]),
                    set(state["seen_families"]))
    if row["effective"]:
        state["seen_coverage"] = sorted(set(state["seen_coverage"]) | set(row["coverage"]))
        state["seen_families"] = sorted(set(state["seen_families"]) | set(row["io_families"]))
    row.pop("coverage")
    row.pop("io_families")
    state["results"].append(row)
    state["pending_ids"].remove(job["supplement_id"])
    state["inflight"] = None
    atomic_json(ROOT / "supplement-checkpoint.json", state)
    write_ledger(state)
    print(json.dumps({k: row[k] for k in ("run_id", "effective", "exact",
          "selected_target_throws", "new_coverage_lines", "new_io_families",
          "elapsed_seconds", "junit_exit")}, sort_keys=True), flush=True)
    return row


def own_java_alive(dest):
    launch = dest / "launch.json"
    if not launch.is_file():
        return False
    pid = json.loads(launch.read_text()).get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    command = Path("/proc") / str(pid) / "cmdline"
    return command.is_file() and str(dest / "events.tsv").encode() in command.read_bytes()


def archive_incomplete(dest):
    if own_java_alive(dest):
        return False
    if dest.exists():
        moved = ROOT / "interrupted" / dest.name
        moved.parent.mkdir(exist_ok=True)
        if moved.exists():
            raise RuntimeError("interrupted run archive already exists")
        shutil.move(str(dest), str(moved))
    return True


def recover(state, by_id):
    pending = state["inflight"]
    if pending is None:
        return True
    job = by_id[pending["supplement_id"]]
    dest = ROOT / pending["run_id"]
    receipt = dest / "run.json"
    if receipt.is_file():
        complete(state, job, json.loads(receipt.read_text()))
    else:
        if not archive_incomplete(dest):
            state["status"] = "paused_inflight_java"
            atomic_json(ROOT / "supplement-checkpoint.json", state)
            return False
        state["inflight"] = None
        atomic_json(ROOT / "supplement-checkpoint.json", state)
    return True


def healthy_check(run_id, receipt):
    rows = parse_events(ROOT / run_id / "events.tsv")
    leader = [f[0] for _, kind, f in rows if kind == "LEADER_BIND"]
    raw = {f[0] for _, kind, f in rows if kind == "SESSION_BIND"
           and len(f) >= 4 and f[2] == "movedSession"}
    guards = [f for _, kind, f in rows if kind == "TARGET_GUARD"
              and len(f) >= 7 and f[:5] == [CHECK, "peer:" + leader[0],
                                            "leader", leader[0], "movedSession"]]
    if receipt["exit_code"] != 0 or len(leader) != 1 or len(raw) != 1 \
            or len(guards) != 10 or any(f[5] != "present-open" for f in guards):
        raise RuntimeError("original healthy JUnit calibration failed")
    return {"run_id": run_id, "raw_session": next(iter(raw)),
            "leader_sid": leader[0], "selected_guards": len(guards),
            "elapsed_seconds": receipt["elapsed_seconds"],
            "events_sha256": receipt["events_sha256"],
            "coverage_sha256": receipt["coverage_sha256"]}


def run_campaign(args, data, assets):
    if not socket.gethostname().startswith("node1"):
        raise RuntimeError("supplement is reserved for node1 only")
    if args.slot is None or not 1 <= args.slot <= args.workers:
        raise ValueError("--run requires a reserved --slot within --workers")
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "supplement.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cp_file = ROOT / "supplement-checkpoint.json"
        state = json.loads(cp_file.read_text()) if cp_file.exists() else \
            initial_state(data, assets)
        if state["assets"] != assets or state["legacy_attempts"] != 480:
            raise RuntimeError("resumed assets or legacy denominator changed")
        if state["status"] in ("paused_target_exception_candidate",
                               "paused_junit_timeout") and not args.resume_after_triage:
            print(json.dumps({"status": state["status"],
                              "reason": "inspect raw evidence before further faults"},
                             sort_keys=True))
            return
        by_id = {job["supplement_id"]: job for job in data["jobs"]}
        if not cp_file.exists():
            atomic_json(cp_file, state)
        write_ledger(state)
        if not recover(state, by_id):
            print(json.dumps({"status": state["status"],
                              "inflight": state["inflight"]}, sort_keys=True))
            return
        while len(state["healthy"]) < 2:
            run_id = "healthy-" + "ab"[len(state["healthy"])]
            path = ROOT / run_id / "run.json"
            if not path.is_file() and (ROOT / run_id).exists():
                if not archive_incomplete(ROOT / run_id):
                    state["status"] = "paused_inflight_healthy_java"
                    atomic_json(cp_file, state)
                    print(json.dumps({"status": state["status"],
                                      "run_id": run_id}, sort_keys=True))
                    return
            receipt = json.loads(path.read_text()) if path.is_file() else \
                run_one(run_id, [], args.slot, args.workers, args.timeout, assets)
            audit = healthy_check(run_id, receipt)
            state["healthy"].append(audit)
            state["seen_coverage"] = sorted(set(state["seen_coverage"]) |
                                           set((ROOT / run_id / "coverage.tsv").read_text().splitlines()))
            atomic_json(cp_file, state)
        if state["healthy"][0]["raw_session"] == state["healthy"][1]["raw_session"] or \
                state["healthy"][0]["leader_sid"] != state["healthy"][1]["leader_sid"]:
            raise RuntimeError("healthy seeds lack independent raw sessions or stable leader")
        state["status"] = "running"
        atomic_json(cp_file, state)
        first = len(state["results"])
        started = time.monotonic()
        while state["pending_ids"]:
            if args.max_new_trials is not None and \
                    len(state["results"]) - first >= args.max_new_trials:
                state["status"] = "paused_at_trial_boundary"
                break
            if time.monotonic() - started >= args.wall_limit:
                state["status"] = "paused_wall_limit"
                break
            job = by_id[state["pending_ids"][0]]
            run_id = "supplement-{:03d}".format(state["next_trial"])
            state["inflight"] = {"supplement_id": job["supplement_id"],
                                 "run_id": run_id}
            state["next_trial"] += 1
            atomic_json(cp_file, state)
            receipt = run_one(run_id, job["plan"], args.slot, args.workers,
                              args.timeout, assets)
            row = complete(state, job, receipt)
            if row["selected_target_throws"]:
                state["status"] = "paused_target_exception_candidate"
                break
            if receipt["exit_code"] == 124:
                state["status"] = "paused_junit_timeout"
                break
        else:
            state["status"] = "queue_exhausted"
        atomic_json(cp_file, state)
        write_ledger(state)
        print(json.dumps({"status": state["status"], "new_selected": len(state["results"]),
                          "new_effective": sum(bool(r["effective"]) for r in state["results"]),
                          "pending": len(state["pending_ids"]),
                          "legacy_selected": 480, "legacy_effective": 37},
                         sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--slot", type=int)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--wall-limit", type=int, default=1800)
    parser.add_argument("--max-new-trials", type=int)
    parser.add_argument("--resume-after-triage", action="store_true")
    args = parser.parse_args()
    if args.wall_limit <= 0 or args.timeout <= 0 or args.workers <= 0 or \
            (args.max_new_trials is not None and args.max_new_trials <= 0):
        parser.error("time, worker count and trial limit must be positive")
    data, assets = verify_assets()
    if not args.run:
        print(json.dumps({"status": "prepared_no_jvm", "node": socket.gethostname(),
                          "plans": len(data["jobs"]), "assets": assets,
                          "run_root": str(ROOT)}, sort_keys=True))
        return
    run_campaign(args, data, assets)


if __name__ == "__main__":
    main()
