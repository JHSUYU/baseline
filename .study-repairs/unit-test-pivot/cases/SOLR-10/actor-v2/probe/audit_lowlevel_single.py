#!/usr/bin/env python3
"""Recount the bounded single-underlying-failure SOLR-40 control from raw files."""

import hashlib
import json
from pathlib import Path

from feedback import atomic_json, checked_target_identity, events, runtime_actor
from replay_candidate import persisted_alias


CASE = Path(__file__).resolve().parents[1]
OUT = CASE / "evidence/lowlevel-single-retry-v10"
STATE = CASE / "evidence/campaign-v4/state.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    build = json.loads((OUT / "build-receipt.json").read_text())
    expected = json.loads((OUT / "summary.json").read_text())["runs"]
    issues = []
    if sha(STATE) != build["frozen_campaign_state_sha256"]:
        issues.append("original campaign checkpoint changed")
    if build["junit_class_sha256"] != build["original_junit_class_sha256"] or \
            build["route_class_sha256"] != build["original_route_class_sha256"]:
        issues.append("original JUnit or routed alias target class changed")
    rows = []
    for number, recorded in enumerate(expected, 1):
        directory = OUT / f"trial-{number:03d}"
        trace = events(directory / "events.tsv")
        clocks = {}
        for line in (directory / "events.tsv").read_text().splitlines():
            cells = line.split("\t", 2)
            if len(cells) > 1 and cells[0].isdigit() and cells[1].isdigit():
                clocks[int(cells[0])] = int(cells[1])
        manifest = json.loads((directory / "manifest.json").read_text())
        entry = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        underlying = [e for e in trace if e["kind"] == "IO_UNDERLYING_CONNECTION_LOSS"]
        success = [e for e in trace if e["kind"] == "IO_UNDERLYING_RETRY_SUCCESS"]
        if len(entry) != 1 or len(underlying) != 1 or len(success) > 1:
            issues.append(f"trial {number}: expected exactly one entry and underlying fault")
            continue
        first, low = entry[0], underlying[0]
        actor = runtime_actor(low)
        if (not actor or runtime_actor(first) != actor or actor[0] != "jetty:node1" or
                first["seq"] >= low["seq"] or low["parts"][:2] != ["GET_DATA", "/aliases.json"]):
            issues.append(f"trial {number}: wrong physical actor, alias path, or fault order")
        guards = [e for e in trace if e["kind"] == "TARGET_CHECK" and
                  len(e["parts"]) > 1 and e["parts"][1] == "SOLR-40" and
                  e["seq"] > low["seq"] and runtime_actor(e) == actor]
        throws = [e for e in trace if e["kind"] == "TARGET_EXCEPTION" and
                  e["parts"] and e["parts"][0] == "SOLR-40" and
                  e["seq"] > low["seq"] and runtime_actor(e) == actor]
        if len(throws) > 1 or (throws and not any(e["parts"][0] == "missing" for e in guards)):
            issues.append(f"trial {number}: target exception has no missing-properties guard")
        if not checked_target_identity(trace):
            issues.append(f"trial {number}: target identity invalid")
        persisted, records = persisted_alias(directory / "scratch")
        junit = (directory / "junit.log").read_text(errors="replace")
        if throws and (manifest["exit_code"] == 0 or not persisted or
                       "Routed alias myalias appears to have been removed" not in junit):
            issues.append(f"trial {number}: failed JUnit or persisted alias evidence missing")
        if success and manifest["exit_code"] != 0:
            issues.append(f"trial {number}: retry success did not leave a passing JUnit")
        raw_sha = {name: sha(directory / name) for name in
                   ("events.tsv", "manifest.json", "junit.log", "jacoco.exec")}
        if any(recorded.get(key) != value for key, value in (
                ("events_sha256", raw_sha["events.tsv"]),
                ("junit_log_sha256", raw_sha["junit.log"]),
                ("jacoco_sha256", raw_sha["jacoco.exec"]))):
            issues.append(f"trial {number}: raw SHA disagrees with run receipt")
        row = {
            "trial": number, "entry_fault_seq": first["seq"],
            "underlying_failure_seq": low["seq"], "runtime_actor": actor,
            "underlying_failures": len(underlying), "retry_success_seq": success[0]["seq"] if success else None,
            "same_reader_guard_values": [e["parts"][0] for e in guards],
            "same_reader_target_exception": bool(throws),
            "failure_to_first_guard_ms": round((clocks[guards[0]["seq"]] - clocks[low["seq"]]) / 1e6, 3) if guards else None,
            "failure_to_retry_success_ms": round((clocks[success[0]["seq"]] - clocks[low["seq"]]) / 1e6, 3) if success else None,
            "target_before_retry_success": bool(success and any(e["seq"] < success[0]["seq"] for e in guards)),
            "persisted_alias_in_zk_txlog": persisted, "alias_txn_records": records,
            "junit_exit": manifest["exit_code"], "raw_sha256": raw_sha,
        }
        rows.append(row)
    result = {
        "model": build["model"], "original_source_commit": build["source_commit"],
        "unchanged_junit_class_sha256": build["junit_class_sha256"],
        "unchanged_route_class_sha256": build["route_class_sha256"],
        "injected_zkclient_class_sha256": build["zkclient_class_sha256"],
        "injected_probe_class_sha256": build["probe_class_sha256"],
        "frozen_campaign_state_sha256": build["frozen_campaign_state_sha256"],
        "trials": rows, "issues": issues,
    }
    atomic_json(OUT / "control-audit.json", result)
    print(json.dumps({"trials": len(rows), "target_exceptions": sum(
        item["same_reader_target_exception"] for item in rows),
        "retry_successes": sum(item["retry_success_seq"] is not None for item in rows),
        "issues": issues}, sort_keys=True), flush=True)
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
