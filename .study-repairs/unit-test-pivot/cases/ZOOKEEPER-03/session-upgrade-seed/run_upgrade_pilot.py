#!/usr/bin/env python3
"""Run a separate, bounded original-JUnit I/O pilot with exact actor receipts."""

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
import time

import run_upgrade_health as up
from receipt_validator import parse_events, fault_selector


PILOT = Path("/users/ZhenyuLi/zk03-upgrade-pilot")
MANIFEST = PILOT / "pilot-manifest.json"
HEALTH = Path("/users/ZhenyuLi/zk03-upgrade-seed/healthy-v2")
CHECKPOINT = PILOT / "pilot-checkpoint.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify():
    parent, build = up.assets()
    manifest = json.loads(MANIFEST.read_text())
    calibration = json.loads((HEALTH / "health-calibration.json").read_text())
    if manifest["original_commit"] != up.base.ORIGINAL_SOURCE or \
            manifest["agent_sha256"] != build["agent_sha256"] or \
            calibration["status"] != "healthy_target_calibrated" or \
            manifest["max_trials"] != len(manifest["jobs"]) or \
            len(manifest["jobs"]) != 10:
        raise RuntimeError("pilot original source, agent, or healthy calibration changed")
    selectors = [job["selector"] for job in manifest["jobs"]]
    if len(set(selectors)) != len(selectors):
        raise RuntimeError("pilot has duplicate fault occurrences")
    for label, digest in manifest["healthy_events_sha256"].items():
        if sha(HEALTH / label / "events.tsv") != digest:
            raise RuntimeError("healthy raw events changed: " + label)
    return parent, build, manifest


def run_one(job, parent, build, timeout):
    run_id = job["pilot_id"]
    dest = PILOT / run_id
    if dest.exists():
        raise RuntimeError("existing trial directory requires manual audit: " + str(dest))
    cp = up.base.classpath() + ":" + str(up.AGENT)
    with up.base.START_LOCK.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        gate = up.base.preflight(up.SLOT, up.WORKERS)
        dest.mkdir(parents=True)
        (dest / "temp").mkdir()
        command = [str(up.base.JAVA), "-Xverify:all", "-ea", "-Xmx1g",
                   "-Djava.awt.headless=true", "-Dsun.reflect.noInflation=true",
                   "-Djava.io.tmpdir=" + str(dest / "temp"),
                   "-Dbuild.test.dir=" + str(dest / "test-data"),
                   "-Dtest.junit.threads=" + str(up.WORKERS),
                   "-Dzookeeper.junit.threadid=" + str(up.SLOT),
                   "-Dzk.actor.plan=" + job["selector"],
                   "-Dzk.actor.events.output=" + str(dest / "events.tsv"),
                   "-Dzk.actor.coverage.output=" + str(dest / "coverage.tsv"),
                   "-javaagent:" + str(up.AGENT), "-cp", cp,
                   "independent.OriginalJUnitRunner", up.TEST, up.METHOD]
        start = time.monotonic()
        with (dest / "junit.log").open("w") as log:
            proc = subprocess.Popen(command, cwd=up.base.SOURCE / "zookeeper-server",
                                    stdout=log, stderr=subprocess.STDOUT)
            up.write_json(dest / "launch.json", {"pid": proc.pid,
                          "started_wall": time.time(), "gate": gate,
                          "selector": job["selector"], "agent_sha256": build["agent_sha256"]})
            fcntl.flock(lock, fcntl.LOCK_UN)
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                code = 124
    receipt = {"run_id": run_id, "selector": job["selector"],
               "original_junit": up.TEST + "#" + up.METHOD,
               "original_commit": up.base.ORIGINAL_SOURCE,
               "agent_sha256": build["agent_sha256"],
               "parent_agent_sha256": parent["agent_sha256"],
               "gate": gate, "exit_code": code,
               "elapsed_seconds": round(time.monotonic() - start, 3),
               "events_sha256": sha(dest / "events.tsv") if (dest / "events.tsv").is_file() else None,
               "coverage_sha256": sha(dest / "coverage.tsv") if (dest / "coverage.tsv").is_file() else None}
    up.write_json(dest / "run.json", receipt)
    shutil.rmtree(dest / "temp", ignore_errors=True)
    shutil.rmtree(dest / "test-data", ignore_errors=True)
    return receipt


def audit(job, receipt, seen_coverage, seen_io):
    dest = PILOT / job["pilot_id"]
    rows = parse_events(dest / "events.tsv") if receipt["events_sha256"] else []
    matched = [(seq, fields) for seq, kind, fields in rows if kind == "FAULT_MATCHED"]
    applied = [(seq, fields) for seq, kind, fields in rows if kind == "FAULT_APPLIED"]
    exact = len(matched) == len(applied) == 1 and \
        fault_selector(matched[0][1]) == job["selector"] and \
        fault_selector(applied[0][1]) == job["selector"] and \
        matched[0][0] < applied[0][0] and \
        applied[0][1][6] == "upgradedSession"
    last = applied[0][0] if exact else 0
    leaders = [fields[0] for _, kind, fields in rows if kind == "LEADER_BIND"]
    raws = {fields[0] for _, kind, fields in rows if kind == "SESSION_BIND"
            and len(fields) >= 3 and fields[2] == "upgradedSession"}
    guards = [(seq, fields) for seq, kind, fields in rows
              if seq > last and kind == "TARGET_GUARD" and len(fields) >= 6
              and fields[0] == up.CHECK and fields[2] == "leader"
              and fields[4] == "upgradedSession"] if exact else []
    retained = None
    if len(leaders) == len(raws) == 1:
        for seq, fields in guards:
            if fields[1] != "peer:" + leaders[0] or fields[3] != leaders[0]:
                continue
            owners = [(s, f) for s, kind, f in rows if last < s < seq
                      and kind == "OWNER_BIND" and len(f) >= 4
                      and f[0] == leaders[0] and f[1] in raws
                      and f[3] == fields[5] and
                      f[2].startswith(("forwarder:", "local:"))]
            if owners:
                retained = {"target_sequence": seq, "leader_sid": leaders[0],
                            "raw_session": next(iter(raws)),
                            "owner": owners[-1][1][2], "branch": fields[5]}
                break
    throws = ([(seq, fields) for seq, kind, fields in rows
               if seq > last and kind == "TARGET_THROW" and len(fields) >= 6
               and fields[:5] == [up.CHECK, "peer:" + retained["leader_sid"],
                                    "leader", retained["leader_sid"], "upgradedSession"]]
              if retained else [])
    coverage = set((dest / "coverage.tsv").read_text().splitlines()) \
        if receipt["coverage_sha256"] else set()
    future_io = {"@@".join(fields[:3]) for seq, kind, fields in rows
                 if retained and last < seq < retained["target_sequence"]
                 and kind == "IO" and len(fields) >= 7
                 and fields[6] == "upgradedSession"}
    return {"run_id": job["pilot_id"], "selector": job["selector"],
            "fault_family": job["family"], "exact_injection": exact,
            "target_after_final_fault": retained is not None,
            "target_receipt": retained, "selected_target_throws": len(throws),
            "bug_mark": "candidate_requires_replay" if throws else "none",
            "elapsed_seconds": receipt["elapsed_seconds"],
            "junit_exit": receipt["exit_code"],
            "new_target_coverage_lines": len(coverage - seen_coverage) if retained else 0,
            "new_target_io_families": len(future_io - seen_io) if retained else 0,
            "coverage": sorted(coverage) if retained else [],
            "io_families": sorted(future_io) if retained else [],
            "events_sha256": receipt["events_sha256"],
            "coverage_sha256": receipt["coverage_sha256"]}


def choose(jobs, results):
    used = {r["run_id"] for r in results}
    remaining = [job for job in jobs if job["pilot_id"] not in used]
    def score(job):
        same = [r for r in results if r["fault_family"] == job["family"]]
        return (job["priority"] +
                3 * sum(r["target_after_final_fault"] for r in same) +
                min(3, sum(r["new_target_coverage_lines"] for r in same)) -
                sum(not r["target_after_final_fault"] for r in same))
    return max(remaining, key=lambda j: (score(j), -int(j["pilot_id"].rsplit("-", 1)[1])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--wall-limit", type=int, default=1800)
    args = parser.parse_args()
    if not socket.gethostname().startswith("node1"):
        raise RuntimeError("pilot reserved for node1")
    parent, build, manifest = verify()
    if not args.run:
        print(json.dumps({"status": "prepared_no_jvm", "jobs": len(manifest["jobs"]),
                          "manifest_sha256": sha(MANIFEST)}, sort_keys=True))
        return
    PILOT.mkdir(parents=True, exist_ok=True)
    with (PILOT / "pilot.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.is_file() else \
            {"case_id": "ZOOKEEPER-03", "phase": "session-upgrade-pilot",
             "status": "running", "manifest_sha256": sha(MANIFEST),
             "results": [], "seen_coverage": [], "seen_io_families": [],
             "started_wall": time.time()}
        if state["manifest_sha256"] != sha(MANIFEST):
            raise RuntimeError("pilot manifest differs from checkpoint")
        started = time.monotonic()
        while len(state["results"]) < manifest["max_trials"]:
            if time.monotonic() - started >= args.wall_limit:
                state["status"] = "paused_wall_limit"
                break
            job = choose(manifest["jobs"], state["results"])
            try:
                receipt = run_one(job, parent, build, args.timeout)
            except RuntimeError as error:
                state["status"] = "paused_resource_or_inflight"
                state["pause_reason"] = str(error)
                break
            row = audit(job, receipt, set(state["seen_coverage"]),
                        set(state["seen_io_families"]))
            state["results"].append(row)
            state["seen_coverage"] = sorted(set(state["seen_coverage"]) |
                                            set(row["coverage"]))
            state["seen_io_families"] = sorted(set(state["seen_io_families"]) |
                                               set(row["io_families"]))
            up.write_json(CHECKPOINT, state)
            print(json.dumps({k: row[k] for k in ("run_id", "exact_injection",
                  "target_after_final_fault", "selected_target_throws",
                  "elapsed_seconds", "new_target_coverage_lines")}, sort_keys=True),
                  flush=True)
            if row["selected_target_throws"]:
                state["status"] = "candidate_needs_replay"
                break
        else:
            state["status"] = "queue_exhausted"
        state["finished_wall"] = time.time()
        up.write_json(CHECKPOINT, state)
        print(json.dumps({"status": state["status"], "selected": len(state["results"]),
                          "strict_injections": sum(r["exact_injection"] for r in state["results"]),
                          "target_retaining": sum(r["target_after_final_fault"] for r in state["results"]),
                          "selected_target_throws": sum(r["selected_target_throws"] for r in state["results"])},
                         sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
