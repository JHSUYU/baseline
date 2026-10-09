#!/usr/bin/env python3
"""Recount F0-only and delayed-retry SOLR-40 controls from raw artifacts."""

import hashlib
import json
from pathlib import Path
import sys


CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace(path: Path) -> list[dict]:
    result = []
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        result.append({"seq": int(parts[0]), "ns": int(parts[1]),
                       "kind": parts[2], "parts": parts[3:],
                       "fields": dict(part.split("=", 1) for part in parts[3:] if "=" in part)})
    return result


def actor(event: dict) -> tuple[str, ...]:
    fields = event["fields"]
    return tuple(fields.get(key, "") for key in ("actor", "node", "client_id", "manager_id"))


def main() -> None:
    frozen = sha(EVIDENCE / "campaign-v4/state.json")
    originals = json.loads((EVIDENCE / "lowlevel-single-retry-v10/build-receipt.json").read_text())
    if frozen != originals["frozen_campaign_state_sha256"]:
        raise RuntimeError("Terminal campaign checkpoint changed")
    audited = {}
    for name in ("first-fault-only-v10", "delayed-retry-v11b"):
        root = EVIDENCE / name
        summary = json.loads((root / "summary.json").read_text())
        rows = []
        for receipt in summary["runs"]:
            trial = root / f"trial-{receipt['number']:03d}"
            raw = trace(trial / "events.tsv")
            manifest = json.loads((trial / "manifest.json").read_text())
            if receipt["frozen_campaign_state_sha256"] != frozen:
                raise RuntimeError(f"{name}/{trial.name} used another checkpoint")
            for key, filename in (("events_sha256", "events.tsv"),
                                  ("junit_log_sha256", "junit.log"),
                                  ("jacoco_sha256", "jacoco.exec")):
                if sha(trial / filename) != receipt[key]:
                    raise RuntimeError(f"{name}/{trial.name} {filename} digest mismatch")
            if not (trial / "jacoco.exec").stat().st_size:
                raise RuntimeError(f"{name}/{trial.name} empty coverage")
            if manifest["exit_code"] != receipt["junit_exit"]:
                raise RuntimeError(f"{name}/{trial.name} JUnit exit mismatch")
            if manifest["original_test_class_sha256"] != originals["original_junit_class_sha256"]:
                raise RuntimeError(f"{name}/{trial.name} changed original JUnit")
            faults = [event for event in raw if event["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
            underlying = [event for event in raw if event["kind"] == "IO_UNDERLYING_CONNECTION_LOSS"]
            successes = [event for event in raw if event["kind"] == "IO_UNDERLYING_RETRY_SUCCESS"]
            target = [event for event in raw if event["kind"] == "TARGET_CHECK" and
                      len(event["parts"]) > 1 and event["parts"][1] == "SOLR-40"]
            throws = [event for event in raw if event["kind"] == "TARGET_EXCEPTION" and
                      event["parts"] and event["parts"][0] == "SOLR-40"]
            if (len(faults) != 1 or faults[0]["parts"][:2] !=
                    ["EXISTS_WATCH", "/collections/myalias__TRA__2017-10-23/state.json"]):
                raise RuntimeError(f"{name}/{trial.name} F0 identity mismatch")
            if (faults[0]["fields"].get("actor") != "jetty:node1" or
                    faults[0]["fields"].get("physical_actor") != "jetty:node1"):
                raise RuntimeError(f"{name}/{trial.name} F0 physical actor mismatch")
            if name == "first-fault-only-v10":
                if underlying or successes or receipt["alias_underlying_fault_count"]:
                    raise RuntimeError(f"{name}/{trial.name} is not F0-only")
                after = [event for event in target if event["seq"] > faults[0]["seq"] and
                         actor(event) == actor(faults[0])]
                after_throw = [event for event in throws if event["seq"] > faults[0]["seq"] and
                               actor(event) == actor(faults[0])]
                if (len(after) != receipt["same_reader_target_count"] or
                        len(after_throw) != receipt["same_reader_throw_count"] or
                        [event["parts"][0] for event in after] !=
                        receipt["same_reader_target_values"]):
                    raise RuntimeError(f"{name}/{trial.name} target recount mismatch")
                rows.append({"number": receipt["number"], "same_reader_target": len(after),
                             "same_reader_throw": len(after_throw), "junit_exit": manifest["exit_code"]})
            else:
                if (len(underlying) != 1 or actor(underlying[0]) != actor(faults[0]) or
                        underlying[0]["parts"][:2] != ["GET_DATA", "/aliases.json"]):
                    raise RuntimeError(f"{name}/{trial.name} underlying identity mismatch")
                if len(successes) > 1:
                    raise RuntimeError(f"{name}/{trial.name} multiple retry successes")
                if successes and actor(successes[0]) != actor(underlying[0]):
                    raise RuntimeError(f"{name}/{trial.name} retry actor mismatch")
                after = [event for event in target if event["seq"] > underlying[0]["seq"] and
                         actor(event) == actor(underlying[0])]
                after_throw = [event for event in throws if event["seq"] > underlying[0]["seq"] and
                               actor(event) == actor(underlying[0])]
                after_retry = [event for event in after if successes and
                               event["seq"] > successes[0]["seq"]]
                after_retry_throw = [event for event in after_throw if successes and
                                     event["seq"] > successes[0]["seq"]]
                gates = [event for event in raw if event["kind"] == "TARGET_DELAY_GATE"]
                if any(gate["fields"].get("client_id") != actor(underlying[0])[2] or
                       gate["fields"].get("retry_complete") != "true" for gate in gates):
                    raise RuntimeError(f"{name}/{trial.name} delay gate identity or retry mismatch")
                if (len(after) != receipt["same_reader_target_count"] or
                        len(after_throw) != receipt["same_reader_throw_count"] or
                        bool(after_retry) != receipt["target_after_retry_success"] or
                        bool(after_retry_throw) != receipt["throw_after_retry_success"] or
                        len(gates) != len(receipt["delay_gates"])):
                    raise RuntimeError(f"{name}/{trial.name} delayed target recount mismatch")
                rows.append({"number": receipt["number"], "retry_success": len(successes),
                             "same_reader_target": len(after),
                             "after_retry_target": len(after_retry),
                             "after_retry_throw": len(after_retry_throw),
                             "delay_gate": len(gates), "junit_exit": manifest["exit_code"]})
        audited[name] = {"runs": rows, "summary_sha256": sha(root / "summary.json"),
                         "raw_trial_count": len(rows)}
    audited["frozen_campaign_state_sha256"] = frozen
    path = EVIDENCE / "control-audit-v11b.json"
    path.write_text(json.dumps(audited, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"audit": str(path), "sha256": sha(path),
                      "runs": {key: value["raw_trial_count"] for key, value in audited.items()
                               if isinstance(value, dict)}}))


if __name__ == "__main__":
    main()
