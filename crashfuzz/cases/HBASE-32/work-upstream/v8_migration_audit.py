#!/usr/bin/env python3
"""Record and verify the supplemental v7 to v8 checkpoint migration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
CHECKPOINT = HERE / "supplemental-checkpoint.json"
PRE = HERE / "evidence-v8-migration-pre.json"
POST = HERE / "evidence-v8-migration-post.json"
CODE_PATH = "crashfuzz/cases/HBASE-32/work-upstream/campaign.py"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_json(value: object) -> str:
    return sha_bytes(json.dumps(value, sort_keys=True,
                                separators=(",", ":")).encode())


def snapshot() -> dict:
    state = json.loads(CHECKPOINT.read_text())
    last = state["trials"][-1]
    old_code = subprocess.check_output(["git", "show", "HEAD:" + CODE_PATH],
                                       cwd=HERE)
    raw = CASE / last["log"]
    receipt = HERE / "logs" / (last["id"] + ".exit")
    jacoco = HERE / "logs" / (last["id"] + ".exec")
    identity = [{key: trial[key] for key in (
        "id", "plan", "exit", "raw_log_sha256", "exec_sha256")}
        for trial in state["trials"]]
    return {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_sha256": sha_bytes(CHECKPOINT.read_bytes()),
        "committed_v7_script_sha256": sha_bytes(old_code),
        "v8_script_sha256": sha_bytes((HERE / "campaign.py").read_bytes()),
        "version": state["version"],
        "attempt_cap": state["attempt_cap"],
        "effective_budget": state["effective_budget"],
        "max_faults": state["max_faults"],
        "attempts": len(state["trials"]),
        "effective": sum(trial["effective"] for trial in state["trials"]),
        "coverage_execs": len(state["coverage_execs"]),
        "coverage_union": state["coverage_union"],
        "io_union_sha256": sha_json(state["io_union"]),
        "io_union_size": len(state["io_union"]),
        "queue_length": len(state["queue"]),
        "queue_sha256": sha_json(state["queue"]),
        "seen_plans_length": len(state["seen_plans"]),
        "seen_plans_sha256": sha_json(state["seen_plans"]),
        "trial_source_identity_sha256": sha_json(identity),
        "last_trial_id": last["id"],
        "last_trial_effective": last["effective"],
        "last_trial_coverage_admitted": last["coverage_admitted"],
        "last_trial_disposition": last["disposition"],
        "last_trial_raw_sha256": sha_bytes(raw.read_bytes()),
        "last_trial_exit_sha256": sha_bytes(receipt.read_bytes()),
        "last_trial_jacoco_sha256": sha_bytes(jacoco.read_bytes()),
        "inflight_exists": (HERE / "supplemental-inflight.json").exists(),
        "active_runner": bool(subprocess.check_output(
            ["pgrep", "-af", str(HERE / "trial_runner.py")], text=True,
            stderr=subprocess.DEVNULL).strip()) if subprocess.run(
                ["pgrep", "-f", str(HERE / "trial_runner.py")],
                capture_output=True).returncode == 0 else False,
    }


def write(path: Path, data: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


def main() -> None:
    mode = sys.argv[1]
    data = snapshot()
    if mode == "pre":
        if data["version"] != 7 or data["attempt_cap"] != 240:
            raise RuntimeError("unexpected v7 source state")
        if data["inflight_exists"] or data["active_runner"]:
            raise RuntimeError("not at a complete JUnit boundary")
        write(PRE, data)
    elif mode == "post":
        before = json.loads(PRE.read_text())
        if data["version"] != 8 or data["attempt_cap"] != 384:
            raise RuntimeError("v8/cap migration absent")
        for key in ("effective_budget", "max_faults", "attempts", "queue_length",
                    "queue_sha256", "seen_plans_length", "seen_plans_sha256",
                    "trial_source_identity_sha256", "last_trial_raw_sha256",
                    "last_trial_exit_sha256", "last_trial_jacoco_sha256"):
            if data[key] != before[key]:
                raise RuntimeError("migration changed immutable " + key)
        if data["effective"] != before["effective"] - 1:
            raise RuntimeError("unreviewed timeout was not excluded")
        if data["coverage_execs"] != before["coverage_execs"] - 1:
            raise RuntimeError("timeout JaCoCo remained in union")
        if data["last_trial_effective"] or data["last_trial_coverage_admitted"]:
            raise RuntimeError("last timeout is still admitted")
        if data["last_trial_disposition"] != "timeout_pending_exact_replay":
            raise RuntimeError("last timeout is not pending review")
        if data["inflight_exists"] or data["active_runner"]:
            raise RuntimeError("migration started a JUnit trial")
        write(POST, data)
    else:
        raise RuntimeError("use pre or post")
    print(json.dumps({"mode": mode, "checkpoint_sha256": data["checkpoint_sha256"],
                      "attempts": data["attempts"], "effective": data["effective"],
                      "attempt_cap": data["attempt_cap"],
                      "queue_length": data["queue_length"]}, sort_keys=True))


if __name__ == "__main__":
    main()
