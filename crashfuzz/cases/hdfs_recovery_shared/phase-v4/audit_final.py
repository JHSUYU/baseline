#!/usr/bin/env python3
"""Cross-check the finished per-check ledger against preserved raw traces."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import campaign


HERE = Path(__file__).resolve().parent


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    if (state.get("stop_reason") != "budget" or state.get("active") is not None
            or len(state["completed"]) != state["budget"]["max_trials"]):
        raise RuntimeError("campaign has not finished its budget")
    total_exact = 0
    nonzero_junit = 0
    target_throws_in_any_run = 0
    for number, trial in enumerate(state["completed"], 1):
        directory = Path(trial["run"])
        manifest = json.loads((directory / "manifest.json").read_text())
        trace = campaign.rows(directory)
        if manifest["elapsed_seconds"] != trial["elapsed_seconds"]:
            raise AssertionError("elapsed mismatch at trial " + str(number))
        if manifest["returncode"] != trial["junit_exit"]:
            raise AssertionError("JUnit code mismatch at trial " + str(number))
        nonzero_junit += manifest["returncode"] != 0
        sequences = [event["seq"] for event in trace]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise AssertionError("trace sequence order at trial " + str(number))
        applied = [event for event in trace if event.get("event") == "FAULT_APPLIED"]
        if len(applied) != trial["applied_faults"]:
            raise AssertionError("fault count mismatch at trial " + str(number))
        if trial["exact_order_applied"]:
            total_exact += 1
            if len(applied) != len(trial["sequence"]):
                raise AssertionError("strict fault count mismatch at trial " + str(number))
            for index, (event, selected) in enumerate(zip(applied, trial["sequence"])):
                if (event.get("planIndex") != index or
                        any(event.get(key) != selected.get(key)
                            for key in ("marker", "siteId", "sourceKey",
                                        "occurrenceAddress", "hitOrdinal", "faultType"))):
                    raise AssertionError("strict selector mismatch at trial " + str(number))
        target_throws_in_any_run += sum(event.get("event") == "TARGET_THROW"
                                        for event in trace)
        # The first calibrated file trial predates the derived root field in
        # campaign-state; derive the identity from its preserved raw event.
        last_fault = applied[-1] if trial["exact_order_applied"] else None
        last_root = campaign.recovery_root(last_fault) if last_fault else None
        if ("last_recovery_root" in trial and
                trial["last_recovery_root"] != last_root):
            raise AssertionError("stored recovery root mismatch at trial " + str(number))
        for case in campaign.CASES:
            observed_after = [event for event in trace
                              if event.get("event") == "TARGET_CHECK"
                              and event.get("caseId") == case
                              and event.get("siteId") == campaign.TARGET_SITE[case]
                              and applied and trial["exact_order_applied"]
                              and event["seq"] > applied[-1]["seq"]
                              and event.get("sourceKey") == trial["last_origin_source_key"]
                              and event.get("blockId") == trial["last_block_id"]
                              and event.get("occurrenceAddress")
                              == last_root]
            if len(observed_after) != trial["post_fault_target_checks"][case]:
                raise AssertionError("target identity mismatch at trial " + str(number)
                                     + " " + case)
        probes = directory / "covered_probes.txt"
        if not probes.is_file():
            raise AssertionError("missing derived coverage before archive: " + str(directory))
        probe_rows = probes.read_text().splitlines()
        if (len(probe_rows) != manifest["covered_probes_count"]
                or any("$MockitoMock$" in row or "/MiniDFSCluster#" in row
                       for row in probe_rows)):
            raise AssertionError("unstable coverage at trial " + str(number))
    for case in campaign.CASES:
        result = json.loads((campaign.CASE_ROOT / case / "result.json").read_text())
        with (campaign.CASE_ROOT / case / "trial-ledger-v4.csv").open() as stream:
            ledger_rows = list(csv.DictReader(stream))
        if len(ledger_rows) != len(state["completed"]):
            raise AssertionError("ledger size mismatch for " + case)
        if result["independent_campaign"]["strict_target_trials"] != sum(
                bool(trial["exact_order_applied"] and
                     trial["post_fault_target_checks"][case])
                for trial in state["completed"]):
            raise AssertionError("case target count mismatch for " + case)
    report = {
        "completed_trials": len(state["completed"]),
        "strict_trials": total_exact,
        "junit_nonzero_trials": nonzero_junit,
        "raw_target_throws_in_any_run": target_throws_in_any_run,
        "checks": {case: {
            "strict_target_retaining_trials": sum(
                bool(trial["exact_order_applied"] and
                     trial["post_fault_target_checks"][case])
                for trial in state["completed"]),
            "target_exceptions_after_fault": sum(
                bool(trial["target_exceptions_after_fault"][case])
                for trial in state["completed"]),
        } for case in campaign.CASES},
    }
    campaign.atomic_json(HERE / "final-audit.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
