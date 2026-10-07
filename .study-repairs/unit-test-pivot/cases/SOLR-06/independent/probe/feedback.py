#!/usr/bin/env python3
"""Graph-free I/O-exception and coverage-guided campaign for SOLR-10/39/40."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import time


CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
CAMPAIGN = EVIDENCE / "campaign"
HEALTHY = EVIDENCE / "healthy-instrumented"
HEALTHY_CALLSITE = EVIDENCE / "healthy-callsite"
STATE = CAMPAIGN / "state.json"
RESULT = CASE / "result.json"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
RUN = CASE / "probe/run.py"
MAX_TRIALS = 80
MAX_FAULTS = 8


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def events(path: Path) -> list[dict]:
    output = []
    if not path.exists():
        return output
    for line in path.open():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 4:
            continue
        output.append({"seq": int(parts[0]), "kind": parts[2], "parts": parts[3:]})
    return output


def io_identity(event: dict) -> tuple[str, str] | None:
    if event["kind"] != "IO_OBSERVED" or len(event["parts"]) < 2:
        return None
    return event["parts"][0], event["parts"][1]


def feedback_identity(identity: tuple[str, str]) -> str:
    """Collapse ephemeral ZooKeeper sequence suffixes for novelty feedback only."""
    operation, path = identity
    path = re.sub(r"(?<=/)qn-\d+", "qn-*", path)
    path = re.sub(r"(?<=/)qnr-\d+", "qnr-*", path)
    path = re.sub(r"(?<=/election/)[^/]+", "<election>", path)
    path = re.sub(r"127\.0\.0\.1:\d+_solr", "<node>", path)
    path = re.sub(r"core_node\d+", "core_node*", path)
    path = re.sub(r"n_\d+", "n_*", path)
    return operation + "|" + path


def io_behavior_key(event: dict) -> str | None:
    """Stable I/O behavior: production caller, operation, normalized resource.

    The occurrence ordinal is used only to select the exact injection point.
    Older traces without caller identity cannot establish new I/O behavior.
    """
    identity = io_identity(event)
    if identity is None or len(event["parts"]) < 3:
        return None
    caller = event["parts"][2]
    if not caller.startswith("caller="):
        return None
    return caller[7:] + "|" + feedback_identity(identity)


def sequence_applied_in_order(plan: list[str], applied: list[dict],
                              matched: list[dict], trial_events: list[dict]) -> bool:
    if len(applied) != len(plan):
        return False
    seen_fault_ids = set()
    for index, (expected, event) in enumerate(zip(plan, applied)):
        fields = expected.split("|")
        if len(fields) not in (4, 6):
            return False
        parts = event["parts"]
        if len(parts) < 3 or not parts[2].startswith("ordinal="):
            return False
        if (parts[0], parts[1], parts[2].split("=", 1)[1]) != tuple(fields[:3]):
            return False
        metadata = dict(item.split("=", 1) for item in parts[3:] if "=" in item)
        if metadata.get("caller") != fields[3].replace("caller=", "", 1):
            return False
        if not metadata.get("fault_id"):
            # Historical, completed selectors predate phase anchors. Preserve
            # their original exact op/path/global-ordinal validation only.
            if len(fields) != 4:
                return False
            continue
        fault_id = f"F{index}"
        previous_id = f"F{index - 1}" if index else "<none>"
        if (metadata.get("fault_id") != fault_id or
                metadata.get("previous_fault_id") != previous_id or
                metadata.get("plan_index") != str(index) or
                fault_id in seen_fault_ids):
            return False
        seen_fault_ids.add(fault_id)
        try:
            global_hit = int(metadata["global_hit_ordinal"])
        except (KeyError, ValueError):
            return False
        if global_hit <= 0:
            return False
        observed = [item for item in trial_events
                    if item["kind"] == "IO_OBSERVED" and
                    item["seq"] < event["seq"] and
                    item["parts"][:2] == parts[:2]]
        if global_hit != len(observed):
            return False
        if len(fields) == 6:
            if (fields[4] != f"after={previous_id}" or
                    not fields[5].startswith("seed_global=") or
                    metadata.get("seed_global") != fields[5].split("=", 1)[1] or
                    metadata.get("relative_count") != fields[2][1:]):
                return False
            phase_start = applied[index - 1]["seq"]
            try:
                relative_hit = int(metadata["relative_count"])
            except (KeyError, ValueError):
                return False
            if relative_hit != sum(
                    item["seq"] > phase_start for item in observed):
                return False
        elif fields[2].startswith("@"):
            return False
    if any(any(part.startswith("fault_id=") for part in event["parts"])
           for event in applied):
        if len(seen_fault_ids) != len(plan) or len(matched) != len(plan):
            return False
        for match, injection in zip(matched, applied):
            if match["seq"] + 1 != injection["seq"] or match["parts"] != injection["parts"]:
                return False
    elif matched:
        return False
    return True
