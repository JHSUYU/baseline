#!/usr/bin/env python3
"""Independently audit raw HDFS-28/29/30 trials added after V4 trial 128.

The historical 128 trials have a separately verified raw archive. This audit
reads each newer original-JUnit run instead of trusting the campaign's verdict.
It is safe to run against a live checkpoint: only completed entries are read.
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HISTORICAL = 128
OLD_STATE_SHA = "c990b52036d45f25a4370c611a2254fa3bdd580853a392226909ad04dd3a2b1b"
CASES = ("HDFS-28", "HDFS-29", "HDFS-30")
TARGETS = {
    "HDFS-28": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>#u12",
    "HDFS-29": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u12",
    "HDFS-30": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u23",
}
SELECTOR = ("marker", "siteId", "sourceKey", "occurrenceAddress", "hitOrdinal",
            "faultType", "requestApi")
RAW_FILES = ("manifest.json", "runtime_trace.jsonl", "fault-plan.tsv",
             "junit.log", "jacoco.exec")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def root_address(event: dict) -> str:
    address = event.get("occurrenceAddress", "")
    return address.split("/rpc:", 1)[0].split("/server:", 1)[0]


def selector_matches(event: dict, selected: dict, index: int) -> bool:
    return (event.get("planIndex") == index
            and all(event.get(key, "") == selected.get(key, "") for key in SELECTOR)
            and event.get("originSourceKey", event.get("sourceKey"))
            == selected.get("originSourceKey", selected.get("sourceKey"))
            and event.get("filePhase", "") == selected.get("filePhase", ""))


def has_owner(events: list[dict], fault: dict) -> bool:
    origin = fault.get("originSourceKey", fault.get("sourceKey"))
    root = root_address(fault)
    if origin in (None, "unregistered", "unknown-origin") or not root:
        return False
    begin = any(event.get("event") == "RECOVERY_BEGIN"
                and event["seq"] < fault["seq"]
                and event.get("sourceKey") == origin
                and event.get("blockId") == fault.get("blockId")
                and event.get("occurrenceAddress") == root
                and (fault.get("recoveryId") is None
                     or event.get("recoveryId") == fault.get("recoveryId"))
                for event in events)
    if not begin:
        return False
    if not fault.get("marker", "").startswith("FAULT:HDFS_FILE:"):
        return True
    phase = fault.get("filePhase")
    if phase not in ("initReplicaRecovery", "updateReplicaUnderRecovery"):
        return False
    if phase == "updateReplicaUnderRecovery" and fault.get("sourceKey") != origin:
        return False
    return any(event.get("event") == "SERVER_RECOVERY_BEGIN"
               and event["seq"] < fault["seq"]
               and event.get("sourceKey") == fault.get("sourceKey")
               and event.get("originSourceKey") == origin
               and event.get("blockId") == fault.get("blockId")
               and event.get("recoveryId") == fault.get("recoveryId")
               for event in events)


def audit_trial(number: int, trial: dict) -> dict:
    directory = ROOT / "runs" / f"trial-{number:03d}"
    if Path(trial["run"]).resolve() != directory:
        raise AssertionError(f"trial {number}: run path mismatch")
    for name in RAW_FILES:
        if not (directory / name).is_file():
            raise AssertionError(f"trial {number}: missing {name}")
    hashes = {name: sha256(directory / name) for name in RAW_FILES}
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("test") != "org.apache.hadoop.hdfs.server.datanode.TestBlockRecovery2#testRecoveryTimeout":
        raise AssertionError(f"trial {number}: original workload changed")
    if manifest.get("graphchecker_runtime_used") is not False or manifest.get("instrumented") is not True:
        raise AssertionError(f"trial {number}: unexpected runtime")
    if (manifest["returncode"] != trial["junit_exit"]
            or manifest["elapsed_seconds"] != trial["elapsed_seconds"]):
        raise AssertionError(f"trial {number}: manifest/ledger mismatch")
    plan = [line.split("\t") for line in (directory / "fault-plan.tsv").read_text().splitlines()]
    if len(plan) != len(trial["sequence"]):
        raise AssertionError(f"trial {number}: plan length mismatch")
    for selected, fields in zip(trial["sequence"], plan):
        expected = [str(selected[k]) for k in ("marker", "siteId", "sourceKey",
                                              "occurrenceAddress", "hitOrdinal", "faultType")]
        expected.append(selected.get("filePhase", ""))
        if fields != expected:
            raise AssertionError(f"trial {number}: on-disk fault plan differs")
    events = [json.loads(line) for line in (directory / "runtime_trace.jsonl").read_text().splitlines()
              if line.strip()]
    seqs = [row["seq"] for row in events]
    if seqs != sorted(set(seqs)):
        raise AssertionError(f"trial {number}: non-monotone trace sequence")
    matched = [row for row in events if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in events if row.get("event") == "FAULT_APPLIED"]
    selected = trial["sequence"]
    exact = (len(matched) == len(applied) == len(selected)
             and all(selector_matches(matched[i], selected[i], i)
                     and selector_matches(applied[i], selected[i], i)
                     and matched[i]["seq"] < applied[i]["seq"]
                     and has_owner(events, applied[i])
                     for i in range(len(selected)))
             and all(applied[i]["seq"] < matched[i + 1]["seq"]
                     for i in range(len(selected) - 1)))
    if (exact != trial["exact_order_applied"]
            or len(matched) != trial["matched_faults"]
            or len(applied) != trial["applied_faults"]):
        raise AssertionError(f"trial {number}: strict fault verdict mismatch")
    final = applied[-1] if exact else None
    counts, throws = {}, {}
    for case in CASES:
        checks = [row for row in events
                  if row.get("event") == "TARGET_CHECK"
                  and row.get("caseId") == case and row.get("siteId") == TARGETS[case]
                  and final is not None and row["seq"] > final["seq"]
                  and row.get("sourceKey") == final.get("originSourceKey", final.get("sourceKey"))
                  and row.get("blockId") == final.get("blockId")
                  and row.get("occurrenceAddress") == root_address(final)]
        emitted = [row for row in events
                   if row.get("event") == "TARGET_THROW"
                   and row.get("caseId") == case and row.get("siteId") == TARGETS[case]
                   and row.get("runtimeType") == "java.io.IOException"
                   and final is not None and row["seq"] > final["seq"]
                   and row.get("sourceKey") == final.get("originSourceKey", final.get("sourceKey"))
                   and row.get("blockId") == final.get("blockId")
                   and row.get("occurrenceAddress") == root_address(final)
                   and any(check.get("outcome") is True and check["seq"] < row["seq"]
                           for check in checks)]
        counts[case] = len(checks)
        throws[case] = len(emitted)
    if (counts != trial["post_fault_target_checks"]
            or throws != trial["target_exceptions_after_fault"]):
        raise AssertionError(f"trial {number}: target/throw verdict mismatch")
    coverage = {}
    for label in ("probes", "methods", "branch_counts"):
        path = directory / f"covered_{label}.txt"
        if not path.is_file():
            raise AssertionError(f"trial {number}: missing JaCoCo {label} export")
        rows = path.read_text().splitlines()
        if len(rows) != manifest[f"covered_{label}_count"]:
            raise AssertionError(f"trial {number}: coverage/manifest mismatch")
        if any("$MockitoMock$" in row or "/MiniDFSCluster#" in row for row in rows):
            raise AssertionError(f"trial {number}: unstable test coverage included")
        coverage[label] = len(rows)
    return {"trial": number, "sequence_id": trial["id"], "requested": len(selected),
            "matched": len(matched), "applied": len(applied), "exact": exact,
            "target_after_fault": counts, "target_throw_after_fault": throws,
            "junit_exit": manifest["returncode"], "elapsed_seconds": manifest["elapsed_seconds"],
            "coverage": coverage, "raw_sha256": hashes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="write an atomic JSON receipt")
    args = parser.parse_args()
    state_path = ROOT / "campaign-state.json"
    state = json.loads(state_path.read_text())
    receipt = json.loads((ROOT / "raw-evidence-receipt.json").read_text())
    if (receipt["completed_trials"] != HISTORICAL
            or receipt["raw_file_sha256"]["campaign-state.json"] != OLD_STATE_SHA
            or state["effective_resume"]["original_checkpoint_sha256"] != OLD_STATE_SHA):
        raise AssertionError("historical source checkpoint mismatch")
    with gzip.open(ROOT / "campaign-state.before-effective-resume.json.gz", "rb") as stream:
        if hashlib.sha256(stream.read()).hexdigest() != OLD_STATE_SHA:
            raise AssertionError("historical checkpoint backup mismatch")
    if sha256(ROOT / "raw-evidence.tar.gz") != receipt["archive_sha256"]:
        raise AssertionError("historical raw archive checksum mismatch")
    completed = state["completed"]
    if len(completed) < HISTORICAL:
        raise AssertionError("resumed checkpoint lost historical trials")
    audited = [audit_trial(number, trial)
               for number, trial in enumerate(completed[HISTORICAL:], HISTORICAL + 1)]
    strict = [trial for trial in completed if trial["exact_order_applied"]]
    checks = {case: {
        "effective_all": sum(bool(t["post_fault_target_checks"][case]) for t in strict),
        "effective_new": sum(bool(t["exact"] and t["target_after_fault"][case]) for t in audited),
        "target_throws_new": sum(t["target_throw_after_fault"][case] for t in audited),
    } for case in CASES}
    report = {"schema": 1, "checkpoint_sha256": sha256(state_path),
              "historical_trials": HISTORICAL, "historical_archive_sha256": receipt["archive_sha256"],
              "new_trials_audited": len(audited), "checks": checks,
              "new_exact_trials": sum(t["exact"] for t in audited),
              "new_junit_nonzero": sum(t["junit_exit"] != 0 for t in audited),
              "trials": audited}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + ".tmp")
        temporary.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        temporary.replace(args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "trials"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
