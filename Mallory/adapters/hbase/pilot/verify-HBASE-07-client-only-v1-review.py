#!/usr/bin/env python3
"""Recompute the HBASE-07 client-only precision review from frozen raw trials.

Run with PYTHONPATH pointing first at the pinned 96dd core release, then the
repository root. This verifier never reads the mutable canonical case link.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import Mallory.core.graph as graph_module
from Mallory.core.graph import OccurrenceGraph


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def address(event: dict) -> tuple:
    return tuple(event.get(k) for k in ("node", "epoch", "occurrence", "thread_id"))


def check_hash(path: Path, expected: str) -> None:
    require(path.is_file() and sha256(path) == expected, f"SHA mismatch: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--review", type=Path,
                        default=Path("data/mallory/quality_reviews/hbase07_client_only_v1/HBASE-07.json"))
    args = parser.parse_args()
    root = args.repo.resolve()
    review_path = args.review if args.review.is_absolute() else root / args.review
    review = load(review_path)
    campaign = root / review["versioned_campaign_path"]
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    check_hash(result_path, review["campaign_result_sha256"])
    check_hash(audit_path, review["campaign_audit_sha256"])
    check_hash(campaign / "config.json", review["campaign_config_sha256"])
    check_hash(root / review["archive_path"], review["archive_sha256"])
    check_hash(root / "data/mallory/HBASE-07/campaigns/client-only-v1-receipt.json",
               review["collector_receipt_sha256"])
    core_manifest = root / "Mallory/dispatch/releases" / review["core_release_id"] / "manifest.json"
    check_hash(core_manifest, review["core_manifest_sha256"])
    require(Path(graph_module.__file__).resolve().is_relative_to(core_manifest.parent.resolve()),
            "verifier did not import pinned 96dd graph")
    campaign_result, audit = load(result_path), load(audit_path)
    require(campaign_result["case_id"] == review["case_id"] == "HBASE-07", "wrong case")
    require(campaign_result["status"] == review["campaign_status"] == "queue_exhausted",
            "wrong terminal status")
    require(campaign_result["fault_trials_completed"] == review["fault_trials_completed"] == 27,
            "wrong trial count")
    require(campaign_result["exact_exception_trials"] == review["selected_exception_trials"] == 0,
            "selected target exception present")
    require(audit["campaign_result_sha256"] == review["campaign_result_sha256"] and
            audit["applied_fault_identity_valid"] and audit["archive_integrity_valid"] and
            audit["guidance_consistent"], "frozen audit rejected result")
    require(audit.get("report_gate_passed") is True,
            "frozen audit quality gate failed")
    require(audit.get("require_event_time_paths") is True and
            audit.get("reject_coarse_roots") is True and
            audit.get("replay_identity_mode") == "occurrence_hit" and
            audit.get("target_claims_reverified") is True and
            audit.get("target_retained_fault_trials") == 27 and
            audit.get("unknown_applied_faults") == 0,
            "frozen audit precision settings changed")
    target_sites = set(campaign_result["target"]["check_sites"])
    require(len(target_sites) == 1 and campaign_result["target"]["exception_class"] ==
            "org.apache.hadoop.hbase.TableNotDisabledException", "target changed")
    rows = review["trials"]
    ids = [row["trial_id"] for row in rows]
    require(ids == list(range(1, 28)) == review["qualifying_trial_ids"], "trial IDs incomplete")
    require(review["strict_injected_trials"] == review["strict_postfault_event_path_trials"] == 27,
            "review count mismatch")
    for row in rows:
        trial_id = row["trial_id"]
        trial = campaign / "trials" / f"r{trial_id:04d}"
        check_hash(trial / "result.json", row["trial_result_sha256"])
        check_hash(trial / "plan.json", row["plan_sha256"])
        check_hash(trial / "events.jsonl.gz", row["trace_gzip_sha256"])
        trial_result, plan = load(trial / "result.json"), load(trial / "plan.json")
        require(trial_result["trial_id"] == trial_id and trial_result["case_id"] == "HBASE-07",
                f"trial identity r{trial_id:04d}")
        require(trial_result["feedback"]["all_faults_matched"] and
                trial_result["feedback"]["all_faults_applied"] and
                trial_result["feedback"]["all_faults_effective"],
                f"fault delivery r{trial_id:04d}")
        require(len(plan["faults"]) == len(row["faults"]) and len(plan["faults"]) > 0,
                f"fault count r{trial_id:04d}")
        raw = gzip.decompress((trial / "events.jsonl.gz").read_bytes())
        require(hashlib.sha256(raw).hexdigest() == row["trace_raw_sha256"] ==
                trial_result["events_sha256"], f"raw trace r{trial_id:04d}")
        events = tuple(json.loads(line) for line in raw.splitlines() if line)
        by_id = {event.get("id"): event for event in events}
        require(len(by_id) == len(events), f"duplicate event IDs r{trial_id:04d}")
        applied = [event for event in events if event.get("type") == "FAULT_APPLIED"]
        require(len(applied) == len(row["faults"]), f"extra applied fault r{trial_id:04d}")
        for planned, witness in zip(plan["faults"], row["faults"]):
            require(planned["fault_id"] == witness["fault_id"] and
                    planned["point"] == witness["point"] and
                    planned["fault_type"] == "EXCEPTION" and
                    planned["exception_class"] == "java.io.IOException",
                    f"planned identity r{trial_id:04d}")
            door, match, effect = (by_id[witness[key]] for key in
                                   ("door_event_id", "matched_event_id", "applied_event_id"))
            require([event["type"] for event in (door, match, effect)] ==
                    ["DOOR_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED"],
                    f"fault event types r{trial_id:04d}")
            require([event["seq"] for event in (door, match, effect)] ==
                    [witness[key] for key in ("door_seq", "matched_seq", "applied_seq")] and
                    door["seq"] < match["seq"] < effect["seq"],
                    f"fault order r{trial_id:04d}")
            require(address(door) == address(match) == address(effect) ==
                    (witness["node"], witness["epoch"], witness["occurrence"], witness["thread_id"]),
                    f"fault actor r{trial_id:04d}")
            require(all(event["site"] == witness["point"]["site"] and
                        event["hit"] == witness["point"]["hit"] for event in (door, match, effect)) and
                    effect["node"] == witness["point"]["node"] and
                    effect["epoch"] == witness["point"]["epoch"] and
                    effect["occurrence"] == witness["point"]["occurrence"] and
                    match["fault_id"] == effect["fault_id"] == witness["fault_id"],
                    f"exact occurrence/hit r{trial_id:04d}")
        last = max(applied, key=lambda event: event["seq"])
        require((last["id"], last["seq"]) ==
                (row["last_applied_event_id"], row["last_applied_seq"]),
                f"last fault r{trial_id:04d}")
        target = by_id[row["postfault_target_check_event_id"]]
        require(target["type"] == "TARGET_CHECK" and target["site"] in target_sites and
                target["seq"] == row["postfault_target_check_seq"] and
                target["seq"] > last["seq"] and target.get("outcome") == "TAKEN",
                f"selected nonthrowing target r{trial_id:04d}")
        require(address(target) ==
                (row["postfault_target_node"], row["postfault_target_epoch"],
                 row["postfault_target_occurrence"], row["postfault_target_thread_id"]) ==
                address(last) and row["same_actor_occurrence"] is True and
                target["node"] != "unknown" and isinstance(target["thread_id"], int),
                f"affected actor retention r{trial_id:04d}")
        require(not any(event.get("type") == "TARGET_THROW" and
                        event.get("site") == campaign_result["target"]["throw_site"]
                        for event in events), f"selected exception r{trial_id:04d}")
        path = OccurrenceGraph(events, reject_coarse_roots=True).event_path(
            last, target, require_edge=True)
        require(path is not None and len(path) > 0, f"no strict event path r{trial_id:04d}")
        observed = []
        for edge in path:
            producer, consumer = by_id[edge.producer_event], by_id[edge.consumer_event]
            require(edge.certainty == "observed" and producer["seq"] < consumer["seq"] and
                    producer["seq"] > last["seq"] and consumer["seq"] < target["seq"],
                    f"noncausal path edge r{trial_id:04d}")
            observed.append({"kind": edge.kind,
                             "producer_event_id": producer["id"], "producer_seq": producer["seq"],
                             "producer_node": producer["node"],
                             "consumer_event_id": consumer["id"], "consumer_seq": consumer["seq"],
                             "consumer_node": consumer["node"]})
        require(observed == row["event_time_path"], f"witness path changed r{trial_id:04d}")
    print(f"PASS HBASE-07: {len(rows)} exact applied faults and later named target checks; "
          f"{len(rows)} strict time-respecting observed paths; 0 selected exceptions")


if __name__ == "__main__":
    main()
