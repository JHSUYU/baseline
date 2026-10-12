#!/usr/bin/env python3
"""Run one fresh, actor-bound SOLR-31 low-level retry fault trial."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from build_plan import SITE, plan_from_receipt


ROOT = Path("/users/ZhenyuLi/baseline")
CASE = ROOT / "Mallory/adapters/solr/cases/SOLR-31"
AGENT = ROOT / ("Mallory/instrumentation/releases/"
                "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
                "mallory-agent.jar")
NORMAL = ROOT / "Mallory/adapters/solr/target/mallory-solr-adapter-v46.jar"
ADDON = CASE / "retry-faithful-v48/target/mallory-solr31-retry-attempt.jar"
PILOT = ROOT / "Mallory/adapters/solr/releases/v46/run_pilot.py"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/solr-lane3")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def log_fields(line: str) -> dict:
    return dict(part.split("=", 1) for part in line.split() if "=" in part)


def run(mode: str, healthy: Path, out: Path) -> dict:
    if out.exists():
        raise ValueError("diagnostic output must be fresh")
    receipt = json.loads(healthy.read_text())
    plan = plan_from_receipt(receipt, mode)
    config = json.loads((CASE / "retry-faithful-v48/config-v48-healthy-node2.json").read_text())
    pinned = next(row["sha256"] for row in config["runtime_artifacts"]
                  if row["path"] == str(ADDON))
    if not all(path.is_file() for path in (AGENT, NORMAL, ADDON, PILOT)) \
            or sha(ADDON) != pinned or not SOURCE.is_dir():
        raise ValueError("pinned runtime artifact or source missing")

    out.mkdir(parents=True)
    (out / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    config_rows = {
        "events": out / "events.jsonl", "site.catalog": out / "sites.jsonl",
        "run.id": "SOLR-31-v48-" + mode,
        "fault.plan": out / "plan.json",
        "site.file": CASE / "sites-v46-state-watch.json",
        "include": ",".join(config["agent_include"]),
        "adapter.jars": str(NORMAL) + "," + str(ADDON),
        "adapter.transformers": (
            "edu.uva.liftlab.mallory.solr.SolrTransformer,"
            "edu.uva.liftlab.mallory.solr31.RetryAttemptTransformer"),
        "auto.io.doors": "false", "coverage.methods": "true",
        "coverage.branches": "true", "state.fields": "false", "state.maps": "false",
    }
    props = out / "agent.properties"
    props.write_text("".join(f"{key}={value}\n" for key, value in config_rows.items()))
    env = os.environ.copy()
    env.update({
        "MALLORY_EVENT_FILE": str(out / "events.jsonl"),
        "MALLORY_PLAN_FILE": str(out / "plan.json"),
        "MALLORY_SITE_CATALOG": str(out / "sites.jsonl"),
        "MALLORY_SITE_FILE": str(CASE / "sites-v46-state-watch.json"),
        "MALLORY_RUN_ID": "SOLR-31-v48-" + mode,
        "MALLORY_SOLR_AGENT_JAR": str(AGENT),
        "MALLORY_SOLR_ADAPTER_JAR": str(NORMAL),
        "MALLORY_SOLR_NIGHTLY": "1",
        "MALLORY_SOLR31_RETRY_ACTOR": plan["selection"]["node"],
        "MALLORY_SOLR31_RETRY_EPOCH": str(plan["selection"]["epoch"]),
        "MALLORY_SOLR31_RETRY_READ_ORDINAL": str(plan["selection"]["watch_read_ordinal"]),
        "JAVA_TOOL_OPTIONS": "-javaagent:" + str(AGENT) + "=config=" + str(props),
    })
    command = ["python3", str(PILOT), "SOLR-31", "--source", str(SOURCE),
               "--output", str(out), "--campaign", "--timeout", "420"]
    started = time.time()
    try:
        with (out / "stdout.log").open("w") as stdout, (out / "stderr.log").open("w") as stderr:
            proc = subprocess.run(command, cwd=SOURCE, env=env, stdout=stdout,
                                  stderr=stderr, timeout=480, check=False)
            return_code = proc.returncode
    except subprocess.TimeoutExpired:
        return_code = 124
    pilot_file = out / "pilot-result.json"
    pilot = json.loads(pilot_file.read_text()) if pilot_file.is_file() else {}
    log_file = out / "junit.log"
    log = log_file.read_text(errors="replace") if log_file.is_file() else ""
    attempts = [log_fields(line) for line in log.splitlines()
                if "MALLORY_SOLR31_RETRY phase=attempt" in line
                and "node=" + plan["selection"]["node"] in line
                and "read_ordinal=" + str(plan["selection"]["watch_read_ordinal"]) in line]
    successes = [log_fields(line) for line in log.splitlines()
                 if "MALLORY_SOLR31_RETRY phase=success" in line
                 and "node=" + plan["selection"]["node"] in line
                 and "read_ordinal=" + str(plan["selection"]["watch_read_ordinal"]) in line]
    applied = []
    event_file = out / "events.jsonl"
    if event_file.is_file():
        for line in event_file.open():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "FAULT_APPLIED" and row.get("site") == SITE:
                applied.append(row.get("fault_id"))
    expected = [row["fault_id"] for row in plan["faults"]]
    stable = bool(attempts) and len({(row.get("reader_id"), row.get("client_id"),
                                     row.get("keeper_id"), row.get("session_id"),
                                     row.get("occurrence")) for row in attempts}) == 1 \
        and all(row.get("stable_session") == "true" for row in attempts)
    targets = [log_fields(line) for line in log.splitlines()
               if "MALLORY_SOLR31_STATE phase=target" in line]
    same_reader_target = any(row.get("node") == attempts[0]["node"]
                             and row.get("epoch") == attempts[0]["epoch"]
                             and row.get("reader_id") == attempts[0]["reader_id"]
                             for row in targets) if attempts else False
    matched = (applied == expected and stable and same_reader_target
               and log.count("MALLORY_SOLR31_RETRY_WEAVE status=ok matches=1") == 1)
    if mode == "transient":
        matched = matched and len(attempts) >= 2 and len(successes) == 1 \
            and successes[0].get("attempt") == "2"
    else:
        matched = matched and len(attempts) == len(expected) and not successes
    result = {
        "schema_version": 1, "mode": mode, "status": "matched" if matched else "unmatched",
        "elapsed_seconds": round(time.time() - started, 3), "return_code": return_code,
        "healthy_receipt_sha256": sha(healthy), "plan_sha256": sha(out / "plan.json"),
        "addon_sha256": sha(ADDON), "expected_fault_ids": expected,
        "applied_fault_ids": applied, "attempts": attempts, "successes": successes,
        "same_reader_target": same_reader_target, "target_operands": targets,
        "pilot_status": pilot.get("status"),
        "pilot_target_checks": pilot.get("target_check_count"),
        "pilot_target_throws": pilot.get("target_throw_count"),
    }
    (out / "diagnostic-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("transient", "exhaust"), required=True)
    parser.add_argument("--healthy-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    lock_file = Path("/users/ZhenyuLi/.mallory-worktrees/solr31-v48-node2.lock")
    with lock_file.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = run(args.mode, args.healthy_receipt.resolve(), args.out.resolve())
    print(json.dumps({key: result[key] for key in
                      ("mode", "status", "elapsed_seconds", "return_code",
                       "applied_fault_ids", "same_reader_target", "pilot_target_throws")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
