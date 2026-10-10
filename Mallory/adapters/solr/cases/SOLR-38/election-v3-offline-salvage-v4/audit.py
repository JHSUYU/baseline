#!/usr/bin/env python3
"""SHA-bound, JVM-free correction audit of the sealed SOLR-38 v3 pilot."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V3 = HERE.parent / "election-strict-pilot-node1-v3"
ARCHIVE = ROOT / "data/mallory/evidence_archives/SOLR-38-strict-fault-node1-v3.tar.gz"
MEMBERS = ARCHIVE.with_suffix("").with_suffix(".members.json")
RECEIPT = ARCHIVE.with_suffix("").with_suffix(".receipt.json")
ARCHIVE_SHA = "19440785b619ef7d80f0105ef86359767f35c674728421d875a0d9e3ffc4f455"
PREFIX = "SOLR-38-strict-fault-node1-v3/"
sys.path.insert(0, str(V3))
import config_v3  # noqa: E402
import graph_overlay as v3_graph  # noqa: E402
import preflight as v3_preflight  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CanonicalSolr38Graph(v3_graph.SourceBackedSolr38Graph):
    """Remove sampled duplicates of an independently proved exact event pair.

    The v3 graph held both a candidate sampled-version edge and an observed
    source-backed edge for the same write/read IDs. The pinned backward walk
    sorts only those IDs, so Python set order chose either edge at random.
    Removing only that duplicate makes the closure fingerprint deterministic.
    """

    def __init__(self, events: tuple[dict, ...], *, reject_coarse_roots: bool = False):
        super().__init__(events, reject_coarse_roots=reject_coarse_roots)
        proved = {(e.producer_event, e.consumer_event, e.kind)
                  for e in self.edges
                  if e.kind == "state" and e.evidence.startswith("solr38_source_backed")}
        self.candidate_edges = {e for e in self.candidate_edges
                                if (e.producer_event, e.consumer_event, e.kind) not in proved}
        self._time_cache.clear()


def read_sealed() -> tuple[dict, dict, list[tuple[dict, tuple[dict, ...]]], dict]:
    if sha(ARCHIVE.read_bytes()) != ARCHIVE_SHA:
        raise ValueError("sealed v3 archive SHA differs")
    member_index = json.loads(MEMBERS.read_text())["files"]
    receipt = json.loads(RECEIPT.read_text())
    if receipt.get("archive_sha256") != ARCHIVE_SHA:
        raise ValueError("archive receipt SHA differs")
    wanted = ["config.json", "result.json", "offline-causal-audit.json"]
    for i in range(3):
        wanted.extend([f"trials/r{i:04d}/result.json",
                       f"trials/r{i:04d}/events.jsonl.gz"])
    blobs = {}
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        for name in wanted:
            item = archive.extractfile(PREFIX + name)
            if item is None:
                raise ValueError(f"sealed archive missing {name}")
            blob = item.read()
            if sha(blob) != member_index.get(name):
                raise ValueError(f"member SHA differs: {name}")
            blobs[name] = blob
    config = json.loads(blobs["config.json"])
    summary = json.loads(blobs["result.json"])
    old_audit = json.loads(blobs["offline-causal-audit.json"])
    trials = []
    for i in range(3):
        name = f"trials/r{i:04d}"
        trial = json.loads(blobs[f"{name}/result.json"])
        raw_events = gzip.decompress(blobs[f"{name}/events.jsonl.gz"])
        events = tuple(json.loads(line) for line in raw_events.splitlines())
        if trial.get("events_sha256") != sha(raw_events):
            raise ValueError(f"trial r{i:04d} trace SHA differs")
        trials.append((trial, events))
    return config, summary, trials, old_audit


def selected_postfault_path(trial: dict, events: tuple[dict, ...]) -> dict:
    if (len(trial["plan"]) != 1 or not trial["feedback"].get("all_faults_effective")
            or trial["feedback"].get("target_threw")
            or trial["feedback"].get("target_exception_candidate")):
        raise ValueError("trial is not one effective, nonthrowing exact fault")
    fault = trial["plan"][0]
    point = fault["point"]
    by_id = {event["id"]: event for event in events}
    matches = [e for e in events if e.get("type") == "FAULT_MATCHED"
               and e.get("fault_id") == fault["fault_id"]]
    applied = [e for e in events if e.get("type") == "FAULT_APPLIED"
               and e.get("fault_id") == fault["fault_id"]]
    if len(matches) != 1 or len(applied) != 1:
        raise ValueError("fault match/application is not unique")
    match, application = matches[0], applied[0]
    keys = ("node", "epoch", "site", "door_ordinal")
    if not all(match.get(k) == application.get(k) == point.get(k) for k in keys):
        raise ValueError("fault runtime identity differs from selected point")
    if not (match["seq"] < application["seq"] and
            application.get("exception_class") == fault["exception_class"]):
        raise ValueError("typed fault receipt is inconsistent")
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"
             and all(e.get(k) == point.get(k) for k in keys)
             and e.get("occurrence") == application.get("occurrence")
             and e.get("thread_id") == application.get("thread_id")
             and e["seq"] < match["seq"]]
    if len(doors) != 1:
        raise ValueError("selected pre-fault door is not unique")
    door = doors[0]
    graph = CanonicalSolr38Graph(events, reject_coarse_roots=True)
    candidates = []
    for witness in v3_graph.unique_writer.witnesses(list(events)):
        if witness["door"] != door["id"]:
            continue
        write = by_id[witness["value_write"]]
        read = by_id[witness["value_read"]]
        check = by_id[witness["target"]]
        native_write = by_id[witness["native_write"]]
        native_read = by_id[witness["native_read"]]
        chain = (door, match, application, native_write, write,
                 native_read, read, check)
        if not all(e.get("node") == application["node"] and
                   e.get("epoch") == application["epoch"] and
                   e.get("thread_id") == application["thread_id"] for e in chain):
            continue
        if not all(e.get("object") == witness["descriptor_object"]
                   for e in (native_write, write, native_read, read)):
            continue
        if not (application["seq"] < native_write["seq"] < write["seq"] <
                native_read["seq"] < read["seq"] < check["seq"]):
            continue
        if (read["occurrence"] != check["occurrence"] or
                witness["last_writer_before_read"] != native_write["id"] or
                witness["intervening_native_writes"] != 0 or
                witness["target_outcome"] != "FALLTHROUGH"):
            continue
        path = graph.event_path(door, check, require_edge=True)
        if not path or not any(e.kind == "state" and
                               e.producer_event == write["id"] and
                               e.consumer_event == read["id"] and
                               e.evidence.startswith("solr38_source_backed")
                               for e in path):
            continue
        candidates.append({"fault_id": fault["fault_id"],
                           "node": application["node"], "epoch": application["epoch"],
                           "thread_id": application["thread_id"],
                           "door_occurrence": door["occurrence"],
                           "target_occurrence": check["occurrence"],
                           "descriptor_object": witness["descriptor_object"],
                           "event_ids": {"door": door["id"], "fault_matched": match["id"],
                                         "fault_applied": application["id"],
                                         "native_write": native_write["id"],
                                         "value_write": write["id"],
                                         "native_read": native_read["id"],
                                         "value_read": read["id"], "target": check["id"]},
                           "target_outcome": check["outcome"],
                           "path_edges": [{"kind": e.kind, "evidence": e.evidence,
                                           "producer_event": e.producer_event,
                                           "consumer_event": e.consumer_event}
                                          for e in path]})
    if not candidates:
        raise ValueError("no exact same-actor source-backed postfault target path")
    return min(candidates, key=lambda row: row["event_ids"]["target"])


def audit() -> dict:
    v3_preflight.main()
    v3_graph.unique_writer.verify_source(v3_graph.SOURCE)
    config, summary, trials, old_audit = read_sealed()
    if (summary.get("status") != "queue_exhausted" or
            summary.get("fault_trials_completed") != 2 or
            summary.get("exact_exception_trials") != 0 or
            not summary.get("healthy_seed_valid") or
            old_audit.get("report_gate_passed") is not False or
            not old_audit.get("archive_integrity_valid") or
            not old_audit.get("applied_fault_identity_valid") or
            not old_audit.get("target_claims_reverified") or
            not old_audit.get("healthy_closure_proven") or
            old_audit.get("unknown_applied_faults") != 0 or
            config.get("budget", {}).get("trials") != 4 or
            config.get("budget", {}).get("max_faults_per_trial") != 1 or
            config.get("case_id") != "SOLR-38"):
        raise ValueError("sealed terminal pilot identity or outcome differs")
    sys.path.insert(0, str(config_v3.RELEASE))
    from Mallory.core import feedback
    from Mallory.core.audit import _edge_fingerprints
    from Mallory.core.events import Trace
    feedback.OccurrenceGraph = CanonicalSolr38Graph
    binding = summary.get("target_binding") or {}
    rows = []
    for i, (trial, events) in enumerate(trials):
        if (trial["trial_id"] != i or trial["return_code"] != 0 or trial["timed_out"] or
                trial["junit_validation"]["status"] != "passed"):
            raise ValueError(f"r{i:04d} terminal JUnit evidence differs")
        target = {**config["target"], **(binding if i else {})}
        replay = feedback.analyze(Trace(events), target, trial["plan"],
                                  return_code=trial["return_code"],
                                  timed_out=trial["timed_out"],
                                  allow_local_timeline_doors=False,
                                  reject_coarse_roots=True,
                                  require_event_time_paths=True)
        replay2 = feedback.analyze(Trace(events), target, trial["plan"],
                                   return_code=trial["return_code"],
                                   timed_out=trial["timed_out"],
                                   allow_local_timeline_doors=False,
                                   reject_coarse_roots=True,
                                   require_event_time_paths=True)
        if (_edge_fingerprints(replay) != _edge_fingerprints(replay2) or
                replay["status"] != trial["feedback"]["status"] or
                set(replay["closure_occurrences"]) !=
                set(trial["feedback"]["closure_occurrences"])):
            raise ValueError(f"r{i:04d} canonical replay differs")
        row = {"trial_id": i, "canonical_closure_edge_fingerprints":
               sorted(_edge_fingerprints(replay)),
               "canonical_graph_state_edges": replay["graph"]["edges_by_kind"].get("state", 0),
               "original_gate_flag": trial["feedback"].get("solr38_strict_fault_acceptance")}
        if i:
            row["postfault_path"] = selected_postfault_path(trial, events)
        rows.append(row)
    healthy = trials[0][0]
    fields = ("node", "epoch", "site", "door_ordinal")
    eligible = {tuple(door["point"][key] for key in fields)
                for door in healthy["feedback"]["doors"]
                if door.get("in_closure") and door["site"].startswith(
                    v3_graph.unique_writer.DOOR)}
    selected = {tuple(trial["plan"][0]["point"][key] for key in fields)
                for trial, _ in trials[1:]}
    if len(eligible) != 2 or eligible != selected:
        raise ValueError("two healthy strict door points were not both exhausted")
    return {"schema_version": 1, "case_id": "SOLR-38",
            "kind": "sealed_v3_offline_gate_correction",
            "archive_sha256": ARCHIVE_SHA,
            "archive_receipt_sha256": sha(RECEIPT.read_bytes()),
            "old_offline_audit_sha256": json.loads(RECEIPT.read_text())[
                "offline_causal_audit_sha256"],
            "v3_graph_overlay_sha256": sha((V3 / "graph_overlay.py").read_bytes()),
            "source_review": "ConnectionLossException at getChildren is caught in waitForReplicasToComeUp; the election loop retries before setLeader(true). Both injected trials subsequently reached the target on the fault actor with a source-backed CloudDescriptor value path.",
            "old_gate_false_reason": "v3 runner read absent pinned-feedback target_check_reached; generic audit same_actor_target_after_fault applies only to local-timeline doors; r0001 closure fingerprint chose candidate versus observed duplicate state edges nondeterministically",
            "bounded_pilot_evidence_valid": True,
            "configured_campaign_complete": True,
            "eligible_for_canonical_completed_row": True,
            "completion_basis": "fresh strict healthy seed; two of four permitted fault trials ran; both eligible in-closure typed points were exercised; fault queue naturally exhausted; both exact same-actor postfault target paths verified offline",
            "fault_trial_cap": 4,
            "fault_trials_run": 2,
            "healthy_eligible_exact_door_points": len(eligible),
            "same_actor_postfault_strict_target_trials": 2,
            "exact_target_exception_trials": 0,
            "new_bug_confirmed": False,
            "terminal_status": summary["status"],
            "duration_seconds": summary["duration_seconds"],
            "trials": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "salvage-receipt.json")
    args = parser.parse_args()
    result = audit()
    args.out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"case_id": result["case_id"],
                      "same_actor_postfault_strict_target_trials":
                          result["same_actor_postfault_strict_target_trials"],
                      "bounded_pilot_evidence_valid": result["bounded_pilot_evidence_valid"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
