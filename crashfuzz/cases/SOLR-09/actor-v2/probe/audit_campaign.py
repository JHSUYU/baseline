#!/usr/bin/env python3
"""Audit every V2 receipt against its preserved raw actor-aware trace."""

import hashlib
import json
from pathlib import Path

from feedback import atomic_json, events, sequence_applied_in_order


WORK = Path(__file__).resolve().parents[1]
STATE = WORK / "evidence/campaign/state.json"
OUTPUT = WORK / "evidence/campaign/raw-audit.json"


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fields(parts: list[str]) -> dict[str, str]:
    return dict(part.split("=", 1) for part in parts if "=" in part)


def main() -> None:
    state = json.loads(STATE.read_text())
    if "finished_at" not in state:
        raise RuntimeError("Audit only a completed atomic V2 campaign")
    rows, errors = [], []
    for expected_number, trial in enumerate(state["trials"], start=1):
        number = trial["number"]
        folder = WORK / trial["evidence"]
        local = json.loads((folder / "trial.json").read_text())
        trace = events(folder / "events.tsv")
        matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
        applied = [e for e in trace if e["kind"].startswith("IO_APPLIED_")]
        strict = sequence_applied_in_order(trial["plan"], applied, matched, trace)
        last = applied[-1]["seq"] if applied else -1
        targets = [e for e in trace if applied and e["kind"] == "TARGET_CHECK"
                   and e["seq"] > last and len(e["parts"]) >= 2
                   and e["parts"][1] == "SOLR-09"]
        throws = [e for e in trace if applied and e["kind"] == "TARGET_EXCEPTION"
                  and e["seq"] > last and e["parts"] and e["parts"][0] == "SOLR-09"]
        checks = [e for e in trace if e["kind"] == "TARGET_CHECK"
                  and len(e["parts"]) >= 2 and e["parts"][1] == "SOLR-09"]
        bindings = [e for e in trace if e["kind"] == "TARGET_ACTORS_BOUND"]
        bound = fields(bindings[-1]["parts"]) if bindings else {}
        guard = fields(targets[-1]["parts"]) if targets else {}
        overseer_injections = [fields(e["parts"]) for e in applied
                               if "actor=target_overseer" in e["parts"]]
        replica_injections = [fields(e["parts"]) for e in applied
                              if "actor=target_replica_http" in e["parts"]]
        same_overseer_client = bool(
            bound.get("overseer_client_id") and
            guard.get("overseer_client_id") == bound["overseer_client_id"] and
            all(e.get("client_id") == bound["overseer_client_id"]
                for e in overseer_injections))
        same_replica_node = bool(
            bound.get("replica_node") and
            guard.get("replica_node") == bound["replica_node"] and
            all(e.get("node") == bound["replica_node"]
                for e in replica_injections))
        manifest = json.loads((folder / "manifest.json").read_text())
        row = {
            "number": number,
            "plan": trial["plan"],
            "matched": len(matched), "applied": len(applied),
            "strict_from_raw": strict,
            "target_after_final_fault_from_raw": bool(targets),
            "target_exception_after_final_fault_from_raw": bool(throws),
            "target_checks_from_raw": len(checks),
            "bound_overseer_client_id": bound.get("overseer_client_id"),
            "guard_overseer_client_id": guard.get("overseer_client_id"),
            "same_overseer_client": same_overseer_client,
            "same_replica_node": same_replica_node,
            "junit_exit": manifest["exit_code"],
            "elapsed_seconds": trial["elapsed_seconds"],
            "hashes": {name: digest(folder / name) for name in
                       ("events.tsv", "junit.log", "jacoco.exec", "trial.json")},
        }
        rows.append(row)
        if number != expected_number or local != trial:
            errors.append(f"trial {number}: checkpoint/receipt mismatch")
        for key, actual, recorded in (
            ("strict", strict, trial["all_faults_applied"]),
            ("target-after", bool(targets), trial["target_after_fault"]["SOLR-09"]),
            ("target-exception", bool(throws), trial["target_exception"]["SOLR-09"]),
            ("target-checks", len(checks), trial["target_checks"]["SOLR-09"]),
            ("junit-exit", manifest["exit_code"], trial["junit_exit"]),
            ("matched", len(matched), trial["faults_matched"]),
            ("applied", len(applied), trial["faults_applied"]),
        ):
            if actual != recorded:
                errors.append(f"trial {number}: {key}: raw={actual} recorded={recorded}")
        if strict and targets and row["hashes"]["jacoco.exec"] is None:
            errors.append(f"trial {number}: valid feedback lacks JaCoCo raw")
        if strict and targets and not same_overseer_client:
            errors.append(f"trial {number}: target and injected Overseer client mismatch")
        if strict and targets and not same_replica_node:
            errors.append(f"trial {number}: target and injected replica node mismatch")
        if any(row["hashes"][name] is None for name in ("events.tsv", "junit.log", "trial.json")):
            errors.append(f"trial {number}: missing mandatory raw evidence")
    summary = {
        "case_id": "SOLR-09", "identity_version": "actor-v2",
        "campaign_finished_at": state["finished_at"],
        "attempts": len(rows),
        "strict_from_raw": sum(row["strict_from_raw"] for row in rows),
        "valid_from_raw": sum(row["strict_from_raw"] and
                              row["target_after_final_fault_from_raw"] for row in rows),
        "target_exceptions_from_raw": sum(row["strict_from_raw"] and
                                           row["target_exception_after_final_fault_from_raw"]
                                           for row in rows),
        "errors": errors, "trials": rows,
    }
    atomic_json(OUTPUT, summary)
    print(json.dumps({k: summary[k] for k in (
        "attempts", "strict_from_raw", "valid_from_raw",
        "target_exceptions_from_raw", "errors")}, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
