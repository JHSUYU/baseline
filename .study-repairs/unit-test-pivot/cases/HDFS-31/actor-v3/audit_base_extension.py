#!/usr/bin/env python3
"""Report the exact last-eight novelty at the HDFS31 base-80 boundary.

This is an evidence report, not an automatic extension decision.  New branch
IDs are classified as candidates for source review; a human still reads the
production code and checks that a branch lies on the selected block-pool and
transfer path before allowing the conditional 128-effective stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import campaign
from audit_healthy import rows


TARGET_PREFIXES = (
    "org/apache/hadoop/hdfs/server/datanode/DataNode#getBPOSForBlock(",
    "org/apache/hadoop/hdfs/server/datanode/DataNode#transferBlock(",
    "org/apache/hadoop/hdfs/server/datanode/DataNode$BlockPoolManager#",
    "org/apache/hadoop/hdfs/server/datanode/BPOfferService#",
    "org/apache/hadoop/hdfs/server/datanode/BPServiceActor#",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_coverage(path: Path) -> set[str]:
    if not path.is_file():
        raise RuntimeError(f"missing raw coverage: {path}")
    return set(path.read_text().splitlines())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    anchor = args.anchor.resolve()
    state_path = anchor / "campaign-state.json"
    state = json.loads(state_path.read_text())
    if (state.get("schema") != "hdfs31-actor-v3-campaign-1"
            or state["effective"] < 80 or state["in_flight"] is not None):
        raise RuntimeError("not at a complete base-80 review boundary")
    effective = [identity for identity in state["completion_order"]
                 if state["completed"][identity]["result"]["valid_for_feedback"]]
    if len(effective) != state["effective"] or len(effective) < 80:
        raise RuntimeError("effective trial accounting differs from checkpoint")
    earlier, recent = effective[:72], effective[72:80]
    before_branches = require_coverage(anchor / "healthy-a" / "covered_branch_counts.txt")
    before_io = {campaign.family(row) for row in campaign.eligible_io(
        rows(anchor / "healthy-a" / "runtime_trace.jsonl"))}
    for identity in earlier:
        before_branches.update(require_coverage(
            anchor / "runs" / identity / "attempt-1" / "covered_branch_counts.txt"))
        before_io.update(campaign.family(row) for row in campaign.eligible_io(
            rows(anchor / "runs" / identity / "attempt-1" / "runtime_trace.jsonl")))
    new_branches: set[str] = set()
    new_io: set[str] = set()
    trial_rows = []
    for identity in recent:
        run = anchor / "runs" / identity / "attempt-1"
        current = require_coverage(run / "covered_branch_counts.txt")
        branch_ids = sorted(current - before_branches - new_branches)
        new_branches.update(branch_ids)
        trace_path = run / "runtime_trace.jsonl"
        trace = rows(trace_path)
        item = state["completed"][identity]["item"]
        result = state["completed"][identity]["result"]
        exact, applied = campaign.exact_applied(item["sequence"], trace)
        checks, _ = campaign.postfault(trace, applied, exact)
        if not exact or not checks or not result["valid_for_feedback"]:
            raise RuntimeError(f"last-eight actor gate changed: {identity}")
        same_actor_io = []
        same_actor_new_io = []
        for row in campaign.eligible_io(trace):
            if (row.get("actorKey") == applied[0].get("actorKey")
                    and row.get("dnObjectId") == applied[0].get("dnObjectId")
                    and row.get("serviceObjectId") == applied[0].get("serviceObjectId")):
                same_actor_io.append({"seq": row["seq"], "family": campaign.family(row),
                                      "endpoint_raw": row.get("endpointRaw"),
                                      "hit_ordinal": row.get("hitOrdinal")})
                if campaign.family(row) not in before_io | new_io:
                    same_actor_new_io.append(campaign.family(row))
        new_io.update(campaign.family(row) for row in campaign.eligible_io(trace))
        trial_rows.append({"plan_id": identity, "trace_sha256": sha(trace_path),
                           "branches_new_at_trial": branch_ids,
                           "same_actor_target_related_io": same_actor_io,
                           "same_actor_io_families_new_at_trial": sorted(set(same_actor_new_io)),
                           "reported_new_io_families": result["new_io_families"],
                           "applied_faults": len(applied), "postfault_target_checks": len(checks)})
    report = {
        "schema": "hdfs31-actor-v3-base80-novelty-1",
        "checkpoint_sha256": sha(state_path),
        "completed": len(state["completion_order"]), "effective": state["effective"],
        "base_review_trial_ids": recent,
        "new_branch_ids_last_eight": sorted(new_branches),
        "new_same_actor_io_families_last_eight": sorted({family for row in trial_rows
            for family in row["same_actor_io_families_new_at_trial"]}),
        "target_path_branch_candidates": sorted(
            x for x in new_branches if x.startswith(TARGET_PREFIXES)),
        "other_branch_ids_need_source_review": sorted(
            x for x in new_branches if not x.startswith(TARGET_PREFIXES)),
        "trials": trial_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"completed": report["completed"], "effective": report["effective"],
                      "new_branches": len(new_branches),
                      "target_path_candidates": len(report["target_path_branch_candidates"]),
                      "report": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
