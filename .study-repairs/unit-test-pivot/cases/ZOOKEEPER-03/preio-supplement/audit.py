#!/usr/bin/env python3
"""Independently recheck each supplemental JUnit from raw events and receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile

from receipt_validator import ReceiptError, parse_events, validate_rows

ASSETS = Path(os.environ.get("ZK03_SUPPLEMENT_ASSETS",
                             "/users/ZhenyuLi/zk03-supplement-assets"))
ROOT = Path(os.environ.get("ZK03_SUPPLEMENT_RUN_ROOT",
                           "/users/ZhenyuLi/zk03-supplement-runs"))
CHECK = "SessionTrackerImpl#setOwner:329:missingOrClosing"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def owner(rows, selected):
    target = next((f for s, kind, f in rows if s == selected and kind == "TARGET_GUARD"), None)
    leaders = {f[0] for _, kind, f in rows if kind == "LEADER_BIND"}
    raw = {f[0] for _, kind, f in rows if kind == "SESSION_BIND"
           and len(f) >= 4 and f[2] == "movedSession"}
    if target is None or len(target) < 7 or len(leaders) != 1 or len(raw) != 1:
        return None
    leader = next(iter(leaders))
    if target[:5] != [CHECK, "peer:" + leader, "leader", leader, "movedSession"]:
        return None
    joined = [f for s, kind, f in rows if kind == "OWNER_BIND" and s < selected
              and len(f) >= 5 and f[-1] == target[-1] and f[0] == leader
              and f[1] in raw and f[3] == target[5]
              and f[2].startswith(("local:", "forwarder:"))]
    return joined[-1] if joined else None


def legacy_coverage():
    with tarfile.open(ASSETS / "legacy/raw-runs.tar.gz", "r:gz") as archive:
        source = archive.extractfile("v2-campaign.json")
        if source is None:
            raise RuntimeError("legacy checkpoint missing")
        state = json.loads(source.read())
    return set(state["seen_coverage"]), set(state["seen_families"])


def audit():
    fixed = json.loads((ASSETS / "plan-manifest.json").read_text())
    jobs = {j["supplement_id"]: j for j in fixed["jobs"]}
    state = json.loads((ROOT / "supplement-checkpoint.json").read_text())
    if state["legacy_attempts"] != 480 or state["legacy_effective"] != 37 or \
            len(jobs) != 63 or len(state["results"]) > 63 or \
            len(state["results"]) + len(state["pending_ids"]) != 63:
        raise RuntimeError("checkpoint denominators or queue changed")
    covered, families = legacy_coverage()
    for healthy in state["healthy"]:
        run = ROOT / healthy["run_id"]
        receipt = json.loads((run / "run.json").read_text())
        if receipt["exit_code"] != 0 or receipt["events_sha256"] != sha(run / "events.tsv") \
                or receipt["coverage_sha256"] != sha(run / "coverage.tsv"):
            raise RuntimeError("healthy original JUnit receipt or raw SHA mismatch")
        rows = parse_events(run / "events.tsv")
        guards = [s for s, kind, f in rows if kind == "TARGET_GUARD"
                  and len(f) >= 7 and f[0] == CHECK and f[2] == "leader"
                  and f[4] == "movedSession" and f[5] == "present-open"]
        if len(guards) != 10 or any(owner(rows, s) is None for s in guards):
            raise RuntimeError("healthy source target/owner calibration changed")
        covered.update((run / "coverage.tsv").read_text().splitlines())
    checked = []
    observed = set()
    for reported in state["results"]:
        key = reported["supplement_id"]
        if key in observed or key not in jobs:
            raise RuntimeError("duplicate or foreign supplemental plan")
        observed.add(key)
        job = jobs[key]
        run = ROOT / reported["run_id"]
        receipt = json.loads((run / "run.json").read_text())
        if receipt["plan"] != job["plan"] or receipt["agent_sha256"] != \
                state["assets"]["agent_sha256"] or \
                receipt["events_sha256"] != sha(run / "events.tsv") or \
                receipt["coverage_sha256"] != sha(run / "coverage.tsv"):
            raise RuntimeError("raw run does not match fixed plan or asset SHA")
        rows = parse_events(run / "events.tsv")
        try:
            strict = validate_rows(rows, {"plan": job["plan"],
                                          "fault_relations": job["relations"],
                                          "target": {"check": CHECK, "actor": "*",
                                                     "role": "leader", "peer": "*",
                                                     "session_tag": "movedSession"}})
            bound = owner(rows, strict["target_sequence"])
            if bound is None:
                raise ReceiptError("no same-session owner receipt")
        except (ReceiptError, ValueError, IndexError):
            strict, bound = None, None
        effective = strict is not None
        last_fault = max((s for s, kind, _ in rows if kind == "FAULT_APPLIED"), default=0)
        target_throws = sum(1 for s, kind, f in rows if effective and kind == "TARGET_THROW"
                            and s > last_fault and len(f) >= 7 and f[:5] ==
                            [CHECK, strict["target_actor"], "leader", bound[0], "movedSession"])
        run_coverage = set((run / "coverage.tsv").read_text().splitlines())
        run_families = {"@@".join(f[:3]) for s, kind, f in rows
                        if effective and kind == "IO"
                        and last_fault < s < strict["target_sequence"]
                        and len(f) >= 8 and f[6] == "movedSession"}
        new_cov = len(run_coverage - covered) if effective else 0
        new_io = len(run_families - families) if effective else 0
        if (reported["effective"] != effective or reported["exact"] != effective
                or reported["selected_target_throws"] != target_throws
                or reported["new_coverage_lines"] != new_cov
                or reported["new_io_families"] != new_io):
            raise RuntimeError("reported trial differs from independent raw audit: " + key)
        if effective:
            covered.update(run_coverage)
            families.update(run_families)
        checked.append({"supplement_id": key, "run_id": reported["run_id"],
                        "effective": effective, "target_throws": target_throws,
                        "new_coverage_lines": new_cov, "new_io_families": new_io,
                        "elapsed_seconds": receipt["elapsed_seconds"],
                        "events_sha256": receipt["events_sha256"],
                        "coverage_sha256": receipt["coverage_sha256"]})
    if observed & set(state["pending_ids"]):
        raise RuntimeError("completed plan is also pending")
    summary = {"case_id": "ZOOKEEPER-03", "status": state["status"],
               "old_selected": 480, "old_effective": 37,
               "supplement_selected": len(checked),
               "supplement_effective": sum(x["effective"] for x in checked),
               "supplement_pending": len(state["pending_ids"]),
               "selected_target_throws": sum(x["target_throws"] for x in checked),
               "supplement_elapsed_seconds": round(
                   sum(x["elapsed_seconds"] for x in checked), 3),
               "healthy_elapsed_seconds": round(
                   sum(x["elapsed_seconds"] for x in state["healthy"]), 3),
               "raw_checked": checked}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="store_true",
                        help="archive completed raw runs after checking no JVM is inflight")
    args = parser.parse_args()
    summary = audit()
    state = json.loads((ROOT / "supplement-checkpoint.json").read_text())
    if args.archive:
        if state["inflight"] is not None:
            raise RuntimeError("cannot archive with an inflight JUnit")
        archive_path = ROOT.parent / "zk03-preio-supplement-raw.tar.gz"
        temporary = archive_path.with_suffix(".tar.gz.tmp")
        with tarfile.open(temporary, "w:gz") as output:
            output.add(ROOT, arcname="zk03-supplement-runs",
                       filter=lambda info: None if "/temp/" in info.name or
                       "/test-data/" in info.name else info)
        os.replace(temporary, archive_path)
        summary["raw_archive"] = str(archive_path)
        summary["raw_archive_sha256"] = sha(archive_path)
    target = ROOT / "audit-summary.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, target)
    print(json.dumps({k: summary[k] for k in ("status", "old_selected",
          "supplement_selected", "supplement_effective", "supplement_pending",
          "selected_target_throws", "supplement_elapsed_seconds")}, sort_keys=True))


if __name__ == "__main__":
    main()
