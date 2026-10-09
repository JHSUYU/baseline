#!/usr/bin/env python3
"""Stage exactly the 63 untried ZK03 pre-I/O plans; never launch a JVM."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
sys.path.insert(0, str(CASE))
import frontier_audit as archive_audit  # noqa: E402
from receipt_validator import validate_rows  # noqa: E402

TARGET = {"check": archive_audit.CHECK, "actor": "*", "role": "leader",
          "peer": "*", "session_tag": "movedSession"}


def parse_raw_events(data):
    rows = []
    for line in data.decode().splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            raise ValueError("short archived event row")
        rows.append((int(parts[0]), parts[1], parts[2:]))
    return sorted(rows)


def owner_for_guard(rows, guard_seq, leader, raw):
    target = next((f for s, kind, f in rows
                   if s == guard_seq and kind == "TARGET_GUARD"), None)
    if target is None or target[:5] != [archive_audit.CHECK, "peer:" + leader,
                                        "leader", leader, "movedSession"]:
        return None
    owners = [f for s, kind, f in rows if kind == "OWNER_BIND" and s < guard_seq
              and len(f) >= 5 and f[-1] == target[-1]
              and f[0] == leader and f[1] == raw
              and f[2].startswith(("local:", "forwarder:"))
              and f[3] == target[5]]
    return owners[-1] if owners else None


def prepare():
    with archive_audit.open_archive("pre_io") as archive:
        raw_cp = archive_audit.member(archive, "v2-campaign.json")
        cp = json.loads(raw_cp)
        if cp["status"] != "attempt_cap" or len(cp["results"]) != 480 \
                or cp["effective_count"] != 37 or cp["inflight"] or \
                len(cp["pending"]) != 63:
            raise RuntimeError("legacy atomic checkpoint changed")
        original_build = archive_audit.checkpoint(archive, "build-receipt.json")
        old = {r["run_id"]: r for r in cp["results"]}
        tested = {tuple(r["plan"]) for r in cp["results"]}
        pending = [tuple(job["plan"]) for job in cp["pending"]]
        if len(set(pending)) != 63 or set(pending) & tested:
            raise RuntimeError("pending plans are duplicate or already executed")
        cache = {}
        jobs = []
        for ordinal, job in enumerate(cp["pending"], start=1):
            parent = old[job["parent"]]
            plan = job["plan"]
            relations = job["relations"]
            if not parent["effective"] or len(plan) > cp["max_faults"] or \
                    plan[:-1] != parent["plan"] or \
                    relations[:-1] != parent["relations"] or \
                    len(plan) != len(relations):
                raise RuntimeError("pending plan lacks an effective measured parent")
            if parent["run_id"] not in cache:
                event_bytes = archive_audit.member(
                    archive, parent["run_id"] + "/events.tsv")
                rows = parse_raw_events(event_bytes)
                strict = validate_rows(rows, {"plan": parent["plan"],
                                              "fault_relations": parent["relations"],
                                              "target": TARGET})
                if strict != parent["strict_receipt"]:
                    raise RuntimeError("parent strict receipt differs from raw events")
                owner = parent["selected_owner_receipt"]
                selected_owner = owner_for_guard(
                    rows, strict["target_sequence"], owner["peer"],
                    owner["raw_session"])
                if selected_owner is None or selected_owner[2] != owner["requested_owner"]:
                    raise RuntimeError("parent raw selected owner receipt changed")
                cache[parent["run_id"]] = (rows, event_bytes)
            rows, event_bytes = cache[parent["run_id"]]
            applied = [s for s, kind, _ in rows if kind == "FAULT_APPLIED"]
            last_fault = max(applied)
            matches = [(s, f) for s, kind, f in rows if kind == "IO"
                       and s > last_fault and len(f) >= 8
                       and archive_audit.selector(f) == plan[-1]
                       and f[6] == "movedSession"]
            if len(matches) != 1:
                raise RuntimeError("candidate is not one exact bound parent I/O")
            candidate_seq, candidate = matches[0]
            leader = parent["selected_owner_receipt"]["peer"]
            later = [s for s, kind, f in rows if kind == "TARGET_GUARD"
                     and s > candidate_seq and len(f) >= 7
                     and f[:5] == [archive_audit.CHECK, "peer:" + leader,
                                   "leader", leader, "movedSession"]
                     and owner_for_guard(rows, s, leader,
                                         parent["selected_owner_receipt"]["raw_session"])]
            if not later:
                raise RuntimeError("candidate has no later same-session leader check")
            if relations[-1] != "same_session" or \
                    "session:movedSession" not in candidate[1]:
                raise RuntimeError("last fault lacks moved-session actor relation")
            jobs.append({
                "supplement_id": f"supplement-{ordinal:03d}",
                "parent": parent["run_id"],
                "plan": plan,
                "relations": relations,
                "depth": len(plan),
                "parent_last_fault_sequence": last_fault,
                "candidate_sequence": candidate_seq,
                "next_selected_guard_sequence": later[0],
                "parent_events_sha256": hashlib.sha256(event_bytes).hexdigest(),
                "parent_raw_session": parent["selected_owner_receipt"]["raw_session"],
                "parent_requested_owner": parent["selected_owner_receipt"]["requested_owner"],
                "prior_source_selector_tested": any(
                    r["plan"][-1] == plan[-1] for r in cp["results"]),
            })
        durations = [float(row["elapsed_seconds"]) for row in cp["results"]]
        out = {
            "schema": 1,
            "case_id": "ZOOKEEPER-03",
            "workload": "org.apache.zookeeper.test.QuorumTest#testSessionMoved",
            "target": archive_audit.CHECK,
            "source_commit": archive_audit.SOURCE_REVISION,
            "legacy_archive_sha256": archive_audit.SOURCES["pre_io"][2],
            "legacy_checkpoint_sha256": hashlib.sha256(raw_cp).hexdigest(),
            "legacy_agent_sha256": original_build["agent_sha256"],
            "legacy_agent_source_hashes": sorted(
                original_build["agent_sources_sha256"].values()),
            "legacy_original_classes_sha256": original_build[
                "original_classes_sha256"],
            "legacy_original_test_source_sha256": original_build[
                "original_test_source_sha256"],
            "legacy_original_target_source_sha256": original_build[
                "original_target_source_sha256"],
            "original_test_class_sha256": original_build[
                "original_test_class_sha256"],
            "old_selected_attempts": 480,
            "old_effective": 37,
            "old_budget_effective": cp["budget_effective"],
            "supplement_selected_cap": 63,
            "supplement_effective_budget": "audit all 63; never pool with old 37/80",
            "depths": dict(Counter(str(len(job["plan"])) for job in cp["pending"])),
            "estimated_jvm_seconds_at_old_mean": round(
                statistics.mean(durations) * 63, 3),
            "old_trial_seconds_mean": round(statistics.mean(durations), 3),
            "old_trial_seconds_max": max(durations),
            "jobs": jobs,
            "preflight_limit": "one JVM; shared jvm-start.lock; Java processes <5; free disk >=10 GiB; reserved port slot",
            "postfault_limit": "future target retention cannot be proven offline; every new run is audited separately",
        }
    path = HERE / "plan-manifest.json"
    path.write_text(json.dumps(out, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": "prepared_no_jvm", "jobs": len(jobs),
                      "all_unique": len(set(pending)) == 63,
                      "parent_actor_bound": len(cache),
                      "later_parent_guard": len(jobs)}, sort_keys=True))


if __name__ == "__main__":
    prepare()
