#!/usr/bin/env python3
"""Read-only V4 ancestry import and parent-raw classification; no JUnit."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import v5_model as model

HERE = Path(__file__).resolve().parent
V4 = HERE.parent / "phase-v4"
STATE = HERE / "campaign-state.json"
EXPECTED_V4_SHA = "c990b52036d45f25a4370c611a2254fa3bdd580853a392226909ad04dd3a2b1b"
FILES = ("campaign-state.json", "campaign.py", "run_original.py", "RecoveryProbe.java",
         "PatchRecovery.java", "CoverageRecovery.java", "final-audit.json",
         "raw-evidence.tar.gz")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def trace_rows(directory: str) -> list[dict]:
    return [json.loads(line) for line in (Path(directory) / "runtime_trace.jsonl").read_text().splitlines()
            if line]


def classify(v4: dict) -> tuple[list[dict], dict]:
    completed = v4["completed"]
    strict = defaultdict(list)
    historical_attempts = defaultdict(int)
    strict_ids = set()
    for trial in completed:
        historical_attempts[trial["id"]] += 1
        if trial["exact_order_applied"]:
            strict_ids.add(trial["id"])
            strict[tuple(model.legacy_parent_key(p) for p in trial["sequence"])].append(trial)
    cache: dict[str, list[dict]] = {}
    migrated = []
    counters = {case: 0 for case in model.CASES}
    unresolved = []
    for original in v4["queue"]:
        item = dict(original)
        if item["id"] in strict_ids:
            raise RuntimeError("V4 pending plan already strictly injected")
        if historical_attempts[item["id"]] > 2:
            raise RuntimeError("V4 unmatched retry limit exceeded")
        item["legacy_unmatched_attempts"] = historical_attempts[item["id"]]
        item["expectedEpisode"] = 1  # provisional; two V5 healthy seeds must verify
        item["pre_target_cases"] = []
        item["owner_evidence"] = []
        item["lane"] = "exploration"
        if len(item["sequence"]) == 2:
            key = tuple(model.legacy_parent_key(p) for p in item["sequence"][:-1])
            parents = strict.get(key, [])
            if not parents:
                unresolved.append(item["id"])
            for parent in parents:
                trace = cache.setdefault(parent["run"], trace_rows(parent["run"]))
                for io in trace:
                    if io.get("seq", -1) <= parent["last_applied_seq"]:
                        continue
                    if not model.observed(io, item["sequence"][-1]):
                        continue
                    for case in model.CASES:
                        targets = [row for row in trace if row.get("event") == "TARGET_CHECK"
                                   and row.get("caseId") == case and row.get("siteId") == model.SITES[case]
                                   and row.get("seq", -1) > io["seq"]
                                   and model.legacy_same_owner(io, row)]
                        for target in targets:
                            item["owner_evidence"].append({
                                "parent_run": parent["run"], "parent_id": parent["id"],
                                "io_seq": io["seq"], "target_seq": target["seq"],
                                "case": case, "originSourceKey": model.origin(io),
                                "blockId": io.get("blockId"), "recoveryRoot": model.root(io),
                                "bpid_from_target": target.get("bpid"),
                                "recoveryId_from_target": target.get("recoveryId")})
            item["pre_target_cases"] = sorted({row["case"] for row in item["owner_evidence"]})
            if any(case in item["pre_target_cases"] for case in ("HDFS-29", "HDFS-30")):
                item["lane"] = "same_owner_second_fault"
            for case in item["pre_target_cases"]:
                counters[case] += 1
        migrated.append(item)
    if len({item["id"] for item in migrated}) != len(migrated):
        raise RuntimeError("duplicate V4 pending plan IDs")
    if (len(completed), len(strict_ids), len(migrated), counters) != (
            128, 63, 789, {"HDFS-28": 0, "HDFS-29": 196, "HDFS-30": 196}):
        raise RuntimeError("V4 ancestry or parent-raw classification changed: " + str(counters))
    return migrated, {"strict_ids": sorted(strict_ids),
                      "historical_attempts_by_id": dict(historical_attempts),
                      "unresolved_parent_or_io": sorted(unresolved),
                      "pre_target_pair_by_case": counters,
                      "raw_parent_traces_read": len(cache)}


def migrate() -> dict:
    if STATE.exists():
        raise RuntimeError("V5 state exists; migration is one-shot and must not reset a checkpoint")
    hashes = {name: sha(V4 / name) for name in FILES}
    if hashes["campaign-state.json"] != EXPECTED_V4_SHA:
        raise RuntimeError("archived V4 state SHA changed")
    v4 = json.loads((V4 / "campaign-state.json").read_text())
    if v4.get("active") is not None or v4.get("stop_reason") != "budget":
        raise RuntimeError("V4 is not at a completed-trial boundary")
    queue, classification = classify(v4)
    ancestry = [{"attempt": index, "id": trial["id"], "run": trial["run"],
                 "exact_order_applied": trial["exact_order_applied"],
                 "post_fault_target_checks": trial["post_fault_target_checks"],
                 "junit_exit": trial["junit_exit"]}
                for index, trial in enumerate(v4["completed"], 1)]
    effective = {case: sum(bool(trial["exact_order_applied"] and
                                trial["post_fault_target_checks"][case])
                           for trial in v4["completed"]) for case in model.CASES}
    if effective != {"HDFS-28": 18, "HDFS-29": 39, "HDFS-30": 39}:
        raise RuntimeError("historical effective counts changed")
    cases = {case: {"attempts": 128, "effective": effective[case],
                    "effective_goal": 80, "attempt_cap": 320, "max_faults": 8,
                    "status": "awaiting_calibration", "extension_reason": None,
                    "target_exception_trials_v5": 0} for case in model.CASES}
    state = {"schema": "hdfs-recovery-v5-1", "created_at": time.time(),
             "migration": {"v4_dir": str(V4), "v4_sha256": hashes,
                           "v4_completed_receipts": ancestry,
                           "v4_attempts": 128, "v4_effective": effective,
                           "v4_strict_attempts": 63, "queue_classification": classification,
                           "calibration_required": True},
             "cases": cases, "queue": queue,
             "seen_sequences": list(v4["seen_sequences"]),
             "strict_ids": classification["strict_ids"],
             "legacy_coverage": v4["coverage"],
             "coverage_v5": {case: {key: [] for key in ("probes", "methods", "branch_counts")}
                             for case in model.CASES},
             "io_families_v5": {case: [] for case in model.CASES},
             "completed_v5": [], "v5_attempts": 0, "active": None,
             "stop_reason": "awaiting_two_healthy_calibrations"}
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
    temporary.replace(STATE)
    return state


if __name__ == "__main__":
    state = migrate()
    print(json.dumps({"state": str(STATE), "v4_sha256": EXPECTED_V4_SHA,
                      "v4_attempts": 128,
                      "effective": {case: state["cases"][case]["effective"] for case in model.CASES},
                      "pending": len(state["queue"]),
                      "lanes": {name: sum(q["lane"] == name for q in state["queue"])
                                for name in ("same_owner_second_fault", "exploration")}},
                     sort_keys=True))
