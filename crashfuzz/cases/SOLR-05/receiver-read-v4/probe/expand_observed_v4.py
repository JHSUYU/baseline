#!/usr/bin/env python3
"""At queue exhaustion, add only untried selectors observed in audited raw runs."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from audit_v4 import CASE, EVIDENCE, trace_events, trial
from campaign_v4 import ROOT, STATE, atomic, eligible_pairs, key, plan_id, selector, utc


def candidates(state: dict) -> list[dict]:
    known = set(state["seen_plans"]) | {
        plan_id(row["plan"]) for row in state["queue"]}
    output = {}
    source_dirs = [EVIDENCE / "healthy-001", EVIDENCE / "healthy-002"]
    source_dirs += [CASE / row["evidence"] for row in state["trials"]
                    if row["audit"]["effective"]]
    for directory in source_dirs:
        events = trace_events(directory / "events.tsv")
        eligible = {p["read"]["seq"] for p in eligible_pairs(events)}
        all_count = Counter()
        for event in events:
            if event["kind"] != "RECEIVER_IO_OBSERVED":
                continue
            identity = key(event)
            all_count[identity] += 1
            if event["seq"] not in eligible:
                continue
            plan = [selector(event, all_count[identity])]
            token = plan_id(plan)
            if token not in known:
                output.setdefault(token, {"plan": plan, "priority": 400,
                    "reason": f"untried original or effective raw read: {directory.name}"})
        corresponding = next((row for row in state["trials"]
                              if CASE / row["evidence"] == directory), None)
        if corresponding is None or len(corresponding["plan"]) >= state["budget"]["max_faults"]:
            continue
        checked = trial(directory, corresponding["plan"])
        if not (checked["strict"] and checked["effective"]):
            continue
        final = max(e["seq"] for e in events if e["kind"] == "IO_APPLIED_CONNECTION_LOSS")
        relative, global_count = Counter(), Counter()
        for event in events:
            if event["kind"] != "RECEIVER_IO_OBSERVED":
                continue
            identity = key(event)
            global_count[identity] += 1
            if event["seq"] > final:
                relative[identity] += 1
            if event["seq"] <= final or event["seq"] not in eligible:
                continue
            plan = corresponding["plan"] + [selector(event, relative[identity],
                after="F" + str(len(corresponding["plan"]) - 1),
                global_hit=global_count[identity])]
            token = plan_id(plan)
            if token not in known:
                output.setdefault(token, {"plan": plan,
                    "priority": 200 + 30 * len(plan),
                    "reason": f"untried post-fault read and later target: {directory.name}"})
    return sorted(output.values(), key=lambda row: (-row["priority"], plan_id(row["plan"])))


def main() -> None:
    before = STATE.read_bytes()
    state = json.loads(before)
    if (state["status"] != "queue_exhausted_before_goal" or state["inflight"] is not None or
            state["queue"] or state["effective"] >= state["budget"]["effective_goal"]):
        raise RuntimeError("expand only from a complete, below-goal scope exhaustion")
    subprocess.run([sys.executable, str(CASE / "probe/audit_campaign_v4.py")], check=True)
    audit = json.loads((ROOT / "independent-raw-audit.json").read_text())
    if (audit["checkpoint_sha256"] != hashlib.sha256(before).hexdigest() or
            audit["errors"] or audit["inflight"]):
        raise RuntimeError("independent raw audit does not match complete checkpoint")
    new = candidates(state)
    report = {"case": "SOLR-05", "utc": utc(),
              "scope_exhaustion_checkpoint_sha256": hashlib.sha256(before).hexdigest(),
              "observed_untried": len(new), "new_plan_ids": [plan_id(x["plan"]) for x in new],
              "old_completed": len(state["trials"]), "old_effective": state["effective"],
              "original_run_repeated": False}
    suffix = len(state.get("observed_expansions", [])) + 1
    snapshot = ROOT / f"scope-exhaustion-before-expansion-{suffix}.json"
    snapshot.write_bytes(before)
    if new:
        state["queue"] = new
        state["status"] = "running"
        state.setdefault("observed_expansions", []).append(report)
        state["updated_at_utc"] = utc()
        if STATE.read_bytes() != before:
            raise RuntimeError("checkpoint changed while preparing expansion")
        atomic(STATE, state)
        report["new_checkpoint_sha256"] = hashlib.sha256(STATE.read_bytes()).hexdigest()
    report["snapshot"] = str(snapshot.relative_to(CASE))
    (ROOT / f"observed-expansion-{suffix}.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
