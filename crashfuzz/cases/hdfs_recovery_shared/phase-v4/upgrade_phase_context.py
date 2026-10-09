#!/usr/bin/env python3
"""Add an original-JUnit file-phase seed to the resumable v4 queue once."""

from __future__ import annotations

import fcntl
import json
from pathlib import Path

import campaign


SEED = campaign.HERE / "healthy-file-phase"


def infer_old_file_phases(trial: dict) -> list[str]:
    trace = campaign.rows(Path(trial["run"]))
    phases = []
    for event in trace:
        if event.get("event") != "FAULT_APPLIED" or not event.get(
                "marker", "").startswith("FAULT:HDFS_FILE:"):
            continue
        root = campaign.recovery_root(event)
        passed_active_guard = any(
            row.get("event") == "TARGET_CHECK"
            and row.get("caseId") == "HDFS-29"
            and row.get("occurrenceAddress") == root
            and row.get("seq", -1) < event["seq"]
            for row in trace)
        phase = ("updateReplicaUnderRecovery" if passed_active_guard
                 else "initReplicaRecovery")
        if phase == "updateReplicaUnderRecovery" and event.get(
                "sourceKey") != event.get("originSourceKey"):
            raise RuntimeError("cannot verify remote update owner in " + trial["run"])
        if phase == "initReplicaRecovery" and event.get("hitOrdinal") != 1:
            raise RuntimeError("unexpected pre-guard file ordinal in " + trial["run"])
        if phase == "updateReplicaUnderRecovery" and event.get("hitOrdinal", 0) < 2:
            raise RuntimeError("unexpected post-guard file ordinal in " + trial["run"])
        phases.append(phase)
    return phases


def main() -> None:
    with campaign.LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(campaign.STATE.read_text())
        if str(SEED) in state["healthy_dirs"]:
            print("file-phase calibration already present")
            return
        manifest = json.loads((SEED / "manifest.json").read_text())
        trace = campaign.rows(SEED)
        if manifest["returncode"] != 0 or not manifest["instrumented"]:
            raise RuntimeError("file-phase original JUnit seed failed")
        for case in campaign.CASES:
            checks = [row for row in trace if row.get("event") == "TARGET_CHECK"
                      and row.get("caseId") == case
                      and row.get("siteId") == campaign.TARGET_SITE[case]]
            if not checks or any(row.get("outcome") is not False for row in checks):
                raise RuntimeError("missing nonfatal guard for " + case)
        file_points = [row for row in trace if row.get("event") ==
                       "FAULT_POINT_OBSERVED" and row.get("marker", "").startswith(
                           "FAULT:HDFS_FILE:")]
        phases = {row.get("filePhase") for row in file_points}
        if phases != {"initReplicaRecovery", "updateReplicaUnderRecovery"}:
            raise RuntimeError("file phases not independently observed")
        if any(row["filePhase"] == "updateReplicaUnderRecovery" and
               row["sourceKey"] != row["originSourceKey"] for row in file_points):
            raise RuntimeError("unsupported remote update was recorded")

        historic = []
        for trial in state["completed"]:
            phases_for_trial = infer_old_file_phases(trial)
            trial["file_phases"] = phases_for_trial
            trial["file_phase_evidence"] = (
                "source_order_inferred_from_HDFS29_guard_and_hit_ordinal"
                if phases_for_trial else "no_file_fault")
            historic.extend(phases_for_trial)

        state["healthy_dirs"].append(str(SEED))
        state["healthy_seconds"] = round(
            state["healthy_seconds"] + manifest["elapsed_seconds"], 3)
        for category in campaign.COVERAGE:
            observed = campaign.covered(SEED, category)
            state["healthy_coverage"][category] = sorted(
                set(state["healthy_coverage"][category]) | observed)
            for case in campaign.CASES:
                state["coverage"][case][category] = sorted(
                    set(state["coverage"][case][category]) | observed)
        families = {campaign.family(row) for row in trace if
                    row.get("event") == "FAULT_POINT_OBSERVED" and
                    row.get("marker", "").startswith("FAULT:")}
        for case in campaign.CASES:
            state["io_families"][case] = sorted(
                set(state["io_families"][case]) | families)
        for event in trace:
            if (event.get("event") == "FAULT_POINT_OBSERVED" and
                    campaign.relevant_recovery_io(event, trace)):
                for kind in campaign.fault_kinds(event):
                    campaign.enqueue(state, [campaign.point(event, kind)])
        state["phase_calibration"] = {
            "seed": str(SEED),
            "elapsed_seconds": manifest["elapsed_seconds"],
            "file_points": len(file_points),
            "init_points": sum(row["filePhase"] == "initReplicaRecovery"
                               for row in file_points),
            "local_update_points": sum(row["filePhase"] ==
                                       "updateReplicaUnderRecovery"
                                       for row in file_points),
            "historical_file_fault_phases_inferred": historic,
            "inference": "released source puts replica init before HDFS-29 and "
                         "local replica update after it; original JUnit calibration "
                         "confirms ordinals 1 versus 2/3",
        }
        campaign.atomic_json(campaign.STATE, state)
        campaign.write_result(state)
        print(json.dumps({"file_points": len(file_points),
                          "queue": len(state["queue"]),
                          "completed": len(state["completed"])}))


if __name__ == "__main__":
    main()
