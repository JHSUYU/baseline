"""Bounded HDFS key-issuance RPC fault pilot using the pinned Mallory core.

Select only a NameNode RpcCall door whose next method event in the same RPC
occurrence is NameNodeRpcServer.getDataEncryptionKey. The decision comes from
this pilot's healthy run; a prior trial's ordinal is never reused.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

from Mallory.core import campaign
from Mallory.core.feedback import digest
from Mallory.core.scheduler import _replay_point, sequence_signature


KEY_METHOD = ("org.apache.hadoop.hdfs.server.namenode.NameNodeRpcServer"
              "#getDataEncryptionKey()Lorg/apache/hadoop/hdfs/security/token/block/"
              "DataEncryptionKey;")
RPC_DOOR = "org.apache.hadoop.ipc.Server$RpcCall#run()Ljava/lang/Void;@1246:door:1"


def select_key_rpc_doors(trace_path: Path, feedback_doors: list[dict]) -> list[dict]:
    """Return observed-path doors with a unique immediate key-issuance call.

    The generic RpcCall door is emitted before its dispatch call. We require
    the first subsequent METHOD in the same occurrence and handler thread to
    be getDataEncryptionKey, before any response SEND. This excludes unrelated
    NN RPC calls that share this bytecode site.
    """
    with gzip.open(trace_path, "rt", encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream]
    by_id = {event.get("id"): index for index, event in enumerate(events)}
    selected = []
    for door in feedback_doors:
        if (door.get("site") != RPC_DOOR or not door.get("in_closure") or
                door.get("exception_class") != "java.io.IOException"):
            continue
        index = by_id.get(door.get("event_id"))
        if index is None:
            continue
        event = events[index]
        point = _replay_point(door)
        if (point is None or point.get("node") != event.get("node") or
                not str(point["node"]).endswith("/nn0") or
                event.get("type") != "DOOR_OBSERVED"):
            continue
        following = None
        for later in events[index + 1:]:
            if (later.get("occurrence") != event.get("occurrence") or
                    later.get("thread") != event.get("thread")):
                continue
            if later.get("type") == "SEND" and later.get("port") == "response":
                break
            if later.get("type") == "METHOD":
                following = later
                break
        if following is not None and following.get("site") == KEY_METHOD:
            selected.append({"point": point,
                             "healthy_door_event_id": event["id"],
                             "healthy_key_method_event_id": following["id"],
                             "rpc_occurrence": event["occurrence"]})
    selected.sort(key=lambda item: (item["point"]["node"],
                                    item["point"]["epoch"],
                                    item["point"]["door_ordinal"]))
    return selected


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-doors", type=int, default=1)
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

    matches = select_key_rpc_doors(out / "trials/r0000/events.jsonl.gz",
                                   healthy["feedback"]["doors"])
    if not matches:
        state["status"] = "focus_door_absent"
        campaign.atomic_json(out / "checkpoint.json", state)
        campaign._write_summary(out, state, config)
        print(json.dumps({"status": state["status"], "out": str(out)}))
        return 2
    selected = matches[:min(args.max_doors, config["budget"]["trials"])]
    campaign.atomic_json(out / "focus-plan-selection.json", {
        "schema_version": 1, "site": RPC_DOOR,
        "required_next_method": KEY_METHOD,
        "healthy_trial_result_sha256": _sha256(out / "trials/r0000/result.json"),
        "selected": selected,
    })

    for trial_id, entry in enumerate(selected, start=1):
        point = entry["point"]
        fault = {"fault_id": "f" + digest([0, point, "EXCEPTION"]),
                 "point": point, "fault_type": "EXCEPTION",
                 "exception_class": "java.io.IOException"}
        plan = [fault]
        item = {"faults": plan, "signature": sequence_signature(plan),
                "selection_reason": "observed_key_issuance_rpc_door", "priority": 0.0,
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
