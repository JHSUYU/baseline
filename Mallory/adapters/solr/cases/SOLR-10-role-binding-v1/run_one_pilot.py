#!/usr/bin/env python3
"""Execute exactly one admitted SOLR-10 role plan and audit its physical match."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from audit_pilot import audit
from prepare_pilot import events_from
from role_plan import ROLE, SITE
from run_pilot_role_v1 import preflight


HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config-role-v1-healthy-node2.json")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--admission-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    plan_object = json.loads(args.plan.read_text())
    faults = plan_object.get("faults")
    if plan_object.get("schema_version") != 1 or not isinstance(faults, list) or len(faults) != 1:
        raise ValueError("bounded pilot requires exactly one schema-1 fault")
    fault = faults[0]
    point = fault.get("point", {})
    if (set(point) != {"site", "role", "role_ordinal"}
            or point["site"] != SITE or point["role"] != ROLE
            or isinstance(point["role_ordinal"], bool)
            or not isinstance(point["role_ordinal"], int)
            or point["role_ordinal"] <= 0
            or fault.get("fault_type") != "EXCEPTION"
            or fault.get("exception_class") !=
                "org.apache.zookeeper.KeeperException$ConnectionLossException"):
        raise ValueError("pilot plan must name the exact SOLR-10 role door and exception")
    admission = json.loads(args.admission_receipt.read_text())
    if (admission.get("admitted") is not True or admission.get("host") != "node2"
            or admission.get("case_id") != "SOLR-10"
            or admission.get("max_trials") != 1
            or admission.get("config_sha256") != sha(args.config)
            or admission.get("plan_sha256") != sha(args.plan)
            or admission.get("runner_sha256") != sha(Path(__file__))):
        raise ValueError("explicit node2 one-trial admission receipt missing or mismatched")
    preflight(Path(config["cwd"]), Path(config["mapping"]["distribution_root"]))
    args.output.mkdir(parents=True, exist_ok=False)
    trial = args.output / "r0001"
    trial.mkdir()
    (trial / "plan.json").write_text(json.dumps(plan_object, indent=2, sort_keys=True) + "\n")
    properties = {
        "events": str(trial / "events.jsonl"),
        "site.catalog": str(trial / "sites.jsonl"),
        "run.id": "SOLR-10-role-v1-r0001",
        "fault.plan": str(trial / "plan.json"),
        "site.file": config["site_file"],
        "include": ",".join(config["agent_include"]),
    }
    for key, value in config["agent_properties"].items():
        if not isinstance(key, str) or not isinstance(value, (str, bool, int)):
            raise ValueError("invalid agent property")
        properties[key] = str(value).lower() if isinstance(value, bool) else str(value)
    for key, value in properties.items():
        if any(character in key + value for character in "\r\n="):
            raise ValueError("invalid agent property character")
    prop_file = trial / "agent.properties"
    prop_file.write_text("".join(f"{key}={value}\n" for key, value in properties.items()))
    env = os.environ.copy()
    env.update({str(key): str(value) for key, value in config.get("env", {}).items()})
    env.update({"MALLORY_EVENT_FILE": str(trial / "events.jsonl"),
                "MALLORY_PLAN_FILE": str(trial / "plan.json"),
                "MALLORY_SITE_CATALOG": str(trial / "sites.jsonl"),
                "MALLORY_SITE_FILE": config["site_file"],
                "MALLORY_RUN_ID": properties["run.id"]})
    option = f"-javaagent:{config['agent_jar']}=config={prop_file}"
    env["JAVA_TOOL_OPTIONS"] = (env.get("JAVA_TOOL_OPTIONS", "") + " " + option).strip()
    command = [piece.format(trial_dir=trial) for piece in config["command"]]
    started = time.monotonic()
    timed_out = False
    with (trial / "stdout.log").open("wb") as stdout, (trial / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, cwd=config["cwd"], env=env,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            return_code = process.wait(timeout=int(config["budget"]["trial_timeout_seconds"]))
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                return_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                return_code = process.wait()
    pilot_result = trial / "pilot-result.json"
    wrapper = json.loads(pilot_result.read_text()) if pilot_result.is_file() else None
    events = trial / "events.jsonl"
    try:
        strict = audit(plan_object, events_from(events))
    except (OSError, ValueError) as failure:
        strict = {"status": "unmatched_or_unverifiable", "reason": str(failure)}
    receipt = {"case_id": "SOLR-10", "host": "node2", "trial_count": 1,
               "elapsed_seconds": round(time.monotonic() - started, 3),
               "timed_out": timed_out, "return_code": return_code,
               "admission_sha256": sha(args.admission_receipt),
               "config_sha256": sha(args.config), "plan_sha256": sha(args.plan),
               "events_sha256": sha(events) if events.is_file() else None,
               "junit": wrapper.get("junit") if wrapper else None,
               "strict_role_audit": strict}
    (args.output / "role-pilot-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
