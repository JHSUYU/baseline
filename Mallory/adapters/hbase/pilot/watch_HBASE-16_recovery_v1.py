"""Collect the isolated HBASE-16 full run after its node1 worker exits.

This watcher runs in a separate node0 tmux session. It never starts or resumes
fault trials, and it retains the remote evidence after collection.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time


REPO = Path("/users/ZhenyuLi/baseline")
KEY = Path("/users/ZhenyuLi/.ssh/id_ed25519_nodes")
HOST = "ZhenyuLi@node1"
CASE = "HBASE-16"
REMOTE = Path("/users/ZhenyuLi/.mallory-worktrees/hbase/lane7/full-HBASE-16-recovery-v1")
STAGING = REPO / "data/mallory/cases/.HBASE-16-recovery-v1-collect"
FINAL = REPO / "data/mallory/cases/HBASE-16"
RELEASE = "5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
TERMINAL = {"budget_exhausted", "queue_exhausted"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ssh(command: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=8", HOST, command],
        capture_output=True, text=True, timeout=timeout,
    )


def remote_status() -> dict | None:
    code = (
        "import json,pathlib; "
        f"r=pathlib.Path({str(REMOTE)!r}); "
        "p=r/'result.json'; e=r/'worker-exit-code.txt'; "
        "print(json.dumps({'result':json.loads(p.read_text()) if p.exists() else None, "
        "'exit':e.read_text().strip() if e.exists() else None}))"
    )
    response = ssh(shlex.join(["python3", "-c", code]))
    if response.returncode:
        print(f"status unavailable: {response.stderr.strip()[:300]}", flush=True)
        return None
    return json.loads(response.stdout)


def audit_remote() -> None:
    audit = REMOTE / "offline-causal-audit.json"
    release_root = REPO / "Mallory/dispatch/releases" / RELEASE
    command = (
        f"PYTHONPATH={shlex.quote(str(release_root) + ':' + str(REPO))} "
        + shlex.join(["python3", "-m", "Mallory.core.audit", "--campaign", str(REMOTE),
                      "--out", str(audit)])
    )
    response = ssh(command, timeout=3600)
    print(f"remote audit exit={response.returncode} {response.stdout.strip()} "
          f"{response.stderr.strip()[:500]}", flush=True)
    if response.returncode not in (0, 2):
        raise RuntimeError("remote frozen-core audit failed to run")


def collect() -> None:
    if FINAL.exists():
        receipt_path = FINAL / "collection-receipt.json"
        if not receipt_path.is_file():
            raise RuntimeError(f"unrecognized canonical result already exists: {FINAL}")
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get("case_id") != CASE
                or receipt.get("result_sha256") != sha256(FINAL / "result.json")
                or receipt.get("audit_sha256") != sha256(FINAL / "offline-causal-audit.json")):
            raise RuntimeError("existing canonical collection receipt is invalid")
        print(f"canonical result already collected: {receipt_path}", flush=True)
        rebuild_report()
        return
    STAGING.mkdir(parents=True, exist_ok=True)
    transport = f"ssh -i {KEY} -o IdentitiesOnly=yes -o BatchMode=yes"
    source = f"{HOST}:{REMOTE}/"
    for argv in (
        ["rsync", "-a", "-e", transport, source, str(STAGING) + "/"],
        ["rsync", "-acn", "--delete", "--exclude=collection-receipt.json",
         "--out-format=%n", "-e", transport,
         source, str(STAGING) + "/"],
    ):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
        if result.returncode or ("-acn" in argv and result.stdout.strip()):
            raise RuntimeError(f"rsync failed or differs: {result.returncode} "
                               f"{result.stdout[:300]} {result.stderr[:300]}")

    summary_path = STAGING / "result.json"
    audit_path = STAGING / "offline-causal-audit.json"
    summary = json.loads(summary_path.read_text())
    audit = json.loads(audit_path.read_text())
    if (summary.get("case_id") != CASE or summary.get("status") not in TERMINAL
            or audit.get("case_id") != CASE
            or audit.get("campaign_result_sha256") != sha256(summary_path)
            or audit.get("terminal_status") != summary["status"]
            or audit.get("archive_integrity_valid") is not True):
        raise RuntimeError("terminal result or audit provenance invalid")
    files = [{"path": str(path.relative_to(STAGING)), "sha256": sha256(path),
              "size_bytes": path.stat().st_size}
             for path in sorted(STAGING.rglob("*")) if path.is_file()]
    receipt = {
        "schema_version": 1,
        "kind": "hbase16_full_remote_collection",
        "case_id": CASE,
        "remote_root": str(REMOTE),
        "local_root": str(FINAL),
        "method": "rsync -a then empty rsync -acn --delete checksum dry-run",
        "core_release_id": RELEASE,
        "result_sha256": sha256(summary_path),
        "audit_sha256": sha256(audit_path),
        "terminal_status": summary["status"],
        "fault_trials_completed": summary["fault_trials_completed"],
        "strict_injected_trials": summary["strict_injected_trials"],
        "strict_target_trials": summary["strict_target_trials"],
        "exact_exception_trials": summary["exact_exception_trials"],
        "audit_report_gate_passed": audit.get("report_gate_passed"),
        "files": files,
    }
    receipt_path = STAGING / "collection-receipt.json"
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if receipt_path.exists() and receipt_path.read_text() != payload:
        raise RuntimeError("partial collection receipt differs from resumed evidence")
    receipt_path.write_text(payload, encoding="utf-8")
    STAGING.rename(FINAL)
    print(f"collected {CASE}: {summary['status']} "
          f"{summary['fault_trials_completed']} trials, "
          f"{summary['strict_injected_trials']} strict injections, "
          f"{summary['strict_target_trials']} target-retained, "
          f"{summary['exact_exception_trials']} exact throws, "
          f"audit={audit.get('report_gate_passed')}, receipt={sha256(FINAL / 'collection-receipt.json')}",
          flush=True)
    rebuild_report()


def rebuild_report() -> None:
    report = subprocess.run([sys.executable, "-m", "Mallory.report.build"],
                            cwd=REPO, capture_output=True, text=True, timeout=120)
    print(f"report exit={report.returncode} {report.stdout.strip()} "
          f"{report.stderr.strip()[:400]}", flush=True)
    if report.returncode:
        raise RuntimeError("collected full result but checklist rebuild failed")


def main() -> int:
    while True:
        state = remote_status()
        if state is None:
            time.sleep(30)
            continue
        summary = state.get("result") or {}
        status = summary.get("status")
        worker_exit = state.get("exit")
        if worker_exit is not None:
            print(f"worker exit={worker_exit} status={status}", flush=True)
            if worker_exit != "0" or status not in TERMINAL:
                raise RuntimeError("worker exited without a terminal scientific result")
            audit_remote()
            collect()
            return 0
        print(f"worker live, status={status}, "
              f"fault_trials={summary.get('fault_trials_completed')}", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
