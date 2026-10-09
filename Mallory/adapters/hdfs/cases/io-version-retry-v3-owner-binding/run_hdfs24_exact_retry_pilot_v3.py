"""Bounded HDFS-24 pilot on named pretarget namespace-retry doors only.

This runner selects a door from its *own* healthy trial. It does not change the
frozen core scheduler or treat a previously observed exception as a bug.
Run with PYTHONPATH starting at the immutable core release directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from Mallory.core import campaign
from Mallory.core.feedback import digest
from Mallory.core.scheduler import _replay_point, sequence_signature


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--max-doors", type=int, default=2)
    parser.add_argument("--core-release", type=Path, required=True)
    args = parser.parse_args()
    release = args.core_release.resolve()
    actual_core = Path(campaign.__file__).resolve()
    if not actual_core.is_relative_to(release):
        raise RuntimeError(f"core is not loaded from pinned release: {actual_core}")
    if args.max_doors < 1:
        raise ValueError("--max-doors must be positive")

    config = campaign.read_json(args.config)
    campaign.validate_config(config)
    campaign.load_static_frontier(config)
    campaign.verify_validated_recovery_sites(config)
    if config.get("calibration_only") or not config.get("auto_promote_if_healthy"):
        raise ValueError("focused pilot needs a fault-capable, healthy-attested config")
    if args.out.exists():
        raise FileExistsError(f"pilot output already exists: {args.out}")
    out = args.out.resolve()
    out.mkdir(parents=True)
    state = campaign._fresh_state(config)
    state["out"] = str(out)
    state["calibration_only"] = False
    campaign.atomic_json(out / "config.json", config)
    campaign.atomic_json(out / "checkpoint.json", state)

    def run_trial(trial_id: int, plan: list[dict], item: dict | None) -> dict:
        state["running"] = {"trial_id": trial_id, "item": item, "pid": None}
        campaign.atomic_json(out / "checkpoint.json", state)

        def save_running(pid: int) -> None:
            state["running"]["pid"] = pid
            campaign.atomic_json(out / "checkpoint.json", state)

        result = campaign._run_trial(config, out, trial_id, plan, save_running,
                                     state.get("target_binding"))
        campaign._apply_result(state, config, result, item)
        state["next_trial"] = trial_id + 1
        state["updated_at"] = time.time()
        campaign.atomic_json(out / "checkpoint.json", state)
        campaign._write_summary(out, state, config)
        return result

    healthy = run_trial(0, [], None)
    attestation = state.get("runtime_attestation") or {}
    if state["status"] != "running" or not attestation.get("valid"):
        state["status"] = "healthy_seed_invalid"
        campaign.atomic_json(out / "checkpoint.json", state)
        campaign._write_summary(out, state, config)
        print(json.dumps({"status": state["status"], "out": str(out)}))
        return 2

    target_actors = {(row.get("node"), row.get("epoch"))
                     for row in healthy["feedback"].get("target_instances", [])
                     if row.get("node") not in (None, "unknown")}
    if not target_actors:
        raise RuntimeError("fresh healthy trial has no named target actors")
    matches = []
    for door in healthy["feedback"]["doors"]:
        if (door.get("site") != args.site or not door.get("in_closure") or
                door.get("exception_class") != "java.io.IOException"):
            continue
        point = _replay_point(door)
        if point is not None and (point["node"], point["epoch"]) in target_actors:
            matches.append((point["door_ordinal"], point, door))
    matches.sort(key=lambda row: row[0])
    if not matches:
        state["status"] = "focus_door_absent"
        campaign.atomic_json(out / "checkpoint.json", state)
        campaign._write_summary(out, state, config)
        print(json.dumps({"status": state["status"], "out": str(out)}))
        return 2
    selected = matches[:min(args.max_doors, config["budget"]["trials"])]
    campaign.atomic_json(out / "focus-plan-selection.json", {
        "schema_version": 1, "site": args.site,
        "healthy_trial_result_sha256": _sha256(out / "trials/r0000/result.json"),
        "selected": [{"point": point, "healthy_door_event_id": door["event_id"],
                      "matching_healthy_target_occurrences": [
                          row["occurrence"] for row in healthy["feedback"]["target_instances"]
                          if row["node"] == point["node"] and row["epoch"] == point["epoch"]]}
                     for _, point, door in selected],
    })

    for trial_id, (_, point, _) in enumerate(selected, start=1):
        fault = {"fault_id": "f" + digest([0, point, "EXCEPTION"]),
                 "point": point, "fault_type": "EXCEPTION",
                 "exception_class": "java.io.IOException"}
        plan = [fault]
        item = {"faults": plan, "signature": sequence_signature(plan),
                "selection_reason": "focused_exact_io_door", "priority": 0.0,
                "queued_at": 0}
        run_trial(trial_id, plan, item)

    state["status"] = "budget_exhausted"
    state["updated_at"] = time.time()
    campaign.atomic_json(out / "checkpoint.json", state)
    campaign._write_summary(out, state, config)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"],
                      "out": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
