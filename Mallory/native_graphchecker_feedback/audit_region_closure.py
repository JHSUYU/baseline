"""Read-only audit of exact fault membership in an original Finalizer plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from Mallory.native_graphchecker_feedback.region_state_graph import (
    _plan_identity_rows, _rows, _sha,
)
from Mallory.native_graphchecker_feedback.artifacts import region_plan_path


def audit(campaign: Path, engine_jar: Path) -> dict:
    trials = campaign / "trials"
    items = []
    for trial in sorted(trials.glob("r*/result.json")):
        directory = trial.parent
        result = json.loads(trial.read_text(encoding="utf-8"))
        if not (result.get("strict_injection") is True and
                result.get("native_target_retained") is True):
            continue
        summary = json.loads((directory / "native-summary.json").read_text(
            encoding="utf-8"))
        if summary.get("provenance", {}).get("engineJarSha256") != _sha(engine_jar):
            raise ValueError(f"original engine pin differs: {directory}")
        if (result.get("native_session_sha256") and
                result["native_session_sha256"] != _sha(directory / "native-summary.json")):
            raise ValueError(f"native summary pin differs: {directory}")
        plan_path = region_plan_path(directory / "original-graph/recorded")
        if summary.get("provenance", {}).get("regionPlanSha256") != _sha(plan_path):
            raise ValueError(f"original Finalizer plan pin differs: {directory}")
        plans = [row for row in _rows(plan_path) if row.get("kind") ==
                 "CONCOLIC_REGION_PLAN"]
        members = _plan_identity_rows(plan_path, engine_jar, plans)
        expected_targets = set(result["native_target_occurrence_ids"])
        evidence = summary.get("targetEvidence", {})
        selected_address = evidence.get("selectedOccurrenceAddress")
        selected_ids = [identifier for identifier, plan in members.items()
                        if plan.get("occurrenceId") == selected_address]
        # A resolver selects one exact target activation. Other TARGET_CHECK
        # receipts may name different activations or actors and need not be
        # in that activation's Finalizer plan. The selected receipt must be.
        if (len(selected_ids) != 1 or
                set(evidence.get("targetCheckOccurrenceIds", [])) != expected_targets or
                selected_ids[0] not in expected_targets or
                set(summary.get("closureOccurrenceIds", [])) != set(members)):
            raise ValueError(f"selected target absent from original Finalizer plan: {directory}")
        events_path = directory / "iteration-native/fault-events.jsonl"
        if summary.get("provenance", {}).get("faultEventsSha256") != _sha(events_path):
            raise ValueError(f"runtime fault events pin differs: {directory}")
        events = list(_rows(events_path))
        if not any(row.get("kind") == "TARGET_CHECK" and
                   row.get("siteId") == summary.get("targetSiteId") and
                   row.get("node") == evidence.get("physicalActor") and
                   row.get("actorEpochOrdinal") == evidence.get(
                       "actorEpochOrdinal") and
                   row.get("occurrenceId") == selected_ids[0]
                   for row in events):
            raise ValueError(f"selected target lacks exact runtime check: {directory}")
        applied = [row for row in events if row.get("kind") == "FAULT_APPLIED"]
        doors = [row for row in events if row.get("kind") == "FAULT_DOOR"]
        if not applied:
            raise ValueError(f"strict trial lacks applied fault: {directory}")
        corrected = applied[-1]["occurrenceId"] in members
        items.append({
            "trial": directory.name,
            "originalPlanSha256": _sha(plan_path),
            "faultEventsSha256": _sha(events_path),
            "closureOccurrenceCount": len(members),
            "selectedTargetOccurrenceId": selected_ids[0],
            "observedTargetOccurrenceCount": len(expected_targets),
            "observedTargetIdsOutsideClosure": sorted(expected_targets - members.keys()),
            "observedDoorCount": len(doors),
            "observedClosureDoorCount": sum(row.get("occurrenceId") in members
                                            for row in doors),
            "reportedLastFaultInClosure": result.get("fault_in_target_closure"),
            "correctedLastFaultInClosure": corrected,
            "lastFaultOccurrenceId": applied[-1]["occurrenceId"],
            "targetTemporalAdmitted": result.get("target_temporal_admitted"),
            "targetExceptionTriggered": result.get("target_exception_triggered"),
        })
    return {
        "kind": "READ_ONLY_REGION_STATE_CLOSURE_AUDIT",
        "campaign": str(campaign.resolve(strict=True)),
        "engineJarSha256": _sha(engine_jar),
        "strictTargetRetainedTrials": len(items),
        "reportedLastFaultInClosure": sum(row["reportedLastFaultInClosure"] is True
                                          for row in items),
        "correctedLastFaultInClosure": sum(row["correctedLastFaultInClosure"]
                                           for row in items),
        "observedClosureDoors": sum(row["observedClosureDoorCount"]
                                    for row in items),
        "trials": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("engine_jar", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    result = audit(arguments.campaign, arguments.engine_jar)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "strictTargetRetainedTrials", "reportedLastFaultInClosure",
        "correctedLastFaultInClosure", "observedClosureDoors")},
        sort_keys=True))


if __name__ == "__main__":
    main()
