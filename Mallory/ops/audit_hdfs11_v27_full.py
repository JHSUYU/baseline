"""Recompute HDFS-11 v27 fault-to-target paths from archived trial traces.

Run with the pinned fa5f core release first on PYTHONPATH. A positive path
starts at FAULT_APPLIED, not at the preceding healthy or faulted door.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import gzip
import hashlib
import inspect
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph


CASE = "HDFS-11"
FAULT_SITE = "hdfs:nn-get-data-encryption-key"
TARGET_SITE = ("org.apache.hadoop.hdfs.security.token.block."
               "BlockTokenSecretManager#retrieveDataEncryptionKey(I[B)[B@552:branch:1")
EXPECTED_HOPS = (
    ("rpc", "org.apache.hadoop.ipc.Server.Connection#sendResponse",
     "org.apache.hadoop.ipc.Client#getRpcResponse.error"),
    ("rpc", "hdfs:sasl-initial-message-written",
     "hdfs:sasl-initial-message-read"),
    ("region_parent", "hdfs:sasl-initial-message-read",
     "org.apache.hadoop.hdfs.security.token.block."
     "BlockTokenSecretManager#retrieveDataEncryptionKey(I[B)[B"),
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_trace(trial_dir: Path, trial: dict) -> tuple[dict, ...]:
    evidence = trial["events_evidence"]
    name = evidence["gzip_path"]
    if Path(name).name != name or sha(trial_dir / name) != evidence["gzip_sha256"]:
        raise ValueError(f"compressed trace hash mismatch: {trial_dir}")
    with gzip.open(trial_dir / name, "rb") as stream:
        raw = stream.read()
    if (hashlib.sha256(raw).hexdigest() != evidence["raw_sha256"] or
            len(raw) != evidence["raw_bytes"]):
        raise ValueError(f"raw trace hash mismatch: {trial_dir}")
    return tuple(json.loads(line) for line in raw.splitlines())


def same_actor(left: dict, right: dict) -> bool:
    return (left.get("node") == right.get("node") and
            left.get("epoch") == right.get("epoch") and
            left.get("occurrence") == right.get("occurrence") and
            isinstance(left.get("thread_id"), int) and
            left.get("thread_id") == right.get("thread_id"))


def same_thread_actor(left: dict, right: dict) -> bool:
    return (left.get("node") == right.get("node") and
            left.get("epoch") == right.get("epoch") and
            isinstance(left.get("thread_id"), int) and
            left.get("thread_id") == right.get("thread_id"))


def exact_witness(events: tuple[dict, ...], trial: dict,
                  healthy_point: dict) -> dict | None:
    feedback = trial["feedback"]
    if not (feedback.get("all_faults_effective") is True and
            feedback.get("target_reached") is True and
            feedback.get("target_identity_complete") is True):
        return None
    applied = [event for event in events if event.get("type") == "FAULT_APPLIED"]
    if not applied or len(applied) != len(feedback.get("applied_fault_ids", [])):
        return None
    last_seq = max(event["seq"] for event in applied)
    final = [event for event in applied if event["seq"] == last_seq and
             event.get("site") == FAULT_SITE and
             all(event.get(key) == healthy_point.get(key)
                 for key in ("site", "node", "epoch", "door_ordinal"))]
    if len(final) != 1 or final[0].get("node", "").endswith("/nn0") is False:
        return None
    fault = final[0]
    doors = [event for event in events if event.get("type") == "DOOR_OBSERVED"
             and event.get("seq") == fault["seq"] - 2 and same_actor(event, fault)
             and all(event.get(key) == fault.get(key)
                     for key in ("site", "node", "epoch", "door_ordinal"))]
    if len(doors) != 1:
        return None
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    by_id = {event["id"]: event for event in events}
    if len(by_id) != len(events):
        return None
    targets = [event for event in events if event.get("type") == "TARGET_CHECK"
               and event.get("site") == TARGET_SITE and event["seq"] > last_seq
               and "/dn" in str(event.get("node")) and
               isinstance(event.get("thread_id"), int)]
    for target in targets:
        path = graph.event_path(fault, target, require_edge=True)
        if path is None or len(path) != len(EXPECTED_HOPS):
            continue
        hops = []
        for edge, expected in zip(path, EXPECTED_HOPS):
            producer = by_id[edge.producer_event]
            consumer = by_id[edge.consumer_event]
            if ((edge.kind, producer.get("site"), consumer.get("site")) != expected or
                    edge.certainty != "observed" or
                    producer["seq"] <= last_seq or
                    producer["seq"] >= consumer["seq"] or
                    not isinstance(producer.get("thread_id"), int) or
                    not isinstance(consumer.get("thread_id"), int)):
                break
            hops.append(asdict(edge))
        if len(hops) != len(EXPECTED_HOPS):
            continue
        first_send = by_id[path[0].producer_event]
        error_recv = by_id[path[0].consumer_event]
        sasl_send = by_id[path[1].producer_event]
        sasl_recv = by_id[path[1].consumer_event]
        target_enter = by_id[path[2].consumer_event]
        if not (same_actor(fault, first_send) and
                same_actor(error_recv, sasl_send) and
                same_thread_actor(sasl_recv, target_enter) and
                same_actor(target_enter, target) and
                target["seq"] > target_enter["seq"] and
                error_recv["seq"] < sasl_send["seq"] and
                sasl_recv["seq"] < target_enter["seq"]):
            continue
        return {"door_event": doors[0]["id"], "fault_event": fault["id"],
                "target_check_event": target["id"], "target_node": target["node"],
                "fault_thread_id": fault["thread_id"],
                "target_thread_id": target["thread_id"], "edges": hops,
                "evidence_type": "observed_nn_error_response_retry_sasl_target_event_path"}
    return None


def review(campaign: Path) -> dict:
    result_path = campaign / "result.json"
    result = json.loads(result_path.read_text())
    if (result.get("case_id") != CASE or result.get("status") != "budget_exhausted"
            or result.get("fault_trials_completed") != 80):
        raise ValueError("unexpected HDFS-11 terminal campaign")
    audit_path = campaign / "offline-causal-audit.json"
    audit = json.loads(audit_path.read_text())
    if (audit.get("report_gate_passed") is not True or
            audit.get("campaign_result_sha256") != sha(result_path)):
        raise ValueError("frozen offline audit is not bound to this result")
    archive_info = result["evidence_archive"]
    archive_root = campaign.parents[1]
    archive_path = archive_root / archive_info["path"]
    manifest_path = archive_root / archive_info["manifest_path"]
    if (sha(archive_path) != archive_info["sha256"] or
            sha(manifest_path) != archive_info["manifest_sha256"]):
        raise ValueError("terminal evidence archive differs from result pin")
    healthy_path = campaign / "trials/r0000/result.json"
    healthy = json.loads(healthy_path.read_text())
    points = [door["point"] for door in healthy["feedback"]["doors"]
              if door.get("site") == FAULT_SITE and door.get("in_closure") is True]
    if len(points) != 1:
        raise ValueError("healthy NN fault door is not unique and admitted")
    rows = []
    for trial_id in range(1, 81):
        trial_dir = campaign / "trials" / f"r{trial_id:04d}"
        trial_path = trial_dir / "result.json"
        trial = json.loads(trial_path.read_text())
        events = load_trace(trial_dir, trial)
        witness = exact_witness(events, trial, points[0])
        rows.append({"trial_id": trial_id,
                     "trial_result_sha256": sha(trial_path),
                     "trace_gzip_sha256": trial["events_evidence"]["gzip_sha256"],
                     "trace_raw_sha256": trial["events_evidence"]["raw_sha256"],
                     "strict_effective": trial["feedback"].get("all_faults_effective") is True,
                     "postfault_target": trial["feedback"].get("target_reached") is True,
                     "witness": witness})
    positive = sum(row["witness"] is not None for row in rows)
    if (sum(row["strict_effective"] for row in rows) !=
            result["strict_injected_trials"] or
            sum(row["strict_effective"] and row["postfault_target"] for row in rows)
            != result["strict_target_trials"]):
        raise ValueError("trial strict counts differ from terminal result")
    return {"schema_version": 1, "case_id": CASE,
            "classification": "observed_event_path" if positive else "faulted_path_unverified",
            "campaign_result_sha256": sha(result_path),
            "offline_audit_sha256": sha(campaign / "offline-causal-audit.json"),
            "config_sha256": sha(campaign / "config.json"),
            "archive_sha256": sha(archive_path),
            "archive_manifest_sha256": sha(manifest_path),
            "graph_source_sha256": sha(Path(inspect.getfile(OccurrenceGraph))),
            "healthy_trial_result_sha256": sha(healthy_path),
            "healthy_fault_door_point": points[0],
            "strict_injected_trials": result["strict_injected_trials"],
            "strict_target_trials": result["strict_target_trials"],
            "qualifying_trial_count": positive,
            "provenance_limit": "Path certifies event order and propagation, not that the exception caused the later target check.",
            "trials": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true",
                        help="compare the receipt byte-for-byte against recomputed evidence")
    args = parser.parse_args()
    receipt = review(args.campaign)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.verify:
        if args.out.read_text() != encoded:
            raise ValueError("SHA-bound receipt differs from recomputed raw evidence")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded)
    print(json.dumps({"classification": receipt["classification"],
                      "qualifying_trial_count": receipt["qualifying_trial_count"]}))


if __name__ == "__main__":
    main()
