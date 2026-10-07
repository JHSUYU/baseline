#!/usr/bin/env python3
"""Audit the archived V3 pilot independently from the fuzz scheduler."""

import hashlib
import json
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
COLUMNS = ("seq", "nano", "thread", "phase", "core", "actor", "endpoint",
           "standard", "override", "effective", "detail")


def load_archive(name):
    manifest = json.loads((EVIDENCE / f"{name}-manifest.json").read_text())
    archive = EVIDENCE / manifest["archive"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest["archive_sha256"]
    with tarfile.open(archive, "r:gz") as tar:
        content = {}
        for item in manifest["files"]:
            raw = tar.extractfile(item["path"]).read()
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            content[item["path"]] = raw
    return content


def rows(raw):
    out = []
    for line in raw.decode().splitlines():
        cells = line.split("\t")
        assert len(cells) == len(COLUMNS), line
        event = dict(zip(COLUMNS, cells))
        event["seq"] = int(event["seq"])
        out.append(event)
    return out


def detail(raw):
    return dict(part.split("=", 1) for part in raw.split(";") if "=" in part)


def audit_trial(trial, manifest, events):
    planned = trial["plan"]["steps"]
    bind = {e["core"]: e["actor"] for e in events if e["phase"] == "ZK_BIND"}
    by_seq = {e["seq"]: e for e in events}
    applied = [e for e in events if e["phase"] == "FAULT_APPLIED_CONNECTION_LOSS"]
    matched = [e for e in events if e["phase"] == "FAULT_MATCHED"]
    if len(applied) != len(matched):
        raise AssertionError("matched/applied count differs")
    fault_receipts = []
    issues = []
    for index, event in enumerate(applied):
        if index >= len(planned):
            issues.append("unplanned_extra_fault")
            break
        step = planned[index]
        op, path, caller, actor_spec, ordinal = step["selector"].split("|")
        target_core = step["core"]
        senders = [e for e in events if e["phase"] in ("SEND_CREATE_COLLECTION", "SEND_ADD_REPLICA")
                   and e["core"] == target_core and e["seq"] < event["seq"]]
        sender = senders[-1] if senders else None
        producer = sender["detail"].rsplit("|sourceRole=", 1)[-1] if sender else None
        expected_actor = (bind.get(sender["actor"]) if actor_spec.startswith("OWNER_OF_CORE:")
                          else producer if actor_spec.startswith("PRODUCER_OF_CORE:") else None)
        io = by_seq.get(event["seq"] - 2)
        match = by_seq.get(event["seq"] - 1)
        expected_io = "IO_" + op
        if sender is None or actor_spec.rsplit(":", 1)[-1] != target_core:
            issues.append(f"step{index}_unbound_sender_core")
        if event["actor"] != expected_actor or expected_actor in (None, "UNBOUND"):
            issues.append(f"step{index}_wrong_actor")
        if event["core"] != path or io is None or io["phase"] != expected_io or io["core"] != path:
            issues.append(f"step{index}_wrong_io_resource")
        if io is None or io["actor"] != expected_actor or io["detail"] != caller:
            issues.append(f"step{index}_wrong_io_actor_or_caller")
        if match is None or match["phase"] != "FAULT_MATCHED" or match["actor"] != expected_actor:
            issues.append(f"step{index}_no_exact_match")
        attrs = detail(event["detail"])
        if (attrs.get("actorSpec") != actor_spec or attrs.get("caller") != caller or
                attrs.get("ordinal") != ordinal or attrs.get("index") != str(index)):
            issues.append(f"step{index}_wrong_fault_attributes")
        previous_fault_seq = applied[index - 1]["seq"] if index else 0
        lower = max(sender["seq"], previous_fault_seq) if sender else previous_fault_seq
        occurrence = sum(e["phase"] == expected_io and e["core"] == path and
                         e["actor"] == expected_actor and e["detail"] == caller and
                         lower < e["seq"] < event["seq"] for e in events) if sender else 0
        if occurrence != int(ordinal):
            issues.append(f"step{index}_wrong_occurrence")
        fault_receipts.append({"index": index, "sender_seq": sender["seq"] if sender else None,
                               "sender_node": sender["actor"] if sender else None,
                               "producer_role": producer, "owner_role": bind.get(sender["actor"]) if sender else None,
                               "io_seq": io["seq"] if io else None,
                               "match_seq": match["seq"] if match else None,
                               "applied_seq": event["seq"], "actual_actor": event["actor"],
                               "expected_actor": expected_actor, "op": op, "path": path,
                               "caller": caller, "ordinal": int(ordinal)})
    target_core = trial["target_core"]
    guards = [e for e in events if e["phase"] == "TARGET_GUARD" and e["core"] == target_core]
    guard_lineage = []
    for guard in guards:
        preceding = [e for e in events if e["phase"] in ("SEND_CREATE_COLLECTION", "SEND_ADD_REPLICA")
                     and e["core"] == target_core and e["seq"] < guard["seq"]]
        sender = preceding[-1] if preceding else None
        same_node = bool(sender and sender["actor"] == guard["actor"])
        guard_lineage.append({"guard_seq": guard["seq"], "sender_seq": sender["seq"] if sender else None,
                              "sender_node": sender["actor"] if sender else None,
                              "guard_node": guard["actor"], "same_node": same_node})
        if not same_node:
            issues.append("target_guard_actor_does_not_match_create_sender")
    last_fault = applied[-1]["seq"] if applied else None
    after = [e for e in guards if last_fault is not None and e["seq"] > last_fault]
    if len(applied) != len(planned) and trial["strict_exact_actor"]:
        issues.append("strict_ledger_with_missing_fault")
    if bool(after) != trial["target_after_last_fault"]:
        issues.append("target_after_ledger_disagrees")
    if any(e["detail"] == "missing" for e in after) != trial["target_exception"]:
        issues.append("target_exception_ledger_disagrees")
    if manifest["exit_code"] != trial["junit_exit"]:
        issues.append("junit_exit_ledger_disagrees")
    if issues and trial["strict_exact_actor"]:
        raise AssertionError(f"r{trial['number']:03d}: {issues}")
    return {"trial": trial["number"], "planned_faults": len(planned),
            "matched_faults": len(matched), "applied_faults": len(applied),
            "strict_exact_actor": trial["strict_exact_actor"], "faults": fault_receipts,
            "same_core_guards_before_fault": [e["seq"] for e in guards if last_fault is not None and e["seq"] < last_fault],
            "same_core_guards_after_fault": [{"seq": e["seq"], "actor_node": e["actor"],
                                               "branch": e["detail"]} for e in after],
            "target_guard_sender_lineage": guard_lineage,
            "junit_exit": manifest["exit_code"], "elapsed_seconds": manifest["elapsed_seconds"],
            "ledger_effective": trial["effective"], "ledger_target_exception": trial["target_exception"],
            "issues": issues}


def main():
    content = load_archive("v3-pilot-r003-r008")
    result = []
    for n in range(3, 9):
        folder = f"r{n:03d}"
        trial = json.loads(content[f"{folder}/trial.json"])
        manifest = json.loads(content[f"{folder}/manifest.json"])
        result.append(audit_trial(trial, manifest, rows(content[f"{folder}/actor-events.tsv"])))
    receipt = {"original_junit": "AddReplicaTest.testAddMultipleReplicas",
               "source_commit": "e27f44e", "trials": result,
               "attempts": len(result), "strict": sum(x["strict_exact_actor"] for x in result),
               "effective": sum(x["ledger_effective"] for x in result),
               "target_exceptions": sum(x["ledger_target_exception"] for x in result),
               "elapsed_seconds": round(sum(x["elapsed_seconds"] for x in result), 3)}
    out = EVIDENCE / "v3-pilot-r003-r008-audit.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: receipt[key] for key in ("attempts", "strict", "effective", "target_exceptions", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
