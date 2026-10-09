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
    if len(applied) != len(plan) or len(matched) != len(plan):
        return False
    endpoints_by_call: dict[str, set[str]] = {}
    for index, (expected, event, match) in enumerate(zip(plan, applied, matched)):
        fields = expected.split("|")
        if len(fields) != 5:
            return False
        parts = event["parts"]
        if (event["kind"] != "IO_APPLIED" or len(parts) < 9 or
                match["kind"] != "IO_MATCHED" or
                match["seq"] + 1 != event["seq"] or
                match["parts"] != parts):
            return False
        if tuple(parts[:2]) != tuple(fields[:2]):
            return False
        metadata = dict(item.split("=", 1) for item in parts[2:] if "=" in item)
        if (metadata.get("call") != fields[2] or
                metadata.get("attempt") != fields[3] or
                metadata.get("fault_kind") != fields[4] or
                metadata.get("fault_id") != f"F{index}" or
                metadata.get("previous_fault_id") !=
                (f"F{index - 1}" if index else "<none>") or
                metadata.get("plan_index") != str(index)):
            return False
        if not metadata.get("endpoint"):
            return False
        endpoints = endpoints_by_call.setdefault(fields[2], set())
        if metadata["endpoint"] in endpoints:
            return False
        endpoints.add(metadata["endpoint"])
        observed = [item for item in trial_events
                    if item["kind"] == "IO_OBSERVED" and
                    item["seq"] < event["seq"] and
                    item["parts"][:2] == parts[:2] and
                    f"call={fields[2]}" in item["parts"] and
                    f"attempt={fields[3]}" in item["parts"]]
        if len(observed) != 1 or observed[0]["seq"] + 1 != match["seq"]:
            return False
        if index and applied[index - 1]["seq"] >= event["seq"]:
            return False
    return True
