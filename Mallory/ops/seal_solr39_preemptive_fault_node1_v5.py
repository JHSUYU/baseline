#!/usr/bin/env python3
"""Seal node1 SOLR-39 v5 fault output and an independent exact-target scan."""

import hashlib
import json
import shutil
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
NAME = "SOLR-39-preemptive-fault-node1-v5"
RAW = BASE / "data/mallory/pilot_observations" / NAME
INDEX = RAW.with_suffix(".remote-sha256.txt")
GO = BASE / "Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v5/admission-full-node1.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
GO_SHA = "687c3a7669f8cdae0a03e22433724137705d476272d9d74aee6067804cd6a613"
SOURCE = "/users/ZhenyuLi/baseline/data/mallory/solr39_preemptive_fault_v5_node1/SOLR-39"
THROW = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
         "#lookupShardLeadersOfCollections()Ljava/util/List;@247:throw:1")
CHECK = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
         "#lookupShardLeadersOfCollections()Ljava/util/List;@246:branch:1")


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path):
    return json.loads(path.read_text())


def main():
    sys.path.insert(0, str(BASE / "Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v5"))
    from audit_trial import (FIELD, OccurrenceGraph, _injected_watcher_wrote,
                             events_from, join_field_events, markers_from,
                             validate_postfault_retained_reference, validate_return)

    remote = {}
    for line in INDEX.read_text().splitlines():
        digest, name = line.split("  ", 1)
        name = name.removeprefix("./")
        if name in remote or not name or ".." in Path(name).parts:
            raise RuntimeError(f"invalid remote index entry: {name}")
        remote[name] = digest
        if sha(RAW / name) != digest:
            raise RuntimeError(f"remote byte mismatch: {name}")
    if len(remote) != 320 or sha(GO) != GO_SHA:
        raise RuntimeError("remote index or case-local GO changed")
    go = load(GO)
    summary = load(RAW / "campaign-summary.json")
    if (go.get("go") is not True or go.get("case_id") != "SOLR-39" or
            summary.get("status") != "queue_exhausted" or
            summary.get("fault_trials_completed") != 3 or
            summary.get("go_receipt_sha256") != GO_SHA or
            summary.get("new_bug_confirmed") is not False):
        raise RuntimeError("terminal campaign outcome changed")

    trials = []
    raw_throw_count = 0
    for number in range(1, 4):
        trial = RAW / "trials" / f"r{number:04d}"
        result = load(trial / "result.json")
        audit = load(trial / "case-local-audit.json")
        rows = events_from(trial)
        applied = [row for row in rows if row.get("type") == "FAULT_APPLIED"]
        exact_throws = [row for row in rows if row.get("type") == "TARGET_THROW" and
                        row.get("site") == THROW]
        checks = [row for row in rows if row.get("type") == "TARGET_CHECK" and
                  row.get("site") == CHECK]
        raw_throw_count += len(exact_throws)
        if (result["trial_id"] != number or len(applied) != 1 or
                result.get("dispatch_attempt_id") != go["attempt_id"] or
                audit.get("valid") is not False):
            raise RuntimeError(f"fault/result identity changed in r{number:04d}")
        trials.append({
            "trial_id": number,
            "return_code": result["return_code"],
            "junit_validation": result["junit_validation"],
            "case_local_qualification": audit["qualification"],
            "fault_applied_seq": applied[0]["seq"],
            "fault_actor": applied[0]["node"],
            "fault_epoch": applied[0]["epoch"],
            "fault_occurrence": applied[0]["occurrence"],
            "fault_id": applied[0]["fault_id"],
            "exact_target_checks": len(checks),
            "postfault_target_check_actors": sorted({row["node"] for row in checks
                                                      if row["seq"] > applied[0]["seq"]}),
            "exact_target_throws": [{key: row.get(key) for key in
                                      ("seq", "site", "node", "epoch", "occurrence")}
                                     for row in exact_throws],
            "trace_gzip_sha256": sha(trial / "events.jsonl.gz"),
        })

    # The v5 candidate enumerator requires a watcher parent for a prior writer.
    # r0003 instead retains an exact Aliases reference from an admin publication.
    trial3 = RAW / "trials/r0003"
    rows = events_from(trial3)
    by_seq = {row["seq"]: row for row in rows}
    if len(by_seq) != len(rows):
        raise RuntimeError("duplicate trace sequence in r0003")
    applied = by_seq[32106]
    gates = [row for row in rows if row.get("site") == "SOLR39_PREFAULT_RESOURCE_MANAGER" and
             row.get("node") == applied["node"] and row.get("epoch") == applied["epoch"] and
             row.get("occurrence") == applied["occurrence"] and
             row.get("thread_id") == applied["thread_id"] and
             row["seq"] < applied["seq"]]
    if len(gates) != 1 or gates[0].get("key") != "/aliases.json" or gates[0].get("object") != "o10":
        raise RuntimeError("r0003 actual resource/manager gate changed")
    if _injected_watcher_wrote(rows, applied, "o10"):
        raise RuntimeError("r0003 faulted watcher unexpectedly published")
    markers, errors = markers_from(trial3)
    paired, collisions = join_field_events(rows, markers)
    if errors or len(paired) != len(markers) or any(collisions.values()):
        raise RuntimeError("r0003 exact reference pairing changed")
    path = {"cache_write_seq": 32094, "target_read_seq": 32892,
            "target_check_seq": 32895}
    write, read = validate_postfault_retained_reference(rows, paired, path, applied, "o10")
    exit_row, continuation = validate_return(rows, path)
    graph = OccurrenceGraph(tuple(rows), reject_coarse_roots=True)
    graph._add(write, read, "state_exact_ref", "same_volatile_owner_and_java_aliases_reference")
    graph._add(exit_row, continuation, "program_return", "balanced_same_thread_direct_nested_return")
    graph._time_cache.clear()
    witness = graph.event_path(write, by_seq[32895], include_candidates=False, require_edge=True)
    if witness is None or {edge.kind for edge in witness} != {"state_exact_ref", "program_return"}:
        raise RuntimeError("r0003 observed event-time path changed")
    identity = {row["field_seq"]: row for row in paired}
    if (write.get("key") != FIELD or read.get("key") != FIELD or
            identity[write["seq"]]["aliases_ref"] != 81 or
            identity[read["seq"]]["aliases_ref"] != 81 or
            identity[write["seq"]]["zk_version"] != 15 or
            identity[read["seq"]]["zk_version"] != 15):
        raise RuntimeError("r0003 exact Aliases reference changed")
    posthoc = {
        "trial_id": 3, "status": "source_backed_prior_admin_reference_path_observed",
        "manager_object": "o10", "node": "node2", "epoch": 0,
        "actual_resource": "/aliases.json", "prior_write_seq": write["seq"],
        "fault_applied_seq": applied["seq"], "postfault_read_seq": read["seq"],
        "getter_exit_seq": exit_row["seq"], "caller_continuation_seq": continuation["seq"],
        "target_check_seq": 32895, "aliases_ref": 81, "zk_version": 15,
        "prior_writer_context": write["context"],
        "faulted_watcher_context": applied["context"],
        "faulted_watcher_published_aliases": False,
        "observed_edge_kinds": [edge.kind for edge in witness],
        "target_throw_observed": False,
        "v5_audit_limit": "candidate path enumerator requires watcher-door parent for prior writer",
    }

    shutil.copy2(INDEX, RAW / "remote-sha256.txt")
    shutil.copy2(GO, RAW / "admission-go.json")
    (RAW / "independent-terminal-audit.json").write_text(json.dumps({
        "schema_version": 1, "case_id": "SOLR-39", "trials": trials,
        "exact_target_throw_count": raw_throw_count, "r0003_posthoc": posthoc,
        "new_bug_confirmed": False,
    }, indent=2, sort_keys=True) + "\n")
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("v5 fault evidence already sealed")
    manifest.write_text(json.dumps({"schema_version": 1, "files": members},
                                   indent=2, sort_keys=True) + "\n")
    with tarfile.open(archive, "w:gz") as output:
        for name in sorted(members):
            output.add(RAW / name, arcname=f"{NAME}/{name}", recursive=False)
    with tarfile.open(archive, "r:gz") as saved:
        found = {item.name.removeprefix(f"{NAME}/"):
                 hashlib.sha256(saved.extractfile(item).read()).hexdigest()
                 for item in saved if item.isfile()}
    if found != members:
        raise RuntimeError("archive member hash mismatch")
    receipt.write_text(json.dumps({
        "schema_version": 1, "case_id": "SOLR-39", "kind": "preemptive_fault_v5_terminal",
        "source_host": "node1", "source_path": SOURCE,
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": summary["status"], "duration_seconds": summary["elapsed_seconds"],
        "fault_trials_completed": 3, "case_local_valid_trials": [],
        "case_local_invalid_trials": summary["invalid_trials"],
        "raw_exact_target_throw_count": raw_throw_count,
        "r0003_posthoc_exact_prior_reference_path": True,
        "new_bug_confirmed": False,
        "admission_go_sha256": GO_SHA,
        "remote_file_count": len(remote), "remote_sha_index_sha256": sha(INDEX),
        "independent_terminal_audit_sha256": sha(RAW / "independent-terminal-audit.json"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive), "receipt_sha256": sha(receipt),
                      "member_count": len(members), "raw_exact_target_throw_count": raw_throw_count},
                     sort_keys=True))


if __name__ == "__main__":
    main()
