#!/usr/bin/env python3
"""Audit phase 2 I/O novelty at the 64-trial budget extension.

Ordinal identifies a replay event, but it does not define a new I/O family.
This script replays the sequential checkpoint order against the healthy trace.
"""

from pathlib import Path
import json
import sys


BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import fuzz_phase2 as fuzz  # noqa: E402


def keys(path: Path) -> dict[str, dict]:
    found = {}
    with path.open(errors="replace") as stream:
        for line in stream:
            if "FAULT_POINT_OBSERVED" not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "FAULT_POINT_OBSERVED":
                continue
            point = fuzz.point(row)
            if fuzz.nearby(point):
                found[fuzz.point_key(point)] = point
    return found


def stable_key(point: dict) -> str:
    return json.dumps([point[name] for name in
                       ("marker", "siteId", "occurrence", "sourceKey")],
                      separators=(",", ":"))


def semantic_key(point: dict) -> str:
    # Conservative cross-context family: event, bytecode site, resource key.
    return json.dumps([point[name] for name in
                       ("marker", "siteId", "sourceKey")],
                      separators=(",", ":"))


def main() -> None:
    state = json.loads((BASE / "state.json").read_text())
    healthy = keys(BASE / "trace-healthy/runtime_trace.jsonl")
    healthy_full_count = len(healthy)
    seen_full = set(healthy)
    seen_stable = {stable_key(point) for point in healthy.values()}
    seen_semantic = {semantic_key(point) for point in healthy.values()}
    records = []
    effective_ids = []
    for name in state["completed"]:
        cp = json.loads((BASE / "checkpoint" / (name + ".json")).read_text())
        if fuzz.is_effective(cp, 6):
            effective_ids.append(name)
        points = keys(BASE / ("trace-" + name) / "runtime_trace.jsonl")
        new_full = [point for key, point in points.items() if key not in seen_full]
        new_stable = [point for point in points.values()
                      if stable_key(point) not in seen_stable]
        new_semantic = [point for point in points.values()
                        if semantic_key(point) not in seen_semantic]
        records.append({
            "trial": name,
            "effective_at_max6": fuzz.is_effective(cp, 6),
            "checkpoint_new_io_full_identities": cp.get("new_io_points"),
            "new_full_identities": len(new_full),
            "new_stable_site_context_resource_families": len({stable_key(p) for p in new_stable}),
            "new_semantic_site_resource_families": len({semantic_key(p) for p in new_semantic}),
            "new_full_examples": [
                {k: p[k] for k in ("marker", "siteId", "occurrence", "sourceKey", "hitOrdinal")}
                for p in new_full[:8]],
            "new_stable_examples": [
                {k: p[k] for k in ("marker", "siteId", "occurrence", "sourceKey", "hitOrdinal")}
                for p in new_stable[:8]],
        })
        seen_full.update(points)
        seen_stable.update(stable_key(p) for p in points.values())
        seen_semantic.update(semantic_key(p) for p in points.values())
        if len(effective_ids) == 59:
            break  # Five effective phase 1 runs precede these phase 2 runs.
    extension_window = effective_ids[-16:]
    window_records = [row for row in records if row["trial"] in extension_window]
    audit = {
        "method": "Healthy and sequential faulted traces; stable family removes hitOrdinal; semantic family also removes occurrenceAddress while retaining sourceKey.",
        "healthy_full_identities": healthy_full_count,
        "extension_phase2_effective_index": 59,
        "extension_window_trials": extension_window,
        "raw_new_full_identity_trials": sum(row["checkpoint_new_io_full_identities"] > 0 for row in window_records),
        "stable_new_family_trials": sum(row["new_stable_site_context_resource_families"] > 0 for row in window_records),
        "semantic_new_family_trials": sum(row["new_semantic_site_resource_families"] > 0 for row in window_records),
        "window_records": window_records,
    }
    output = BASE / "io_novelty_audit.json"
    output.write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps({k: audit[k] for k in (
        "extension_window_trials", "raw_new_full_identity_trials",
        "stable_new_family_trials", "semantic_new_family_trials")}, indent=2))
    print("detail", output)


if __name__ == "__main__":
    main()
