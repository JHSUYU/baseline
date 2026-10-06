#!/usr/bin/env python3
"""Recheck HDFS-12 ordinary and key-delivery campaigns from raw traces."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAMPAIGNS = {
    "ordinary_sasl": HERE / "campaign-state.json",
    "long_lived_control": HERE / "long-lived/control-plane/campaign-state.json",
}
OUT = HERE / "audit-all.json"
SELECTOR = ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal", "faultType")
CHECK = "BlockTokenSecretManager.retrievePassword#L511"
THROW = "BlockTokenSecretManager.retrievePassword#L514"


def audit_trial(trial: dict) -> dict:
    directory = Path(trial["run"])
    manifest = json.loads((directory / "manifest.json").read_text())
    events = [json.loads(line) for line in
              (directory / "runtime_trace.jsonl").read_text().splitlines() if line]
    matched = [row for row in events if row["event"] == "FAULT_MATCHED"]
    applied = [row for row in events if row["event"] == "FAULT_APPLIED"]
    sequence = trial["sequence"]
    exact = len(matched) == len(applied) == len(sequence) and all(
        matched[index].get("planIndex") == applied[index].get("planIndex") == index
        and all(matched[index].get(field) == applied[index].get(field) ==
                fault[field] for field in SELECTOR)
        and matched[index]["seq"] < applied[index]["seq"]
        for index, fault in enumerate(sequence)) and all(
            applied[index]["seq"] < matched[index + 1]["seq"]
            for index in range(len(sequence) - 1))
    last = applied[-1]["seq"] if exact else None
    checks = [row for row in events if row["event"] == "TARGET_CHECK"
              and row.get("siteId") == CHECK and last is not None and row["seq"] > last]
    all_checks = [row for row in events if row["event"] == "TARGET_CHECK"
                  and row.get("siteId") == CHECK]
    first_key = all_checks[0].get("keyId") if all_checks else None
    rotated_key_after_fault = bool(checks) and any(
        row.get("keyId") != first_key for row in checks)
    throws = [row for row in events if row["event"] == "TARGET_THROW"
              and row.get("siteId") == THROW
              and row.get("exception") ==
              "org.apache.hadoop.security.token.SecretManager$InvalidToken"
              and last is not None and row["seq"] > last]
    assert exact == trial["exact_order_applied"], trial["id"]
    assert (exact and bool(checks)) == trial["valid_for_feedback"], trial["id"]
    assert bool(checks) == trial["target_after_fault"], trial["id"]
    assert len(checks) == trial["target_checks_after_fault"], trial["id"]
    assert len(throws) == trial["target_exception_after_fault"], trial["id"]
    assert len(matched) == trial["matched_faults"], trial["id"]
    assert len(applied) == trial["applied_faults"], trial["id"]
    assert manifest["returncode"] == trial["junit_exit"], trial["id"]
    assert manifest["elapsed_seconds"] == trial["elapsed_seconds"], trial["id"]
    return {"id": trial["id"], "exact": exact, "target_after_fault": bool(checks),
            "rotated_key_after_fault": rotated_key_after_fault,
            "target_throw_events": len(throws), "junit_exit": manifest["returncode"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "requested_faults": len(sequence), "matched_faults": len(matched),
            "applied_faults": len(applied)}


def main() -> None:
    result = {}
    for name, path in CAMPAIGNS.items():
        state = json.loads(path.read_text())
        trials = [audit_trial(trial) for trial in state["completed"]]
        result[name] = {"completed": len(trials),
                        "budget": state["budget"],
                        "strict": sum(row["exact"] for row in trials),
                        "target_retaining": sum(row["exact"] and row["target_after_fault"]
                                                for row in trials),
                        "rotated_key_target_retaining": sum(
                            row["exact"] and row["rotated_key_after_fault"]
                            for row in trials),
                        "target_throw_events": sum(row["target_throw_events"] for row in trials),
                        "junit_pass": sum(row["junit_exit"] == 0 for row in trials),
                        "elapsed_seconds": round(state["healthy_seconds"] +
                                                 sum(row["elapsed_seconds"] for row in trials), 3),
                        "trials": trials}
    temporary = OUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(OUT)
    print({name: {key: value for key, value in data.items() if key != "trials"}
           for name, data in result.items()})


if __name__ == "__main__":
    main()
