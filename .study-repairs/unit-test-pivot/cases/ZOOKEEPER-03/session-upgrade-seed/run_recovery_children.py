#!/usr/bin/env python3
"""Resume thirteen ordered two-IOException plans from observed recovery I/O."""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import socket
import time

import run_upgrade_pilot as pilot
from receipt_validator import parse_events, fault_selector


ROOT = Path("/users/ZhenyuLi/zk03-upgrade-recovery-children")
MANIFEST = ROOT / "recovery-child-manifest.json"
CHECKPOINT = ROOT / "child-checkpoint.json"
PARENT = Path("/users/ZhenyuLi/zk03-upgrade-pilot")
PARENT_ARCHIVE = ROOT / "zk03-upgrade-pilot-raw.tar.gz"
pilot.PILOT = ROOT  # Reuse the pinned JUnit launch/gate only, with a separate root.


def verify():
    parent_assets, build = pilot.up.assets()
    manifest = json.loads(MANIFEST.read_text())
    pa = json.loads((PARENT / "pilot-feedback-audit.json").read_text())
    if manifest["original_commit"] != pilot.up.base.ORIGINAL_SOURCE or \
            manifest["agent_sha256"] != build["agent_sha256"] or \
            manifest["parent_pilot_archive_sha256"] != pilot.sha(PARENT_ARCHIVE) or \
            pa["status"] != "queue_exhausted" or pa["selected"] != 10 or \
            pa["target_retaining"] != 3 or len(manifest["jobs"]) != 13:
        raise RuntimeError("recovery child original assets or parent evidence changed")
    plans = [tuple(j["plan"]) for j in manifest["jobs"]]
    if len(set(plans)) != 13 or any(len(p) != 2 for p in plans):
        raise RuntimeError("child queue has duplicate or non-two-fault plan")
    return parent_assets, build, manifest, pa


def base_feedback(parent_audit):
    coverage = set()
    io_families = set()
    for label in ("healthy-a", "healthy-b"):
        root = pilot.HEALTH / label
        coverage |= set((root / "coverage.tsv").read_text().splitlines())
        io_families |= {"@@".join(fields[:3]) for _, kind, fields in
                        parse_events(root / "events.tsv") if kind == "IO"
                        and len(fields) >= 7 and fields[6] == "upgradedSession"}
    for entry in parent_audit["trials"]:
        if not entry["target_after_final_fault"]:
            continue
        root = PARENT / entry["run_id"]
        coverage |= set((root / "coverage.tsv").read_text().splitlines())
        rows = parse_events(root / "events.tsv")
        last = max(s for s, kind, _ in rows if kind == "FAULT_APPLIED")
        target = entry["target_receipt"]["target_sequence"]
        io_families |= {"@@".join(fields[:3]) for s, kind, fields in rows
                        if last < s < target and kind == "IO"
                        and len(fields) >= 7 and fields[6] == "upgradedSession"}
    return coverage, io_families


def audit(job, receipt, seen_coverage, seen_io):
    root = ROOT / job["child_id"]
    rows = parse_events(root / "events.tsv") if receipt["events_sha256"] else []
    matched = [(s, f) for s, kind, f in rows if kind == "FAULT_MATCHED"]
    applied = [(s, f) for s, kind, f in rows if kind == "FAULT_APPLIED"]
    exact = len(matched) == len(applied) == len(job["plan"]) and \
        [fault_selector(f) for _, f in matched] == job["plan"] and \
        [fault_selector(f) for _, f in applied] == job["plan"] and \
        all(m[0] < a[0] for m, a in zip(matched, applied)) and \
        all(f[6] == "upgradedSession" for _, f in applied)
    last = applied[-1][0] if exact else 0
    leaders = [f[0] for _, kind, f in rows if kind == "LEADER_BIND"]
    raws = {f[0] for _, kind, f in rows if kind == "SESSION_BIND"
            and len(f) >= 3 and f[2] == "upgradedSession"}
    retained = None
    if exact and len(leaders) == len(raws) == 1:
        for s, kind, f in rows:
            if s <= last or kind != "TARGET_GUARD" or len(f) < 6 or \
                    f[:5] != [pilot.up.CHECK, "peer:" + leaders[0],
                              "leader", leaders[0], "upgradedSession"]:
                continue
            owners = [(os, owner) for os, okind, owner in rows
                      if last < os < s and okind == "OWNER_BIND"
                      and len(owner) >= 4 and owner[0] == leaders[0]
                      and owner[1] in raws and owner[3] == f[5]
                      and owner[2].startswith(("forwarder:", "local:"))]
            if owners:
                retained = {"target_sequence": s, "leader_sid": leaders[0],
                            "raw_session": next(iter(raws)),
                            "owner": owners[-1][1][2], "branch": f[5]}
                break
    throws = ([(s, f) for s, kind, f in rows if s > last
               and kind == "TARGET_THROW" and len(f) >= 6
               and f[:5] == [pilot.up.CHECK, "peer:" + retained["leader_sid"],
                             "leader", retained["leader_sid"], "upgradedSession"]]
              if retained else [])
    coverage = set((root / "coverage.tsv").read_text().splitlines()) \
        if receipt["coverage_sha256"] else set()
    future_io = {"@@".join(f[:3]) for s, kind, f in rows
                 if retained and last < s < retained["target_sequence"]
                 and kind == "IO" and len(f) >= 7 and f[6] == "upgradedSession"}
    return {"run_id": job["child_id"], "parent": job["parent"],
            "plan": job["plan"], "child_family": job["child_family"],
            "faults_matched": len(matched), "faults_applied": len(applied),
            "exact_injection": exact, "target_after_final_fault": retained is not None,
            "target_receipt": retained, "selected_target_throws": len(throws),
            "bug_mark": "candidate_requires_replay" if throws else "none",
            "junit_exit": receipt["exit_code"],
            "elapsed_seconds": receipt["elapsed_seconds"],
            "new_target_coverage_lines": len(coverage - seen_coverage) if retained else 0,
            "new_target_io_families": len(future_io - seen_io) if retained else 0,
            "coverage": sorted(coverage) if retained else [],
            "io_families": sorted(future_io) if retained else [],
            "events_sha256": receipt["events_sha256"],
            "coverage_sha256": receipt["coverage_sha256"]}


def choose(jobs, results):
    done = {x["run_id"] for x in results}
    remaining = [job for job in jobs if job["child_id"] not in done]
    def score(job):
        peers = [r for r in results if r["child_family"] == job["child_family"]]
        return (job["priority"] +
                3 * sum(r["target_after_final_fault"] for r in peers) +
                min(3, sum(r["new_target_io_families"] for r in peers)) -
                sum(not r["target_after_final_fault"] for r in peers))
    return max(remaining, key=lambda j: (score(j), -int(j["child_id"].rsplit("-", 1)[1])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--wall-limit", type=int, default=1800)
    args = parser.parse_args()
    if not socket.gethostname().startswith("node1"):
        raise RuntimeError("ZK03 recovery child stage reserved for node1")
    assets, build, manifest, parent_audit = verify()
    covered, known_io = base_feedback(parent_audit)
    if not args.run:
        print(json.dumps({"status": "prepared_no_jvm", "jobs": len(manifest["jobs"]),
                          "parent_pilot_selected": parent_audit["selected"],
                          "baseline_coverage_lines": len(covered),
                          "baseline_io_families": len(known_io)}, sort_keys=True))
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "child.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.is_file() else \
            {"case_id": "ZOOKEEPER-03", "phase": manifest["phase"],
             "status": "running", "manifest_sha256": pilot.sha(MANIFEST),
             "results": [], "started_wall": time.time()}
        if state["manifest_sha256"] != pilot.sha(MANIFEST):
            raise RuntimeError("child manifest changed across resume")
        for previous in state["results"]:
            if previous["target_after_final_fault"]:
                covered |= set(previous["coverage"])
                known_io |= set(previous["io_families"])
        started = time.monotonic()
        while len(state["results"]) < manifest["max_trials"]:
            if time.monotonic() - started >= args.wall_limit:
                state["status"] = "paused_wall_limit"
                break
            job = choose(manifest["jobs"], state["results"])
            launch_job = {"pilot_id": job["child_id"],
                          "selector": "|||".join(job["plan"])}
            try:
                receipt = pilot.run_one(launch_job, assets, build, args.timeout)
            except RuntimeError as error:
                state["status"] = "paused_resource_or_inflight"
                state["pause_reason"] = str(error)
                break
            row = audit(job, receipt, covered, known_io)
            state["results"].append(row)
            if row["target_after_final_fault"]:
                covered |= set(row["coverage"])
                known_io |= set(row["io_families"])
            pilot.up.write_json(CHECKPOINT, state)
            print(json.dumps({key: row[key] for key in
                  ("run_id", "faults_applied", "exact_injection",
                   "target_after_final_fault", "selected_target_throws",
                   "new_target_coverage_lines", "new_target_io_families",
                   "elapsed_seconds")}, sort_keys=True), flush=True)
            if row["selected_target_throws"]:
                state["status"] = "candidate_needs_replay"
                break
        else:
            state["status"] = "queue_exhausted"
        state["finished_wall"] = time.time()
        pilot.up.write_json(CHECKPOINT, state)
        print(json.dumps({"status": state["status"], "selected": len(state["results"]),
                          "exact_injections": sum(r["exact_injection"] for r in state["results"]),
                          "target_retaining": sum(r["target_after_final_fault"] for r in state["results"]),
                          "selected_target_throws": sum(r["selected_target_throws"] for r in state["results"])},
                         sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
