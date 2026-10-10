#!/usr/bin/env python3
"""Run one pinned ZK04 campaign on node1, with a worker-held lock and disk journal."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


BASE = Path("/users/ZhenyuLi/baseline")
ROOT = BASE / "Mallory/adapters/zookeeper"
RECEIPT = ROOT / "cases/ZOOKEEPER-04-fa5f-readbool-node1-full-v1.staging.json"
OUTPUT = BASE / "data/mallory/campaigns/ZOOKEEPER-04-readbool-node1-v1"
LOCK = Path("/tmp/mallory-lanes/zookeeper-node1-source.lock")
FLOOR = 5 * 1024**3
PEAK_RESERVE = 2 * 300 * 1024**2
EMERGENCY_HEADROOM = 150 * 1024**2


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def append(event: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "resource-journal.jsonl"
    row = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def free_bytes() -> int:
    return os.statvfs(BASE).f_bavail * os.statvfs(BASE).f_frsize


def verify_files(receipt: dict) -> None:
    if receipt.get("case_id") != "ZOOKEEPER-04" or receipt.get("schema_version") != 1:
        raise ValueError("wrong staging receipt")
    for row in receipt["pins"]:
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"pinned input changed: {path}")
    config = Path(receipt["config"])
    subprocess.run([sys.executable, str(ROOT / "verify_lane2_campaign.py"),
                    str(config)], cwd=BASE, check=True)
    core = Path(receipt["core_release"])
    subprocess.run([sys.executable, str(BASE / "Mallory/dispatch/core_release.py"),
                    "--verify", str(core / "manifest.json")], cwd=BASE, check=True)
    if receipt["output"] != str(OUTPUT):
        raise ValueError("output path differs from staging receipt")


def trial_hashes() -> list[dict]:
    rows = []
    for path in sorted((OUTPUT / "trials").glob("r[0-9][0-9][0-9][0-9]/result.json")):
        result = read_json(path)
        evidence = result.get("events_evidence") or {}
        name = evidence.get("gzip_path") or evidence.get("raw_path")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError(f"invalid trace name in {path}")
        trace = path.parent / name
        expected = evidence.get("gzip_sha256") or evidence.get("raw_sha256")
        if not trace.is_file() or sha(trace) != expected:
            raise ValueError(f"trace hash mismatch in {path.parent}")
        rows.append({"trial": path.parent.name, "result_sha256": sha(path),
                     "trace": name, "trace_sha256": expected,
                     "trace_raw_sha256": evidence.get("raw_sha256")})
    return rows


def stop_child(process: subprocess.Popen, reason: str) -> None:
    checkpoint = OUTPUT / "checkpoint.json"
    current = read_json(checkpoint) if checkpoint.is_file() else {}
    running = (current.get("running") or {}).get("pid")
    append({"event": "emergency_stop", "reason": reason,
            "checkpoint_sha256": sha(checkpoint) if checkpoint.is_file() else None,
            "trial_process_group": running})
    if process.poll() is None and os.getpgid(process.pid) == process.pid:
        os.killpg(process.pid, signal.SIGTERM)
    if isinstance(running, int) and running > 0:
        try:
            if os.getpgid(running) == running:
                os.killpg(running, signal.SIGTERM)
        except ProcessLookupError:
            pass


def write_collection(receipt: dict, exit_code: int) -> None:
    tracked = {"staging_receipt": RECEIPT, "config": Path(receipt["config"]),
               "checkpoint": OUTPUT / "checkpoint.json", "result": OUTPUT / "result.json",
               "audit": OUTPUT / "offline-causal-audit.json",
               "journal": OUTPUT / "resource-journal.jsonl",
               "driver_log": OUTPUT / "driver.log"}
    files = {key: {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}
             for key, path in tracked.items() if path.is_file()}
    result = read_json(OUTPUT / "result.json") if (OUTPUT / "result.json").is_file() else {}
    document = {"schema_version": 1, "case_id": "ZOOKEEPER-04",
                "scope": "node1_private_raw_offhost_from_node0_no_node0_import",
                "output": str(OUTPUT), "runner_exit_code": exit_code,
                "campaign_status": result.get("status"),
                "fault_trials_completed": result.get("fault_trials_completed"),
                "free_bytes": free_bytes(), "files": files, "trials": trial_hashes()}
    temporary = OUTPUT / "collection-receipt.json.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(OUTPUT / "collection-receipt.json")


def run(*, resume: bool) -> int:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = read_json(RECEIPT)
        verify_files(receipt)
        if resume:
            if not (OUTPUT / "checkpoint.json").is_file() or (OUTPUT / "result.json").is_file():
                raise ValueError("resume requires a nonterminal checkpoint")
            if sha(OUTPUT / "config.json") != receipt["config_sha256"]:
                raise ValueError("resume config digest changed")
            trial_hashes()
        elif OUTPUT.exists():
            raise FileExistsError(f"fresh output must be absent: {OUTPUT}")
        if free_bytes() < FLOOR + PEAK_RESERVE:
            raise RuntimeError("node1 disk reserve gate failed")
        OUTPUT.mkdir(parents=True, exist_ok=True)
        append({"event": "admission", "free_bytes": free_bytes(),
                "required_free_bytes": FLOOR + PEAK_RESERVE,
                "config_sha256": receipt["config_sha256"],
                "staging_receipt_sha256": sha(RECEIPT), "resume": resume})
        core = Path(receipt["core_release"])
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{core}:{BASE}"
        env["MALLORY_CORE_RELEASE_ID"] = core.name
        env["MALLORY_ATTEMPT_ID"] = f"zk04-node1-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        command = [sys.executable, "-m", "Mallory.core.campaign", "--config",
                   receipt["config"], "--out", str(OUTPUT)]
        with (OUTPUT / "driver.log").open("ab") as log:
            process = subprocess.Popen(command, cwd=core, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            append({"event": "campaign_start", "pid": process.pid,
                    "attempt_id": env["MALLORY_ATTEMPT_ID"]})
            last_sample = 0.0
            while process.poll() is None:
                now = time.monotonic()
                free = free_bytes()
                if now - last_sample >= 30:
                    checkpoint = OUTPUT / "checkpoint.json"
                    append({"event": "disk_sample", "free_bytes": free,
                            "checkpoint_sha256": sha(checkpoint) if checkpoint.is_file() else None})
                    last_sample = now
                if free < FLOOR + EMERGENCY_HEADROOM:
                    stop_child(process, f"free bytes {free} below emergency threshold")
                    break
                time.sleep(5)
            code = process.wait()
        append({"event": "campaign_exit", "exit_code": code,
                "free_bytes": free_bytes()})
        result = OUTPUT / "result.json"
        if result.is_file():
            audit_log = OUTPUT / "offline-audit.log"
            with audit_log.open("wb") as stream:
                audit = subprocess.run([sys.executable, "-m", "Mallory.core.audit",
                                        "--campaign", str(OUTPUT), "--out",
                                        str(OUTPUT / "offline-causal-audit.json")],
                                       cwd=core, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT)
            append({"event": "offline_audit", "exit_code": audit.returncode})
        write_collection(receipt, code)
        return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.preflight:
        verify_files(read_json(RECEIPT))
        print(json.dumps({"preflight": "passed", "free_bytes": free_bytes(),
                          "output_exists": OUTPUT.exists()}, sort_keys=True))
    else:
        raise SystemExit(run(resume=args.resume))
