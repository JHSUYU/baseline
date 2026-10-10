#!/usr/bin/env python3
"""Node1 worker for bounded natural-race admission and a terminal HBASE-23 campaign."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import time


BASE = Path("/users/ZhenyuLi/baseline")
STAGE = BASE / "Mallory/adapters/hbase/pilot/HBASE-23-natural-race-v1"
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
OUTPUT = BASE / "data/mallory/HBASE-23/campaigns/natural-race-v1"
LOCK = Path("/tmp/mallory-lanes/hbase-lane9-next.lock")
HEALTHY_CONFIG = STAGE / "HBASE-23-healthy.json"
FULL_CONFIG = STAGE / "HBASE-23-full.json"
CONFIG_HASHES = {
    "healthy": "b1e74d95e924bb40e3b442c8d14daeefd904659e30c799da6ed52276b4e05bdf",
    "full": "8c4914b7d68f8d1038bee766c43b51f5ad46f333ab910389d11fec48b7d12bc5",
}
SELECTOR = "org.apache.hadoop.hbase.procedure.TestProcedureManager#testSimpleProcedureManager"
CHECK = "org.apache.hadoop.hbase.procedure.ZKProcedureCoordinator#sendGlobalBarrierReached(Lorg/apache/hadoop/hbase/procedure/Procedure;Ljava/util/List;)V@127:branch:5"
MAX_HEALTHY = 12
MAX_FULL_STARTS = 12
TERMINAL = {"budget_exhausted", "queue_exhausted"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def preflight() -> dict:
    """Check frozen inputs and workload identity without starting a JVM."""
    if not socket.gethostname().startswith("node1"):
        raise RuntimeError("HBASE-23 natural-race worker is pinned to node1")
    import_status = subprocess.run(
        [sys.executable, "-m", "Mallory.dispatch.core_release", "--verify",
         str(RELEASE / "manifest.json")], cwd=BASE, capture_output=True, text=True)
    if import_status.returncode:
        raise RuntimeError(import_status.stdout + import_status.stderr)
    sys.path.insert(0, str(RELEASE))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import validate_config

    verified = {}
    for mode, path in (("healthy", HEALTHY_CONFIG), ("full", FULL_CONFIG)):
        if sha(path) != CONFIG_HASHES[mode]:
            raise RuntimeError(f"config hash mismatch: {path}")
        config = read(path)
        validate_config(config)
        if (config["case_id"] != "HBASE-23" or config["cluster_test"] != SELECTOR
                or config["target"]["check_sites"] != [CHECK]):
            raise RuntimeError(f"workload/target mismatch: {path}")
        budget = config["budget"]
        expected = (1, 720, 1) if mode == "healthy" else (80, 3600, 3)
        actual = (budget["trials"], budget["seconds"], budget["max_faults_per_trial"])
        if actual != expected:
            raise RuntimeError(f"budget mismatch: {path}: {actual}")
        if mode == "healthy" and (not config["calibration_only"] or config["auto_promote_if_healthy"]):
            raise RuntimeError("healthy config must stay calibration only")
        if mode == "full" and (config["calibration_only"] or not config["auto_promote_if_healthy"]):
            raise RuntimeError("full config must run fault trials after its own healthy seed")
        pins = config["runtime_artifacts"] + [config["source_equivalence_receipt"]]
        for pin in pins:
            artifact = Path(pin["path"])
            if sha(artifact) != pin["sha256"]:
                raise RuntimeError(f"artifact hash mismatch: {artifact}")
        source = Path(config["source_equivalent_root"])
        test_source = source / "hbase-server/src/test/java/org/apache/hadoop/hbase/procedure/TestProcedureManager.java"
        if sha(test_source) != config["mapping"]["test_source_sha256"]:
            raise RuntimeError(f"test source hash mismatch: {test_source}")
        verified[mode] = {"config_sha256": CONFIG_HASHES[mode], "artifacts": len(pins),
                          "test_source_sha256": sha(test_source)}
    return {"case_id": "HBASE-23", "host": socket.gethostname(), "selector": SELECTOR,
            "exact_check": CHECK, "core_release": RELEASE.name, "verified": verified,
            "jvm_started": False}


def java_busy() -> bool:
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / "comm").read_text().strip() == "java":
                return True
        except (FileNotFoundError, PermissionError):
            pass
    return False


def qualified_outcome(mode: str, status: str | None, seed_qualified: bool) -> bool:
    if mode == "healthy":
        return seed_qualified and status == "calibration_complete"
    if mode == "full":
        return status in TERMINAL
    raise ValueError(f"unknown campaign mode: {mode}")


def campaign(mode: str, number: int) -> tuple[Path, dict, dict]:
    name = f"healthy-{number:02d}" if mode == "healthy" else f"full-{number:02d}"
    out = OUTPUT / name
    config = HEALTHY_CONFIG if mode == "healthy" else FULL_CONFIG
    # Dispatch owns the host capacity gate. This catches accidental starts while another
    # node1 JVM is already running; the lane lock serializes HBase case controllers.
    summary_path = out / "result.json"
    needs_run = not summary_path.is_file() or read(summary_path).get("status") == "running"
    if needs_run:
        if java_busy():
            raise RuntimeError("node1 has an active JVM; dispatch must wait for capacity")
        out.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-m", "Mallory.core.campaign", "--config", str(config),
                   "--out", str(out)]
        if mode == "healthy":
            command.append("--calibration-only")
        with (out / "worker.log").open("a") as log:
            result = subprocess.run(command, cwd=BASE, env={**os.environ,
                                    "PYTHONPATH": f"{RELEASE}:{BASE}"}, stdout=log,
                                    stderr=subprocess.STDOUT)
        (out / "worker-exit.txt").write_text(f"{result.returncode}\n")
    summary = read(out / "result.json")
    trial = read(out / "trials/r0000/result.json")
    audit_path = out / "offline-causal-audit.json"
    audit_status = "present" if audit_path.is_file() else "missing"
    if audit_status == "missing":
        with (out / "audit.log").open("a") as log:
            audited = subprocess.run(
                [sys.executable, "-m", "Mallory.core.audit", "--campaign", str(out),
                 "--out", str(audit_path)], cwd=BASE,
                env={**os.environ, "PYTHONPATH": f"{RELEASE}:{BASE}"},
                stdout=log, stderr=subprocess.STDOUT)
        (out / "audit-exit.txt").write_text(f"{audited.returncode}\n")
        audit_status = "passed" if audited.returncode == 0 else "failed"
    feedback = trial.get("feedback") or {}
    instances = feedback.get("target_instances") or []
    seed_qualified = (summary.get("healthy_seed_valid") is True
                 and trial.get("junit_validation", {}).get("status") == "passed"
                 and trial.get("site_catalog_validation", {}).get("valid") is True
                 and feedback.get("target_reached") is True
                 and feedback.get("target_threw") is False
                 and len(feedback.get("doors") or []) > 0
                 and bool(instances)
                 and all(str(row.get("node", "")).startswith("zk-coordinator:")
                         for row in instances))
    qualified = qualified_outcome(mode, summary.get("status"), seed_qualified)
    receipt = {"mode": mode, "attempt": number, "path": str(out),
               "result_status": summary.get("status"), "junit_status":
               trial.get("junit_validation", {}).get("status"),
               "campaign_duration_seconds": summary.get("duration_seconds"),
               "fault_trials_completed": summary.get("fault_trials_completed"),
               "exact_check_reached": feedback.get("target_reached") is True,
               "target_nonthrowing": feedback.get("target_threw") is False,
               "target_nodes": sorted({row.get("node") for row in instances if row.get("node")}),
               "observed_doors": len(feedback.get("doors") or []),
               "qualified": qualified, "seed_qualified": seed_qualified,
               "audit_status": audit_status,
               "result_sha256": sha(out / "result.json"),
               "trial_result_sha256": sha(out / "trials/r0000/result.json"),
               "audit_sha256": sha(audit_path) if audit_path.is_file() else None}
    atomic(out / "admission-receipt.json", receipt)
    if mode == "healthy":
        archive_dir = OUTPUT / "archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive = archive_dir / f"{name}.tar.gz"
        if not archive.exists():
            temporary = archive.with_suffix(archive.suffix + ".tmp")
            with tarfile.open(temporary, "w:gz") as bundle:
                for member in sorted(out.rglob("*")):
                    if member.is_file() and member.name != ".campaign.lock":
                        bundle.add(member, arcname=f"{name}/{member.relative_to(out)}")
            temporary.replace(archive)
        receipt["archive_path"] = str(archive)
        receipt["archive_sha256"] = sha(archive)
    return out, summary, receipt


def run() -> None:
    if os.environ.get("MALLORY_NODE1_CAPACITY_GRANTED") != "1":
        raise RuntimeError("dispatch must grant node1 capacity before --run")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verified = preflight()
        OUTPUT.mkdir(parents=True, exist_ok=True)
        start_path = OUTPUT / "worker-start.json"
        if not start_path.exists():
            atomic(start_path, {"started_at_epoch": time.time()})
        started_at = read(start_path)["started_at_epoch"]
        atomic(OUTPUT / "preflight.json", verified)
        admissions = []
        for number in range(1, MAX_HEALTHY + 1):
            _, _, receipt = campaign("healthy", number)
            admissions.append(receipt)
            atomic(OUTPUT / "progress.json", {"phase": "healthy", "attempts": admissions})
            if receipt["qualified"]:
                break
        else:
            atomic(OUTPUT / "terminal-receipt.json", {
                "status": "admission_inconclusive", "full_fault_trials_started": False,
                "total_wall_seconds": round(time.time() - started_at, 3),
                "healthy_attempts": admissions})
            return
        full_attempts = []
        for number in range(1, MAX_FULL_STARTS + 1):
            _, summary, receipt = campaign("full", number)
            full_attempts.append(receipt)
            atomic(OUTPUT / "progress.json", {"phase": "full", "healthy_attempts": admissions,
                                                 "full_attempts": full_attempts})
            if receipt["qualified"]:
                atomic(OUTPUT / "terminal-receipt.json", {
                    "status": "full_campaign_terminal", "full_status": summary["status"],
                    "fault_trials_completed": summary.get("fault_trials_completed"),
                    "total_wall_seconds": round(time.time() - started_at, 3),
                    "healthy_attempts": admissions, "full_attempts": full_attempts})
                return
            if (summary.get("status") != "healthy_seed_invalid"
                    or summary.get("fault_trials_completed") != 0):
                raise RuntimeError(f"full attempt stopped unexpectedly: {summary.get('status')}")
        atomic(OUTPUT / "terminal-receipt.json", {
            "status": "full_startup_inconclusive", "healthy_attempts": admissions,
            "total_wall_seconds": round(time.time() - started_at, 3),
            "full_attempts": full_attempts})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "run"))
    args = parser.parse_args()
    if args.mode == "preflight":
        print(json.dumps(preflight(), indent=2, sort_keys=True))
    else:
        run()
