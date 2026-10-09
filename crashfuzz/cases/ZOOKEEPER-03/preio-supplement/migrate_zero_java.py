#!/usr/bin/env python3
"""Preserve a prelaunch gate failure and resume the unchanged ZK03 plan."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import time

from campaign import ROOT, ASSETS, atomic_json, own_java_alive, verify_assets


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if not socket.gethostname().startswith("node1"):
        raise RuntimeError("migration belongs to the node1 isolated campaign")
    checkpoint = ROOT / "supplement-checkpoint.json"
    old_bytes = checkpoint.read_bytes()
    state = json.loads(old_bytes)
    if state["status"] != "running" or len(state["results"]) != 5 or \
            len(state["pending_ids"]) != 58 or \
            state["pending_ids"][0] != "supplement-006" or \
            state["inflight"] != {"run_id": "supplement-006",
                                  "supplement_id": "supplement-006"} or \
            state["next_trial"] != 7 or state["legacy_attempts"] != 480 or \
            state["legacy_effective"] != 37:
        raise RuntimeError("unexpected checkpoint; refusing migration")
    dest = ROOT / "supplement-006"
    if own_java_alive(dest) or any((dest / name).exists() for name in
                                   ("launch.json", "run.json", "events.tsv",
                                    "coverage.tsv")):
        raise RuntimeError("trial #6 may have launched; refusing migration")
    if (dest / "junit.log").is_file() and (dest / "junit.log").stat().st_size:
        raise RuntimeError("prelaunch JUnit log is nonempty")
    data, fresh_assets = verify_assets()
    if len(data["jobs"]) != 63:
        raise RuntimeError("fixed 63-plan manifest changed")
    old_assets = dict(state["assets"])
    expected = dict(old_assets)
    expected["asset_manifest_sha256"] = fresh_assets["asset_manifest_sha256"]
    if expected != fresh_assets:
        raise RuntimeError("staged source, agent, runner or classpath changed")
    backup = ROOT / "migrations"
    backup.mkdir(exist_ok=True)
    old_saved = backup / "zero-java-old-checkpoint.json"
    if old_saved.exists() and old_saved.read_bytes() != old_bytes:
        raise RuntimeError("checkpoint backup exists with different bytes")
    old_saved.write_bytes(old_bytes)
    moved = ROOT / "interrupted" / "supplement-006-no-java-preflight"
    moved.parent.mkdir(exist_ok=True)
    if dest.exists():
        if moved.exists():
            raise RuntimeError("prelaunch directory already archived")
        shutil.move(str(dest), str(moved))
    elif not moved.exists():
        raise RuntimeError("missing prelaunch directory and archive")
    state["assets"] = fresh_assets
    state["inflight"] = None
    state["next_trial"] = 6
    state["status"] = "paused_at_trial_boundary"
    event = {"reason": "procps ps exits 1 for zero Java processes",
             "old_checkpoint_sha256": sha(old_bytes),
             "old_asset_manifest_sha256": old_assets["asset_manifest_sha256"],
             "new_asset_manifest_sha256": fresh_assets["asset_manifest_sha256"],
             "selected_unchanged": 5, "pending_unchanged": 58,
             "retry_same_plan": "supplement-006",
             "prelaunch_archive": str(moved),
             "no_trial6_java_or_fault": True, "migrated_wall": time.time()}
    state.setdefault("migrations", []).append(event)
    atomic_json(checkpoint, state)
    new_bytes = checkpoint.read_bytes()
    (backup / "zero-java-new-checkpoint.json").write_bytes(new_bytes)
    event["new_checkpoint_sha256"] = sha(new_bytes)
    atomic_json(backup / "zero-java-migration.json", event)
    print(json.dumps(event, sort_keys=True))


if __name__ == "__main__":
    main()
