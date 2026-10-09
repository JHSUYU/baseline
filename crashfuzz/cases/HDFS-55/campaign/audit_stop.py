#!/usr/bin/env python3
"""Re-audit completed exact plans and stop after independent known-bug detection."""

import json
from pathlib import Path
import campaign

HERE = Path(__file__).resolve().parent


def main():
    state = json.loads(campaign.STATE.read_text())
    if state["status"] not in ("running", "stopped_after_known_bug_reproduction"):
        raise SystemExit("unexpected exact-plan campaign status")
    original = list(state["trials"])
    if not original:
        raise SystemExit("no completed exact trials")
    state["trials"] = []
    for old in original:
        directory = campaign.RUNS / old["id"]
        row = campaign.parse_trial(old["sequence"], directory,
                                   campaign.cumulative_coverage(state))
        row.update({"id": old["id"], "sequence": old["sequence"],
                    "parent": old.get("parent"),
                    "recovered_existing_run": old.get("recovered_existing_run", False),
                    "re_audited_after_stop": True})
        state["trials"].append(row)
    uncheckpointed = [directory for directory in campaign.RUNS.iterdir()
                      if (directory / "manifest.json").is_file() and
                      directory.name not in {row["id"] for row in state["trials"]}]
    for directory in sorted(uncheckpointed):
        sequence = [int(x) for x in directory.name.removeprefix("p").split("_")]
        if campaign.trial_name(sequence) != directory.name:
            raise SystemExit("unexpected uncheckpointed plan name: " + directory.name)
        candidate = next((x for x in state["queue"] if x["sequence"] == sequence), None)
        if candidate is None:
            raise SystemExit("completed run absent from checkpoint queue: " + directory.name)
        state["queue"].remove(candidate)
        row = campaign.parse_trial(sequence, directory,
                                   campaign.cumulative_coverage(state))
        row.update({"id": directory.name, "sequence": sequence,
                    "parent": candidate.get("parent"),
                    "recovered_existing_run": True,
                    "re_audited_after_stop": True})
        state["trials"].append(row)
        campaign.generate_children(state, row)
        state["campaign_elapsed_wall_seconds"] += row["elapsed_seconds"]
    state["status"] = "stopped_after_known_bug_reproduction"
    state["stop_reason"] = ("A separate DN-wire persistent cached-DEK policy produced "
                            "an operation failure and passing minimal-fix replay; "
                            "exact ordinal queue remains resumable.")
    campaign.atomic(campaign.STATE, state)
    campaign.ledger(state)
    print(json.dumps({"status": state["status"], "trials": len(state["trials"]),
                      "queue_remaining": len(state["queue"]),
                      "recovered_completed_runs": [p.name for p in uncheckpointed]}))


if __name__ == "__main__":
    main()
