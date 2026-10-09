#!/usr/bin/env python3
"""Bind queued replica-file exceptions to the calibrated init/update phase."""

from __future__ import annotations

import fcntl
import json

import campaign


def annotate(sequence: list[dict]) -> list[dict]:
    result = []
    for fault in sequence:
        selected = dict(fault)
        if selected["marker"].startswith("FAULT:HDFS_FILE:"):
            phase = ("initReplicaRecovery" if selected["hitOrdinal"] == 1
                     else "updateReplicaUnderRecovery")
            if phase == "updateReplicaUnderRecovery" and selected[
                    "sourceKey"] != selected["originSourceKey"]:
                raise RuntimeError("unattributed remote update in pending selector")
            selected["filePhase"] = phase
        else:
            selected["filePhase"] = ""
        result.append(selected)
    return result


def main() -> None:
    with campaign.LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(campaign.STATE.read_text())
        if state.get("file_phase_selector_version") == "phase_v1":
            print("file-phase selectors already upgraded")
            return
        if not state.get("phase_calibration"):
            raise RuntimeError("phase calibration must be installed first")
        if state["active"] is not None:
            raise RuntimeError("stop campaign before upgrading selectors")
        seen = set(state["seen_sequences"])
        changed = 0
        unique = {}
        for item in state["queue"]:
            sequence = annotate(item["sequence"])
            identity = campaign.sequence_id(sequence)
            old_id = item["id"]
            if identity != old_id:
                changed += 1
            unique.setdefault(identity, {**item, "sequence": sequence,
                                         "id": identity})
            seen.add(identity)
        for trial in state["completed"]:
            seen.add(campaign.sequence_id(annotate(trial["sequence"])))
        state["queue"] = list(unique.values())
        state["seen_sequences"] = sorted(seen)
        state["file_phase_selector_version"] = "phase_v1"
        campaign.atomic_json(campaign.STATE, state)
        campaign.write_result(state)
        print(json.dumps({"queue": len(state["queue"]),
                          "changed": changed,
                          "completed": len(state["completed"])}))


if __name__ == "__main__":
    main()
