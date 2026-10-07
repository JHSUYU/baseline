#!/usr/bin/env python3
"""Independently audit the five no-F0 alias-read-only controls from raw files."""

import hashlib
import json
from pathlib import Path
import argparse


CASE = Path(__file__).resolve().parents[1]
ROOT = CASE / "evidence/alias-read-only-v12b"
STATE = CASE / "evidence/campaign-v4/state.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        rows.append({"seq": int(parts[0]), "ns": int(parts[1]),
                     "kind": parts[2], "parts": parts[3:],
                     "fields": dict(part.split("=", 1) for part in parts[3:] if "=" in part)})
    return rows


def actor(event: dict) -> tuple[str, ...]:
    return tuple(event["fields"].get(key, "") for key in
                 ("actor", "node", "client_id", "manager_id"))


def main() -> None:
    frozen = sha(STATE)
    build = json.loads((ROOT / "build-receipt.json").read_text())
    if (build["frozen_campaign_state_sha256"] != frozen or not build["no_plan_fault"] or
            build["alias_only_route_class_sha256"] != build["original_route_class_sha256"] or
            build["alias_only_junit_class_sha256"] != build["original_junit_class_sha256"]):
        raise RuntimeError("Frozen or original-class build gate failed")
    summary = json.loads((ROOT / "summary.json").read_text())
    rows = []
    for receipt in summary["runs"]:
        trial = ROOT / f"trial-{receipt['number']:03d}"
        manifest = json.loads((trial / "manifest.json").read_text())
        raw = trace(trial / "events.tsv")
        for key, filename in (("events_sha256", "events.tsv"),
                              ("junit_log_sha256", "junit.log"),
                              ("jacoco_sha256", "jacoco.exec")):
            if sha(trial / filename) != receipt[key]:
                raise RuntimeError(f"{trial.name} {filename} SHA mismatch")
        if not (trial / "jacoco.exec").stat().st_size:
            raise RuntimeError(f"{trial.name} empty coverage")
        if (manifest["faults"] or manifest["exit_code"] != receipt["junit_exit"] or
                manifest["original_test_class_sha256"] != build["original_junit_class_sha256"] or
                receipt["frozen_campaign_state_sha256"] != frozen or
                receipt["build_receipt_sha256"] != sha(ROOT / "build-receipt.json")):
            raise RuntimeError(f"{trial.name} manifest/build gate mismatch")
        plan_faults = [event for event in raw if event["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        faults = [event for event in raw if event["kind"] == "IO_UNDERLYING_CONNECTION_LOSS"]
        successes = [event for event in raw if event["kind"] == "IO_UNDERLYING_RETRY_SUCCESS"]
        if (plan_faults or len(faults) != 1 or faults[0]["parts"][:2] !=
                ["GET_DATA", "/aliases.json"] or faults[0]["fields"].get("actor") != "jetty:node2" or
                len(successes) > 1 or (successes and actor(successes[0]) != actor(faults[0]))):
            raise RuntimeError(f"{trial.name} fault identity mismatch")
        targets = [event for event in raw if event["kind"] == "TARGET_CHECK" and
                   len(event["parts"]) > 1 and event["parts"][1] == "SOLR-40" and
                   event["seq"] > faults[0]["seq"] and actor(event) == actor(faults[0])]
        throws = [event for event in raw if event["kind"] == "TARGET_EXCEPTION" and
                  event["parts"] and event["parts"][0] == "SOLR-40" and
                  event["seq"] > faults[0]["seq"] and actor(event) == actor(faults[0])]
        if (len(targets) != receipt["same_reader_target_count"] or
                [event["parts"][0] for event in targets] != receipt["same_reader_target_values"] or
                len(throws) != receipt["same_reader_throw_count"] or
                len(successes) != receipt["retry_success_count"]):
            raise RuntimeError(f"{trial.name} target recount mismatch")
        rows.append({"number": receipt["number"], "underlying_actor": actor(faults[0]),
                     "retry_success": len(successes),
                     "target_values": [event["parts"][0] for event in targets],
                     "target_exceptions": len(throws), "junit_exit": manifest["exit_code"],
                     "first_fault_to_target_ms": round((targets[0]["ns"] - faults[0]["ns"]) / 1e6, 3)
                        if targets else None})
    output = {"frozen_campaign_state_sha256": frozen,
              "build_receipt_sha256": sha(ROOT / "build-receipt.json"),
              "summary_sha256": sha(ROOT / "summary.json"),
              "raw_trial_count": len(rows), "runs": rows}
    path = ROOT / "control-audit.json"
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"audit": str(path), "sha256": sha(path), "runs": len(rows)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    if args.replay:
        ROOT = CASE / "evidence/alias-read-only-v12b-replay"
    main()
