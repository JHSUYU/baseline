#!/usr/bin/env python3
"""Fail-closed ZK12 terminal verifier over the lossless campaign archive.

The verifier reads archived trial results and traces, independently checks
each member against the archive manifest, and never edits a campaign result.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


CASE = "ZOOKEEPER-12"
DOOR = "org.apache.zookeeper.server.quorum.QuorumPeer#readLongFromFile(Ljava/lang/String;)J@2190:door:1"
CHECK = "org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1193:branch:3"
THROW = "org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1197:throw:1"
EXCEPTION = "java.io.FileNotFoundException"
METHOD = "org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def valid_occurrence(event: dict) -> bool:
    node, epoch = event.get("node"), event.get("epoch")
    occurrence = event.get("occurrence")
    return (node == "zk0" and type(epoch) is int and epoch >= 0
            and type(event.get("thread_id")) is int
            and type(occurrence) is str
            and occurrence.startswith(f"zk0:{epoch}:{METHOD}:")
            and ":root:" in occurrence)


def same_occurrence_after(fault: dict, event: dict) -> bool:
    return (valid_occurrence(event)
            and all(event[key] == fault[key]
                    for key in ("node", "epoch", "thread_id", "occurrence"))
            and type(event.get("seq")) is int and event["seq"] > fault["seq"]
            and type(event.get("ts")) is int and event["ts"] > fault["ts"])


def verify_trial(trial: dict, compressed_trace: bytes, trial_id: int) -> dict:
    require(trial.get("case_id") == CASE and trial.get("trial_id") == trial_id,
            f"r{trial_id:04d}: trial identity mismatch")
    evidence = trial["events_evidence"]
    require(digest(compressed_trace) == evidence["gzip_sha256"],
            f"r{trial_id:04d}: compressed trace digest mismatch")
    raw = gzip.decompress(compressed_trace)
    require(len(raw) == evidence["raw_bytes"]
            and digest(raw) == evidence["raw_sha256"],
            f"r{trial_id:04d}: raw trace digest/size mismatch")
    events = [read_json(line) for line in raw.splitlines()]
    require(events and all(type(e.get("seq")) is int for e in events),
            f"r{trial_id:04d}: missing or nonnumeric event sequence")
    require(all(a["seq"] < b["seq"] for a, b in zip(events, events[1:])),
            f"r{trial_id:04d}: event sequence is not strictly ordered")
    require(len({e.get("id") for e in events}) == len(events),
            f"r{trial_id:04d}: duplicate event ID")

    plan = trial["plan"]
    require(1 <= len(plan) <= 3,
            f"r{trial_id:04d}: fault depth outside pinned budget")
    matched = [e for e in events if e["type"] == "FAULT_MATCHED"]
    applied = [e for e in events if e["type"] == "FAULT_APPLIED"]
    require(len(matched) == len(applied) == len(plan),
            f"r{trial_id:04d}: MATCH/APPLY count does not match plan")
    for position, (intended, match, fault) in enumerate(zip(plan, matched, applied)):
        point = intended["point"]
        require(intended["fault_type"] == "EXCEPTION"
                and intended["exception_class"] == EXCEPTION
                and point["site"] == DOOR and point["node"] == "zk0",
                f"r{trial_id:04d}: plan {position} is not the selected FNF door")
        for event in (match, fault):
            require(valid_occurrence(event),
                    f"r{trial_id:04d}: unnamed or unscoped fault event")
            require(event["fault_id"] == intended["fault_id"]
                    and event["site"] == point["site"]
                    and event["node"] == point["node"]
                    and event["epoch"] == point["epoch"]
                    and event["door_ordinal"] == point["door_ordinal"]
                    and event["exception_class"] == EXCEPTION,
                    f"r{trial_id:04d}: planned fault identity mismatch")
        require(match["seq"] < fault["seq"] and match["ts"] < fault["ts"]
                and all(match[k] == fault[k]
                        for k in ("node", "epoch", "thread_id", "occurrence")),
                f"r{trial_id:04d}: MATCH does not precede same-door APPLY")
        if position:
            require(applied[position - 1]["seq"] < match["seq"],
                    f"r{trial_id:04d}: fault chain out of order")
    feedback = trial["feedback"]
    require(all(feedback.get(key) is True for key in
                ("all_faults_matched", "all_faults_applied", "all_faults_effective")),
            f"r{trial_id:04d}: core did not confirm effective faults")

    last = applied[-1]
    checks = [e for e in events if e["type"] == "TARGET_CHECK"
              and e.get("site") == CHECK and same_occurrence_after(last, e)]
    throws = [e for e in events if e["type"] == "TARGET_THROW"
              and e.get("site") == THROW]
    require(not throws, f"r{trial_id:04d}: selected target exception exists")
    classification = "target_retained_no_throw" if checks else "target_lost"
    require(feedback.get("status") == ("observed" if checks else "target_lost"),
            f"r{trial_id:04d}: core status disagrees with strict target identity")
    return {
        "trial_id": trial_id,
        "classification": classification,
        "depth": len(plan),
        "matched_event_ids": [e["id"] for e in matched],
        "applied_event_ids": [e["id"] for e in applied],
        "last_applied_event_id": last["id"],
        "postfault_check_ids": [e["id"] for e in checks],
        "last_fault_identity": {k: last[k] for k in
                                ("node", "epoch", "thread_id", "occurrence")},
        "junit_status": trial["junit_validation"]["status"],
        "trial_result_sha256": None,
        "trace_gzip_sha256": digest(compressed_trace),
        "trace_raw_sha256": digest(raw),
    }


def archive_members(archive: Path, manifest: dict) -> dict[str, bytes]:
    require(digest(archive.read_bytes()) == manifest["archive_sha256"],
            "archive compressed digest mismatch")
    expected = manifest["members"]
    found: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            name = member.name
            path = PurePosixPath(name)
            require(member.isfile() and name in expected and name not in found
                    and not path.is_absolute() and ".." not in path.parts,
                    f"unexpected archive member {name!r}")
            stream = tar.extractfile(member)
            require(stream is not None, f"unreadable archive member {name!r}")
            data = stream.read()
            require(len(data) == expected[name]["bytes"]
                    and digest(data) == expected[name]["sha256"],
                    f"archive member changed: {name}")
            found[name] = data
    require(found.keys() == expected.keys(), "archive member set mismatch")
    return found


def verify(canonical: Path, archive: Path, manifest_path: Path,
           review_path: Path, sync_path: Path) -> dict:
    manifest_bytes = manifest_path.read_bytes()
    manifest = read_json(manifest_bytes)
    require(manifest["case_id"] == CASE, "wrong archive case")
    members = archive_members(archive, manifest)
    sync = read_json(sync_path.read_bytes())
    require(sync["archive_manifest_sha256"] == digest(manifest_bytes)
            and sync["archive_sha256"] == manifest["archive_sha256"],
            "canonical sync receipt is not bound to archive")
    for name in ("config.json", "result.json", "offline-causal-audit.json"):
        require((canonical / name).read_bytes() == members[name]
                and sync["retained_files"][name]["sha256"] == digest(members[name]),
                f"canonical {name} differs from archived original")
    review_bytes = review_path.read_bytes()
    require(sync["strict_review_sha256"] == digest(review_bytes),
            "prior strict review is not bound to canonical sync")
    config = read_json(members["config.json"])
    result = read_json(members["result.json"])
    audit = read_json(members["offline-causal-audit.json"])
    require(result["case_id"] == CASE and result["status"] == "queue_exhausted"
            and result["fault_trials_completed"] == 18,
            "campaign did not terminate with exactly 18 fault trials")
    require(config["target"]["check_sites"] == [CHECK]
            and config["target"]["throw_site"] == THROW
            and config["budget"]["max_faults_per_trial"] == 3,
            "pinned target or budget changed")
    require(audit["campaign_result_sha256"] == digest(members["result.json"])
            and audit["report_gate_passed"] is True
            and audit["healthy_closure_evidence_types"] == ["observed_local_timeline"]
            and audit["same_actor_target_trials"] == 14,
            "frozen offline audit did not qualify")
    require(result["runtime_attestation"]["valid"] is True,
            "runtime class/site attestation missing")
    rows = []
    for trial_id in range(1, 19):
        prefix = f"trials/r{trial_id:04d}/"
        trial_data = members[prefix + "result.json"]
        row = verify_trial(read_json(trial_data),
                           members[prefix + "events.jsonl.gz"], trial_id)
        row["trial_result_sha256"] = digest(trial_data)
        rows.append(row)
    retained = sum(row["classification"] == "target_retained_no_throw" for row in rows)
    lost = len(rows) - retained
    require((retained, lost) == (14, 4),
            "strict affected-actor classification changed")
    old_review = read_json(review_bytes)
    require(old_review["campaign_result_sha256"] == digest(members["result.json"])
            and old_review["fault_trials"] == 18
            and old_review["strict_fault_chain_trials"] == 18
            and old_review["same_actor_same_occurrence_postfault_check_trials"] == retained
            and old_review["same_actor_same_occurrence_postfault_throw_trials"] == 0,
            "prior strict review disagrees with independent verifier")
    return {
        "schema_version": 1,
        "case_id": CASE,
        "status": "terminal_verified_no_selected_exception",
        "classification": "target_exercised_local_timeline",
        "campaign_result_sha256": digest(members["result.json"]),
        "offline_audit_sha256": digest(members["offline-causal-audit.json"]),
        "config_sha256": digest(members["config.json"]),
        "archive_sha256": manifest["archive_sha256"],
        "archive_manifest_sha256": digest(manifest_bytes),
        "canonical_sync_receipt_sha256": digest(sync_path.read_bytes()),
        "prior_strict_review_sha256": digest(review_bytes),
        "healthy_evidence_type": "observed_local_timeline",
        "fault_trials": 18,
        "faults_matched_and_applied": sum(row["depth"] for row in rows),
        "strict_same_actor_postfault_check_trials": retained,
        "target_lost_trials": lost,
        "selected_target_exception_trials": 0,
        "trial_evidence": rows,
        "interpretation_limit": (
            "The trace records the readLine door ordinal, not the epoch "
            "filename or operand value. This proves target exercise and "
            "absence of the selected throw in these runs, not absence of a bug."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path("/users/ZhenyuLi/baseline"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    result = verify(
        root / "data/mallory/cases/ZOOKEEPER-12",
        root / "data/mallory/evidence_archives/campaign/ZOOKEEPER-12.tar.gz",
        root / "data/mallory/evidence_archives/campaign/ZOOKEEPER-12.tar.manifest.json",
        root / "data/mallory/admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-full-review.json",
        root / "data/mallory/cases/ZOOKEEPER-12/sync-receipt.json",
    )
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(json.dumps({"receipt": str(output), "sha256": digest(output.read_bytes()),
                      "fault_trials": result["fault_trials"],
                      "retained": result["strict_same_actor_postfault_check_trials"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
