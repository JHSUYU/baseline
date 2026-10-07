#!/usr/bin/env python3
"""Recount V3 original JUnit trials from raw actor/location and JaCoCo files."""

from __future__ import annotations

import json
from pathlib import Path

from campaign import (CAMPAIGN, COVERAGE, FILE, HERE, SELECTOR, STATE,
                      TARGET, TARGET_THROW, covered, family, selectable,
                      sha256, trace)


def check_bindings(rows: list[dict]) -> int:
    locations = [row for row in rows if row.get("event") == "BLOCK_LOCATION"]
    checked = 0
    for event in rows:
        if (event.get("event") != "FAULT_POINT_OBSERVED" or
                event.get("marker") != "FAULT:HDFS_DATA_TRANSFER:READ" or
                not event.get("identityBound")):
            continue
        prior = [location for location in locations
                 if location["seq"] < event["seq"]
                 and location.get("blockId") == event.get("blockId")
                 and location.get("actorUuid") == event.get("actorUuid")
                 and location.get("file") == FILE]
        if not prior:
            raise AssertionError("bound read lacks prior raw block-location record")
        latest = max(prior, key=lambda row: row["seq"])
        if (event.get("actorKey") != "replica:" + str(latest["replicaIndex"])
                or event.get("resourceKey") != FILE + "@" + str(latest["startOffset"])):
            raise AssertionError("read actor/resource differs from raw response")
        checked += 1
    return checked


def audit() -> dict:
    state = json.loads(STATE.read_text())
    calibration = HERE / "healthy-v3-calibration.json"
    if state["schema_version"] != 3 or state["calibration_sha256"] != sha256(calibration):
        raise AssertionError("V3 checkpoint/calibration mismatch")
    if state["overlay_receipt_sha256"] != sha256(HERE / "build/receipt.json"):
        raise AssertionError("overlay changed after calibration")
    if len({row["id"] for row in state["completed"]}) != len(state["completed"]):
        raise AssertionError("duplicate completed plan")
    seeds = [HERE / "healthy-v3-a", HERE / "healthy-v3-b"]
    union = {category: set().union(*(covered(seed, category) for seed in seeds))
             for category in COVERAGE}
    io_union = set()
    actor_checks = 0
    for seed in seeds:
        manifest = json.loads((seed / "manifest.json").read_text())
        if manifest["returncode"] != 0 or manifest["test"] != state["original_junit"]:
            raise AssertionError("healthy original JUnit failed/mismatched")
        rows = trace(seed / "runtime_trace.jsonl")
        actor_checks += check_bindings(rows)
        io_union |= {family(row) for row in rows if selectable(row)}
    effective = 0
    strict = 0
    candidates = 0
    elapsed = 0.0
    for index, stored in enumerate(state["completed"], 1):
        directory = CAMPAIGN / "trials" / ("t%04d" % index)
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest["test"] != state["original_junit"]:
            raise AssertionError(f"trial {index} original JUnit mismatch")
        plan_lines = (directory / "faults.tsv").read_text().splitlines()
        if len(plan_lines) != len(stored["plan"]):
            raise AssertionError(f"trial {index} plan length mismatch")
        for line, point in zip(plan_lines, stored["plan"]):
            if line.split("\t") != [point["marker"], point["siteId"],
                                    point["actorKey"], point["resourceKey"],
                                    str(point["hitOrdinal"]), "pending",
                                    point["faultType"]]:
                raise AssertionError(f"trial {index} plan file differs")
        rows = trace(directory / "runtime_trace.jsonl")
        actor_checks += check_bindings(rows)
        applied = [row for row in rows if row.get("event") == "FAULT_APPLIED"]
        ordered = len(applied) == len(stored["plan"]) and all(
            event.get("faultIndex") == j and event.get("faultType") == point["faultType"]
            and event.get("identityBound") is True
            and all(event.get(field) == point[field] for field in SELECTOR)
            for j, (event, point) in enumerate(zip(applied, stored["plan"])))
        last = applied[-1]["seq"] if ordered else 1 << 60
        reached = any(row.get("event") == "TARGET_CHECK"
                      and row.get("siteId") == TARGET and row.get("file") == FILE
                      and row["seq"] > last for row in rows)
        hits = [row for row in rows if row.get("event") == "TARGET_THROW"
                and row.get("siteId") == TARGET_THROW
                and row.get("exception") == "java.io.EOFException"
                and row.get("file") == FILE and row["seq"] > last]
        valid = ordered and reached
        if (ordered != stored["strict"] or valid != stored["effective"]
                or len(hits) != stored["exact_target_throws"]):
            raise AssertionError(f"trial {index} strict/target/oracle mismatch")
        strict += ordered
        effective += valid
        candidates += len(hits) if valid else 0
        elapsed += manifest["elapsed_seconds"]
        if valid:
            for category in COVERAGE:
                union[category] |= covered(directory, category)
            io_union |= {family(row) for row in rows if selectable(row)}
    for category in COVERAGE:
        if union[category] != set(state["coverage"][category]):
            raise AssertionError("coverage union mismatch: " + category)
    if io_union != set(state["io_families"]):
        raise AssertionError("I/O family union mismatch")
    return {"case_id": "HDFS-01", "checkpoint_sha256": sha256(STATE),
            "completed": len(state["completed"]), "strict": strict,
            "effective": effective, "exact_target_throws": candidates,
            "raw_read_actor_joins": actor_checks,
            "elapsed_trial_seconds": round(elapsed, 3),
            "pending": len(state["queue"]), "stop_reason": state["stop_reason"]}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
