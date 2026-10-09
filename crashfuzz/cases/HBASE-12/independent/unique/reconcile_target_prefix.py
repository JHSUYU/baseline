#!/usr/bin/env python3
"""Repair early pilot I/O novelty to use only I/O before the B3 guard."""

from pathlib import Path
import json
import shutil
import campaign

BASE = Path(__file__).resolve().parent
state_path = BASE / "campaign-state.json"
state = json.loads(state_path.read_text())
backup = BASE / "repair-before-target-prefix.json"
if backup.exists():
    raise SystemExit("repair was already run")
shutil.copy2(state_path, backup)

healthy = campaign.observations(BASE / "gf_healthy.log")
healthy_targets = campaign.b3_events(BASE / "gf_healthy.log")
last_healthy = max(t["exit_position"] for t in healthy_targets)
healthy_io = [p for p in healthy["points"] if p["position"] < last_healthy]
families = {p["family"] for p in healthy_io}
io_ids = {p["id"] for p in healthy_io}
updated = {}

for name in state["completed"]:
    path = campaign.CHECKPOINTS / (name + ".json")
    row = json.loads(path.read_text())
    obs = campaign.observations(BASE / (name + ".log"))
    targets = campaign.b3_events(BASE / (name + ".log"))
    last = max((t["exit_position"] for t in targets), default=-1)
    relevant = [p for p in obs["points"] if p["position"] < last]
    current = {p["family"] for p in relevant}
    row["observed_io_points"] = len(relevant)
    row["observed_stable_families"] = len(current)
    valid = (row["strict_identity_match"] and row["target_after_fault"]
             and row["elapsed_seconds"] is not None)
    row["new_stable_families"] = sorted(current - families) if valid else []
    row["io_feedback_scope"] = "before_last_B3_target_exit"
    campaign.save(path, row)
    updated[name] = row
    if valid:
        families |= current
        io_ids |= {p["id"] for p in relevant}

state["seen_stable_families"] = sorted(families)
state["seen_io_ids"] = sorted(io_ids)
for item in state["queue"]:
    parent = updated.get(item["parent"])
    bonus = (min(20, 4 * len(parent["new_production_probes"])
                 + 5 * len(parent["new_stable_families"])) if parent else 0)
    item["base_score"] = campaign.source_score(item["faults"][-1]) + bonus
campaign.save(state_path, state)
print("REPAIRED", len(state["completed"]), "completed trials,",
      len(families), "target-prefix families")
