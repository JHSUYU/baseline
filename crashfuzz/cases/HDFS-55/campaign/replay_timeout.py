#!/usr/bin/env python3
"""Preserve the p3 JVM timeout and replay its exact plan with bounded exit."""

import json
import shutil
import subprocess
import sys

import campaign


def main():
    state = json.loads(campaign.STATE.read_text())
    if state["status"] == "running":
        raise SystemExit("wait for the current campaign process before editing its checkpoint")
    old = next(row for row in state["trials"] if row["id"] == "p3")
    if old["returncode"] != 124:
        raise SystemExit("p3 is not the recorded timeout")
    preserved = campaign.HERE / "harness-timeout/p3"
    if not preserved.exists():
        shutil.copytree(campaign.RUNS / "p3", preserved)
    # Reparse every completed run with the corrected order and timeout
    # criteria. Preserve the raw trial and its source/plan lineage.
    audited = []
    for prior in state["trials"]:
        parsed = campaign.parse_trial(prior["sequence"],
                                      campaign.RUNS / prior["id"],
                                      campaign.cumulative_coverage({"trials": audited}))
        parsed.update({key: prior[key] for key in
                       ("id", "sequence", "parent", "recovered_existing_run")})
        if prior["id"] == "p3":
            parsed["timeout_evidence"] = str(preserved.relative_to(campaign.CASE))
        audited.append(parsed)
    state["trials"] = audited
    accepted = {row["id"] for row in audited if row["result"] == "target_retaining"}
    state["queue"] = [candidate for candidate in state["queue"]
                      if candidate["parent"] is None or candidate["parent"] in accepted]
    campaign.atomic(campaign.STATE, state)
    campaign.ledger(state)

    replay = campaign.RUNS / "p3-replay"
    was_existing = (replay / "manifest.json").is_file()
    if not was_existing:
        replay.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(campaign.CASE / "run_control.py"),
                   "--output", str(replay), "--overlay", str(campaign.OVERLAY),
                   "--inject", "--plan", str(campaign.plan_path([3]))]
        with (campaign.HERE / "p3-replay.runner.log").open("w") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
    if any(row["id"] == "p3-replay" for row in state["trials"]):
        return
    row = campaign.parse_trial([3], replay, campaign.cumulative_coverage(state))
    row.update({"id": "p3-replay", "sequence": [3], "parent": "p3-timeout",
                "replay_of": "p3", "recovered_existing_run": was_existing})
    state["trials"].append(row)
    state["campaign_elapsed_wall_seconds"] += row["elapsed_seconds"]
    campaign.generate_children(state, row)
    campaign.atomic(campaign.STATE, state)
    campaign.ledger(state)
    print(json.dumps({"replayed": row["id"], "result": row["result"],
                      "returncode": row["returncode"],
                      "coverage_complete": row["coverage_complete"],
                      "elapsed_seconds": row["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
