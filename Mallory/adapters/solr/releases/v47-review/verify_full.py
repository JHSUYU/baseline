#!/usr/bin/env python3
"""Review every SOLR-31 v47 fault trial from immutable raw evidence.

Watcher-to-request state observations are reported separately from Mallory
graph paths: those callbacks and the target request run on different threads.
"""

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path


COLLECTION = "forceleader_lower_terms_collection"
WATCHER_DOOR = ("org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState"
                "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Ljava/lang/String;)"
                "Lorg/apache/solr/common/cloud/DocCollection;@1641:door:watcher")
STATE_LINE = re.compile(
    r"MALLORY_SOLR31_STATE phase=(?P<phase>\w+) ts=(?P<ts>\d+) "
    r"node=(?P<node>\S+) epoch=(?P<epoch>\d+) thread_id=(?P<thread_id>\d+) "
    r"occurrence=(?P<occurrence>\S+) collection=(?P<collection>\S+) "
    r"reader_id=(?P<reader_id>\S+) .*?version=(?P<version>\S+) "
    r"leader=(?P<leader>\S+) leader_state=(?P<leader_state>\S+)")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    return digest(path.read_bytes())


def identity(event: dict) -> tuple:
    return tuple(event.get(k) for k in
                 ("site", "node", "epoch", "occurrence", "thread_id", "door_ordinal"))


def state_witness(fault: dict, events: list[dict], logs: list[dict],
                  target_sites: set[str], throw_site: str) -> dict | None:
    if fault.get("site") != WATCHER_DOOR:
        return None
    same_watch = lambda row, phase: (row["phase"] == phase and
                                    row["node"] == fault["node"] and
                                    int(row["epoch"]) == fault["epoch"] and
                                    row["occurrence"] == fault["occurrence"] and
                                    row["collection"] == COLLECTION)
    before = [row for row in logs if same_watch(row, "before")]
    after = [row for row in logs if same_watch(row, "after")]
    if len(before) != 1 or len(after) != 1 or before[0]["reader_id"] != after[0]["reader_id"]:
        return None
    if int(before[0]["ts"]) >= int(after[0]["ts"]):
        return None
    targets = [e for e in events if e.get("type") == "TARGET_CHECK" and
               e.get("site") in target_sites and e.get("node") == fault["node"] and
               e.get("epoch") == fault["epoch"] and e.get("seq", -1) > fault["seq"]]
    for target in targets:
        operands = [row for row in logs if row["phase"] == "target" and
                    row["reader_id"] == before[0]["reader_id"] and
                    row["node"] == target["node"] and
                    int(row["epoch"]) == target["epoch"] and
                    row["occurrence"] == target["occurrence"] and
                    row["collection"] == COLLECTION and
                    int(row["ts"]) > int(after[0]["ts"])]
        if len(operands) != 1:
            continue
        throws = [e["seq"] for e in events if e.get("type") == "TARGET_THROW" and
                  e.get("site") == throw_site and e.get("node") == target["node"] and
                  e.get("epoch") == target["epoch"] and
                  e.get("occurrence") == target["occurrence"] and
                  e.get("seq", -1) > target["seq"]]
        return {"reader_id": before[0]["reader_id"], "watch_occurrence": fault["occurrence"],
                "node": fault["node"], "epoch": fault["epoch"],
                "fault_seq": fault["seq"], "before_version": before[0]["version"],
                "before_leader_state": before[0]["leader_state"],
                "after_version": after[0]["version"],
                "after_leader_state": after[0]["leader_state"],
                "target_seq": target["seq"], "target_occurrence": target["occurrence"],
                "target_version": operands[0]["version"],
                "target_leader": operands[0]["leader"],
                "target_leader_state": operands[0]["leader_state"],
                "selected_throw_seqs": throws,
                "evidence_kind": "same_reader_state_timeline_not_graph_edge"}
    return None


def review_trial(root: Path, row: dict, config: dict, manifest: dict,
                 bound_nodes: set[str] | None = None) -> dict:
    trial = root / row["result"]
    assert trial.name == "result.json" and trial.parent.name == f"r{row['trial_id']:04d}"
    trial_dir = trial.parent
    packed_path = trial_dir / "events.jsonl.gz"
    packed = packed_path.read_bytes()
    raw = gzip.decompress(packed)
    result = json.loads(trial.read_text())
    events = [json.loads(line) for line in raw.splitlines()]
    junit_path = trial_dir / "junit.log"
    logs = [match.groupdict() for match in STATE_LINE.finditer(
        junit_path.read_text(errors="replace"))]
    for path in (trial, packed_path, junit_path, trial_dir / "junit-receipt.json"):
        relative = str(path.relative_to(root))
        assert relative in manifest, relative
        assert file_digest(path) == manifest[relative], relative
    target_sites = set(config["target"]["check_sites"])
    throw_site = config["target"]["throw_site"]
    target_events = [e for e in events if e.get("type") == "TARGET_CHECK" and
                     e.get("site") in target_sites]
    bound_targets = [e for e in target_events if bound_nodes is None or
                     e.get("node") in bound_nodes]
    selected_throws = [e for e in events if e.get("type") == "TARGET_THROW" and
                       e.get("site") == throw_site]
    bound_throws = [e for e in selected_throws if bound_nodes is None or
                    e.get("node") in bound_nodes]
    faults = []
    for planned in result.get("plan", []):
        fault_id = planned["fault_id"]
        applied = [e for e in events if e.get("type") == "FAULT_APPLIED" and
                   e.get("fault_id") == fault_id]
        matched = [e for e in events if e.get("type") == "FAULT_MATCHED" and
                   e.get("fault_id") == fault_id]
        assert len(applied) <= 1 and len(matched) <= 1
        witness = None
        if applied:
            fault = applied[0]
            point = planned["point"]
            for key in ("site", "node", "epoch", "door_ordinal"):
                assert fault.get(key) == point[key], (trial_dir, key)
            assert fault.get("exception_class") == planned["exception_class"]
            assert isinstance(fault.get("thread_id"), int)
            assert len(matched) == 1 and identity(matched[0]) == identity(fault)
            doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
                     identity(e) == identity(fault)]
            assert len(doors) == 1 and doors[0]["seq"] < matched[0]["seq"] < fault["seq"]
            witness = state_witness(fault, events, logs, target_sites, throw_site)
        faults.append({"fault_id": fault_id, "point": planned["point"],
                       "exception_class": planned["exception_class"],
                       "exact_applied": bool(applied),
                       "fault_seq": applied[0]["seq"] if applied else None,
                       "state_witness": witness})
    feedback = result["feedback"]
    assert feedback.get("all_faults_applied") == all(f["exact_applied"] for f in faults)
    if bound_nodes is not None:
        assert feedback.get("target_reached") == bool(bound_targets)
    return {"trial_id": row["trial_id"], "trial_result_sha256": file_digest(trial),
            "events_gzip_sha256": digest(packed), "events_raw_sha256": digest(raw),
            "junit_log_sha256": file_digest(junit_path),
            "junit_receipt_sha256": file_digest(trial_dir / "junit-receipt.json"),
            "junit_status": result["junit_validation"]["status"],
            "feedback_status": feedback["status"],
            "all_faults_effective": feedback.get("all_faults_effective"),
            "exact_target_check_count": len(target_events),
            "bound_target_check_count": len(bound_targets),
            "feedback_target_reached": feedback.get("target_reached"),
            "exact_selected_throw_count": len(selected_throws),
            "bound_selected_throw_count": len(bound_throws),
            "faults": faults}


def review(root: Path) -> dict:
    result_path = root / "result.json"
    config_path = root / "config.json"
    manifest_path = root / "terminal-manifest.json"
    result = json.loads(result_path.read_text())
    config = json.loads(config_path.read_text())
    terminal = json.loads(manifest_path.read_text())
    stop_path = root / "supplemental-stop.json"
    stopped = stop_path.is_file()
    if stopped:
        stop = json.loads(stop_path.read_text())
        assert stop["status"] == "supplemental_stopped"
        assert result["status"] == "running"
        assert stop["result_sha256"] == file_digest(result_path)
        assert stop["checkpoint_sha256"] == file_digest(root / "checkpoint.json")
        assert stop["terminal_manifest_sha256"] == file_digest(manifest_path)
        assert stop["lane_released"] is True and stop["runner_exited"] is True
        assert terminal["terminal_status"] == "supplemental_stopped"
    else:
        assert result["status"] in {"budget_exhausted", "queue_exhausted"}
        assert terminal["terminal_status"] == result["status"]
    assert result["case_id"] == config["case_id"] == terminal["case_id"] == "SOLR-31"
    manifest = {row["path"]: row["sha256"] for row in terminal["files"]}
    assert len(manifest) == len(terminal["files"])
    for row in terminal["files"]:
        path = (root / row["path"]).resolve()
        assert path.is_relative_to(root.resolve())
        assert path.stat().st_size == row["bytes"]
        assert file_digest(path) == row["sha256"], row["path"]
    for path in (result_path, config_path):
        assert file_digest(path) == manifest[path.name]
    rows = result["trials"]
    assert rows[0]["trial_id"] == 0 and rows[0]["selection_reason"] == "healthy_seed"
    assert [row["trial_id"] for row in rows] == list(range(len(rows)))
    assert len(rows) - 1 == result["fault_trials_completed"]
    bound_nodes = set((result.get("target_binding") or {}).get("nodes") or [])
    assert bound_nodes and all(node not in {"unknown", "client"} for node in bound_nodes)
    fault_rows = [review_trial(root, row, config, manifest, bound_nodes)
                  for row in rows[1:]]
    return {"schema_version": 1, "case_id": "SOLR-31",
            "campaign_status": terminal["terminal_status"],
            "completion_kind": ("supplemental_stopped_not_canonical_completion" if stopped
                                else "supplemental_natural_terminal"),
            "state_evidence_kind": "same_reader_state_timeline_not_graph_edge",
            "result_sha256": file_digest(result_path), "config_sha256": file_digest(config_path),
            "terminal_manifest_sha256": file_digest(manifest_path),
            "supplemental_stop_sha256": file_digest(stop_path) if stopped else None,
            "fault_trials_completed": len(fault_rows),
            "exact_applied_trials": sum(all(f["exact_applied"] for f in r["faults"])
                                        for r in fault_rows),
            "target_reached_trials": sum(r["bound_target_check_count"] > 0 for r in fault_rows),
            "same_reader_state_witness_trials": sum(any(f["state_witness"] is not None
                                                        for f in r["faults"]) for r in fault_rows),
            "selected_throw_trials": sum(r["bound_selected_throw_count"] > 0
                                         for r in fault_rows),
            "same_reader_selected_throw_trials": sum(any(
                (f["state_witness"] or {}).get("selected_throw_seqs")
                for f in r["faults"]) for r in fault_rows),
            "trials": fault_rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    output = review(args.campaign)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: output[key] for key in
                      ("campaign_status", "fault_trials_completed", "exact_applied_trials",
                       "target_reached_trials", "same_reader_state_witness_trials",
                       "selected_throw_trials", "same_reader_selected_throw_trials")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
