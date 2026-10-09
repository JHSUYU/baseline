#!/usr/bin/env python3
"""Publish a completed HDFS campaign only after validating its raw evidence.

The campaign writes to a private staging directory. This watcher can run in a
separate tmux session and survives a disconnected Codex client.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from Mallory.core.feedback import digest


TERMINAL = {"budget_exhausted", "queue_exhausted"}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"not a JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_evidence(trial_dir: Path, entry: dict, label: str) -> str | None:
    raw = entry.get("raw_path")
    compressed = entry.get("gzip_path")
    if not raw and not compressed:
        assert not entry.get("raw_sha256") and not entry.get("gzip_sha256")
        return None
    if raw and compressed:
        raise ValueError(f"{trial_dir}: {label} has two evidence paths")
    if raw:
        path = trial_dir / raw
        expected = entry.get("raw_sha256")
        expected_bytes = entry.get("raw_bytes")
        assert path.is_file() and path.stat().st_size == expected_bytes
        assert sha256(path) == expected, f"{path}: checksum mismatch"
        return expected
    path = trial_dir / compressed
    expected = entry.get("gzip_sha256")
    expected_bytes = entry.get("gzip_bytes")
    assert path.is_file() and path.stat().st_size == expected_bytes
    assert sha256(path) == expected, f"{path}: gzip checksum mismatch"
    h = hashlib.sha256()
    size = 0
    with gzip.open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    assert h.hexdigest() == entry.get("raw_sha256")
    assert size == entry.get("raw_bytes")
    return expected


def validate(stage: Path) -> dict:
    checkpoint = read_json(stage / "checkpoint.json")
    summary = read_json(stage / "result.json")
    config = read_json(stage / "config.json")
    assert checkpoint.get("status") in TERMINAL
    assert summary.get("status") == checkpoint["status"]
    assert checkpoint.get("running") is None
    assert checkpoint.get("case_id") == summary.get("case_id") == config.get("case_id") == "HDFS-01"
    assert checkpoint.get("config_digest") == digest(config)
    assert summary.get("healthy_seed_valid") is True
    assert summary.get("runtime_attestation", {}).get("valid") is True
    ids = checkpoint.get("completed_trials")
    rows = summary.get("trials")
    assert isinstance(ids, list) and ids and 0 in ids
    assert isinstance(rows, list) and {r.get("trial_id") for r in rows} == set(ids)
    assert summary.get("fault_trials_completed") == sum(i > 0 for i in ids)
    assert summary.get("fault_trials_completed") > 0
    verified = []
    for row in rows:
        number = row["trial_id"]
        directory = stage / "trials" / f"r{number:04d}"
        relative = Path(row["result"])
        assert relative == Path("trials") / f"r{number:04d}" / "result.json"
        trial_path = stage / relative
        trial = read_json(trial_path)
        assert trial.get("trial_id") == number and trial.get("case_id") == "HDFS-01"
        catalog = directory / "sites.jsonl"
        if trial.get("site_catalog_sha256"):
            assert catalog.is_file() and sha256(catalog) == trial["site_catalog_sha256"]
        else:
            assert not catalog.is_file(), f"{catalog}: unpinned catalog"
        for label in ("events", "stdout", "stderr"):
            verify_evidence(directory, trial[f"{label}_evidence"], label)
        plan = read_json(directory / "plan.json")
        assert isinstance(plan, dict) and plan.get("faults") == trial.get("plan")
        verified.append({"trial_id": number, "result_sha256": sha256(trial_path),
                         "events_sha256": trial["events_evidence"]["raw_sha256"]})
    return {"schema_version": 1, "case_id": "HDFS-01", "status": summary["status"],
            "result_sha256": sha256(stage / "result.json"),
            "checkpoint_sha256": sha256(stage / "checkpoint.json"),
            "config_sha256": sha256(stage / "config.json"),
            "validated_trials": verified, "validated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def publish(stage: Path, destination: Path, report_root: Path) -> dict:
    lock = os.open(stage / ".campaign.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = validate(stage)
        if destination.exists():
            raise FileExistsError(f"refusing to replace canonical result: {destination}")
        receipt_path = stage / "publish-receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{destination.name}.publishing-{os.getpid()}"
        if temporary.exists():
            raise FileExistsError(temporary)
        shutil.copytree(stage, temporary, ignore=shutil.ignore_patterns(".campaign.lock"))
        assert sha256(temporary / "result.json") == receipt["result_sha256"]
        assert sha256(temporary / "checkpoint.json") == receipt["checkpoint_sha256"]
        assert sha256(temporary / "config.json") == receipt["config_sha256"]
        assert validate(temporary)["result_sha256"] == receipt["result_sha256"]
        os.replace(temporary, destination)
        audit = subprocess.run(
            ["python3", "-m", "Mallory.core.audit", "--campaign", str(destination),
             "--out", str(destination / "offline-causal-audit.json")],
            text=True, capture_output=True)
        # Exit 2 means the archived graph or guidance failed the independent
        # quality audit. The terminal raw campaign is still published as data.
        if audit.returncode not in (0, 2):
            raise RuntimeError(f"offline causal audit failed to execute: {audit.stderr}")
        (destination / "audit-execution.json").write_text(json.dumps({
            "exit_code": audit.returncode, "stdout": audit.stdout,
            "stderr": audit.stderr, "result_sha256": receipt["result_sha256"]},
            sort_keys=True, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["python3", "-m", "Mallory.report.build", "--results", str(report_root)],
                       check=True)
        return receipt
    finally:
        os.close(lock)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, default=Path("data/mallory"))
    parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args()
    while True:
        checkpoint_path = args.stage / "checkpoint.json"
        if checkpoint_path.is_file():
            checkpoint = read_json(checkpoint_path)
            status = checkpoint.get("status")
            if status in TERMINAL:
                try:
                    receipt = publish(args.stage, args.destination, args.report_root)
                except BlockingIOError:
                    time.sleep(args.poll_seconds)
                    continue
                print(json.dumps(receipt, sort_keys=True), flush=True)
                return
            if status != "running":
                raise RuntimeError(f"campaign stopped without a terminal budget: {status}")
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
