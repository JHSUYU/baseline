"""Conservative three-node launcher for pinned GraphChecker campaigns.

Default mode only prints a plan. Launch requires a reviewed pilot receipt,
explicit case cap, and fresh verification on each worker before tmux starts.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from Mallory.dispatch.graphchecker_port.lane import verify_inputs
from Mallory.dispatch.graphchecker_port.plan import CASE_ID, SYSTEM_WAVES, checkpoint_state, sha256

SESSION = re.compile(r"^mgc-[a-z0-9-]+$")


def selected_for_wave(document: dict, wave: int, limit: int) -> list[dict]:
    if wave not in (0, 1) or limit < 1:
        raise ValueError("wave must be 0 or 1 and case cap must be positive")
    if document.get("schema_version") != 1:
        raise ValueError("unsupported deployment schema")
    expected = {system: host for hosts in SYSTEM_WAVES for host, system in hosts.items()}
    if document.get("assignments") != expected:
        raise ValueError("system assignment differs from reviewed three-node waves")
    state_root = Path(document["state_root"])
    if not state_root.is_absolute() or state_root == Path("/"):
        raise ValueError("state_root must be an absolute dedicated directory")
    configs = document.get("configs")
    if not isinstance(configs, dict) or not configs:
        raise ValueError("deployment must map case IDs to configs")
    if wave == 1:
        hdfs = [case for case in configs if case.startswith("HDFS-")]
        if not hdfs or any(checkpoint_state(case, state_root)[0] != "terminal"
                           for case in hdfs):
            raise ValueError("ZooKeeper wave waits for HDFS terminal checkpoints")
    lanes = []
    for host, system in SYSTEM_WAVES[wave].items():
        case_ids = []
        for case_id in sorted(configs):
            if not case_id.startswith(system.upper() + "-"):
                continue
            if host != "node0":
                case_ids.append(case_id)
                continue
            state, evidence = checkpoint_state(case_id, state_root)
            config_path = Path(document["release_root"]) / configs[case_id]
            if state == "terminal":
                if evidence["checkpoint_config_sha256"] != sha256(config_path):
                    raise ValueError(f"terminal config changed: {case_id}")
                continue
            if state.startswith("blocked_"):
                raise ValueError(f"unrecognized checkpoint for {case_id}: {state}")
            if state == "resumable" and evidence["checkpoint_config_sha256"] != sha256(config_path):
                raise ValueError(f"resume config changed: {case_id}")
            case_ids.append(case_id)
        if case_ids:
            lanes.append({"host": host, "system": system, "case_ids": case_ids,
                          "max_run_cases": min(limit, len(case_ids)),
                          "checkpoint_authority": host})
    return lanes


def _ssh_prefix(host: str, ssh_key: Path) -> list[str]:
    if host == "node0":
        return []
    if host not in ("node1", "node2"):
        raise ValueError("unknown host")
    return ["ssh", "-i", str(ssh_key), "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes", f"ZhenyuLi@{host}"]


def _run(host: str, ssh_key: Path, argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    prefix = _ssh_prefix(host, ssh_key)
    command = prefix + ([shlex.join(argv)] if prefix else argv)
    return subprocess.run(command, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=check)


def _pilot_valid(path: Path, deployment_hash: str) -> bool:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(row, dict) and row.get("schema_version") == 1
            and row.get("passed") is True
            and row.get("deployment_sha256") == deployment_hash
            and isinstance(row.get("case_id"), str)
            and isinstance(row.get("evidence_paths"), list)
            and bool(row["evidence_paths"]))


def _validate_inventory(document: dict) -> None:
    relative = document.get("inventory")
    pinned = document.get("inventory_sha256")
    if not isinstance(relative, str) or relative not in document["release_files"]:
        raise ValueError("deployment must pin the 102-check inventory in release")
    path = Path(document["release_root"]) / relative
    if sha256(path) != pinned or pinned != document["release_files"][relative]:
        raise ValueError("inventory fingerprint mismatch")
    items = json.loads(path.read_text(encoding="utf-8")).get("cases")
    ids = [item.get("case_id") for item in items] if isinstance(items, list) else []
    if len(ids) != 102 or any(not isinstance(case, str) or not CASE_ID.fullmatch(case)
                              for case in ids) or len(ids) != len(set(ids)):
        raise ValueError("inventory is not the exact 102 distinct checks")
    if not set(document["configs"]).issubset(ids):
        raise ValueError("deployment contains a case outside the 102-check inventory")


def _lane_argv(document: dict, deployment: Path, digest: str,
               lane: dict, verify_only: bool) -> list[str]:
    argv = [sys.executable, "-m", "Mallory.dispatch.graphchecker_port.lane",
            "--deployment", str(deployment), "--expected-sha256", digest,
            "--host", lane["host"], "--system", lane["system"]]
    if verify_only:
        argv.append("--verify-only")
    else:
        argv.extend(["--max-run-cases", str(lane["max_run_cases"]),
                     "--case-ids", *lane["case_ids"]])
    return argv


def _command_env(document: dict, argv: list[str]) -> list[str]:
    return ["env", "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONPATH=" + document["release_root"], *argv]


def launch(document: dict, deployment: Path, digest: str,
           lanes: list[dict], ssh_key: Path) -> list[dict]:
    if not ssh_key.is_file():
        raise ValueError("SSH key unavailable")
    _validate_inventory(document)
    # Every lane must pass all input checks before the first job starts.
    for lane in lanes:
        preflight = _command_env(document, _lane_argv(document, deployment,
                                                     digest, lane, True))
        _run(lane["host"], ssh_key, preflight)
        sessions = _run(lane["host"], ssh_key,
                        ["tmux", "list-sessions", "-F", "#S"], check=False)
        if sessions.returncode not in (0, 1):
            raise ValueError(f"tmux unavailable on {lane['host']}: {sessions.stderr}")
        if any(name.startswith("mgc-") for name in sessions.stdout.splitlines()):
            raise ValueError(f"GraphChecker tmux lane already present on {lane['host']}")
    result = []
    for lane in lanes:
        session = f"mgc-{lane['host']}-{lane['system']}-{digest[:10]}"
        if not SESSION.fullmatch(session):
            raise ValueError("unsafe tmux session name")
        worker = _command_env(document, _lane_argv(document, deployment,
                                                   digest, lane, False))
        _run(lane["host"], ssh_key,
             ["tmux", "new-session", "-d", "-s", session, shlex.join(worker)])
        result.append({**lane, "tmux_session": session})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--wave", type=int, choices=(0, 1), default=0)
    parser.add_argument("--max-cases-per-host", type=int, default=1)
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--pilot-receipt", type=Path)
    parser.add_argument("--ssh-key", type=Path,
                        default=Path.home() / ".ssh/id_ed25519_nodes")
    args = parser.parse_args()
    digest = sha256(args.deployment)
    document = json.loads(args.deployment.read_text(encoding="utf-8"))
    lanes = selected_for_wave(document, args.wave, args.max_cases_per_host)
    plan = {"mode": "dry_run", "deployment_sha256": digest,
            "max_concurrent_jobs": 3, "max_jobs_per_host": 1,
            "lanes": lanes}
    if args.launch:
        if args.pilot_receipt is None or not _pilot_valid(args.pilot_receipt, digest):
            raise ValueError("launch requires a reviewed matching pilot receipt")
        plan["mode"] = "launched"
        plan["lanes"] = launch(document, args.deployment, digest, lanes, args.ssh_key)
    else:
        # A local dry run verifies local snapshots if staged. No SSH or write.
        for lane in lanes:
            if lane["host"] == "node0":
                plan["local_verification"] = verify_inputs(document, "node0",
                                                            lane["system"])
    print(json.dumps(plan, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
