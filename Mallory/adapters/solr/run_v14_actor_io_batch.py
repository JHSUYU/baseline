#!/usr/bin/env python3
"""Run isolated, calibration-only Solr v14 stable-actor-io seeds on lane1."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


REPO = Path(__file__).resolve().parents[3]
MANIFEST = REPO / "Mallory/adapters/solr/cases/lane1-v14-stable-actor-io-manifest.json"
MANIFEST_SHA = "e372c730c6a4e7bbf808bee91a1d2cc9664c4b142ff59c82da0ce8644ea37f68"
INVENTORY_SHA = "bc1304e3ad206160cbeb1a15bd107278e6b0248e11975048873fdecbb90bd944"
SOURCE_REFERENCE_SHA = "ed226d31e940f20396e55ce94e4f578cbf9f48c440753c43d1e3a6bdefc39391"
CORE_RELEASE = REPO / ("Mallory/dispatch/releases/"
    "5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf")
LANE_LOCK = Path("/tmp/mallory-lanes/solr-lane1.lock")
CASE_IDS = ("SOLR-31", "SOLR-36", "SOLR-37")
OUTPUT = REPO / "data/mallory/calibration_v14_config_lane1"
TERMINAL = {"budget_exhausted", "queue_exhausted", "calibration_complete",
            "healthy_seed_invalid", "healthy_node_identity_missing",
            "healthy_seed_ambiguous", "healthy_no_injectable_door",
            "healthy_attestation_failed", "healthy_no_tests", "healthy_junit_failed",
            "healthy_junit_no_tests", "healthy_junit_process_failed",
            "healthy_junit_report_invalid", "fault_trials_not_attested"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"not a JSON object: {path}")
    return result


def atomic_json(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pending.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pending.replace(path)


def verify_release() -> None:
    manifest = read(CORE_RELEASE / "manifest.json")
    if manifest.get("release_id") != CORE_RELEASE.name:
        raise ValueError("wrong core release ID")
    for relative, expected in manifest.get("files", {}).items():
        if sha256(CORE_RELEASE / relative) != expected:
            raise ValueError(f"core release digest mismatch: {relative}")


def configs(case_ids: tuple[str, ...]) -> dict[str, Path]:
    if sha256(MANIFEST) != MANIFEST_SHA:
        raise ValueError("v14 manifest digest mismatch")
    rows = read(MANIFEST)["cases"]
    selected = {}
    for row in rows:
        if row["case_id"] not in case_ids:
            continue
        path = Path(row["config"])
        if sha256(path) != row["sha256"]:
            raise ValueError(f"config digest mismatch: {path}")
        config = read(path)
        if (config.get("case_id") != row["case_id"]
                or config.get("calibration_only") is not True
                or config.get("auto_promote_if_healthy") is not False
                or config.get("cwd") != "/users/ZhenyuLi/.mallory-worktrees/solr"):
            raise ValueError(f"invalid v14 lane1 calibration config: {path}")
        for artifact in config.get("runtime_artifacts", []):
            if sha256(Path(artifact["path"])) != artifact["sha256"]:
                raise ValueError(f"runtime artifact digest mismatch: {artifact['path']}")
        selected[row["case_id"]] = path
    if set(selected) != set(case_ids):
        raise ValueError("v14 manifest is missing a selected pilot")
    return selected


def verify_source() -> dict:
    sys.path.insert(0, str(REPO))
    from Mallory.dispatch.verify_sources import verify_from_reference
    inventory_path = REPO / "Mallory/adapters/solr/releases/v14/inventory.json"
    reference_path = REPO / "Mallory/adapters/solr/releases/v14/source_reference.json"
    if sha256(inventory_path) != INVENTORY_SHA or sha256(reference_path) != SOURCE_REFERENCE_SHA:
        raise ValueError("inventory or source-reference digest changed after v14 preflight")
    inventory = read(inventory_path)
    reference = read(reference_path)
    if reference.get("inventory_sha256") != INVENTORY_SHA:
        raise ValueError("v14 source reference does not bind its inventory snapshot")
    row = next(row for row in inventory["cases"] if row["case_id"] == "SOLR-31")
    provenance = row["provenance"]
    verdict = verify_from_reference({"name": "node2", "kind": "local"},
        Path.home() / ".ssh/id_ed25519_nodes", Path(provenance["source_root"]),
        provenance["source_commit"], reference,
        Path("/users/ZhenyuLi/.mallory-worktrees/solr"))
    if verdict.get("content_match") is not True:
        raise ValueError("lane1 source differs from pinned clean Solr commit")
    return verdict


def solr05_terminal() -> bool:
    source = Path("/users/ZhenyuLi/.mallory-worktrees/solr-campaign-v4-junit/SOLR-05/result.json")
    if not source.is_file():
        return False
    return read(source).get("status") in TERMINAL


def run_case(case_id: str, config: Path, output: Path) -> dict:
    case_root = output / case_id
    prior = case_root / "result.json"
    if prior.is_file() and isinstance(read(prior).get("status"), str) \
            and read(prior)["status"] != "running":
        return {"case_id": case_id, "status": read(prior)["status"],
                "result_sha256": sha256(prior), "resumed_terminal": True}
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CORE_RELEASE) + os.pathsep + str(REPO)
    env["MALLORY_CORE_RELEASE_ID"] = CORE_RELEASE.name
    command = [sys.executable, "-m", "Mallory.core.campaign",
               "--config", str(config), "--out", str(case_root)]
    started = time.time()
    completed = subprocess.run(command, cwd=REPO, env=env, check=False)
    if not prior.is_file():
        raise RuntimeError(f"{case_id}: core exited {completed.returncode} without result.json")
    result = read(prior)
    if not isinstance(result.get("status"), str) or result["status"] == "running":
        raise RuntimeError(f"{case_id}: nonterminal status after core exit: {result.get('status')}")
    return {"case_id": case_id, "status": result["status"],
            "result_sha256": sha256(prior), "core_exit_code": completed.returncode,
            "elapsed_seconds": round(time.time() - started, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    case_ids, output = CASE_IDS, OUTPUT
    verify_release()
    selected = configs(case_ids)
    if args.dry_run:
        print(json.dumps({"cases": list(case_ids), "manifest_sha256": MANIFEST_SHA,
                    "core_release": CORE_RELEASE.name, "output": str(output)},
                         sort_keys=True))
        return 0
    if not solr05_terminal():
        raise RuntimeError("SOLR-05 lane1 campaign has not terminated")
    LANE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LANE_LOCK.open("a+") as lane:
        try:
            fcntl.flock(lane, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("lane1 lock is held; no v10 JVM was launched") from error
        source_verification = verify_source()
        output.mkdir(parents=True, exist_ok=True)
        progress = {"schema_version": 1, "manifest_sha256": MANIFEST_SHA,
                    "core_release": CORE_RELEASE.name, "lane": "solr-lane1",
                    "cohort": "stable_actor_io", "source_verification": source_verification,
                    "cases": []}
        for case_id in case_ids:
            print(f"MALLORY_SOLR_V14_BEGIN {case_id}", flush=True)
            progress["cases"].append(run_case(case_id, selected[case_id], output))
            atomic_json(output / "batch-progress.json", progress)
            print(f"MALLORY_SOLR_V14_END {case_id} {progress['cases'][-1]['status']}", flush=True)
        progress["finished_at"] = time.time()
        atomic_json(output / "batch-result.json", progress)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
