"""Collect and audit terminal calibration cases while a host shard runs.

This controller runs on node0 in tmux.  It never edits a remote campaign or
counts a healthy calibration as a completed fault campaign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .archive import TERMINAL
from .collect import materialize_campaign_evidence
from .core_release import verify as verify_core_release
from .worker import atomic_json


CORE_AUDIT_FILES = ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_one(case_dir: Path, release_manifest: Path, release: dict) -> bool:
    result_path = case_dir / "result.json"
    if not result_path.is_file():
        return False
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("case_id") != case_dir.name or result.get("status") not in TERMINAL["calibration"]:
        raise ValueError(f"invalid terminal calibration result: {case_dir}")
    if not result.get("dispatch_provenance") or not result.get("evidence_archive"):
        raise ValueError(f"calibration lacks synced dispatch/evidence receipt: {case_dir}")
    expected_core = {name: release["files"][f"Mallory/core/{name}"]
                     for name in CORE_AUDIT_FILES}
    audit_path = case_dir / "offline-causal-audit.json"
    result_sha = digest(result_path)
    audit = None
    if audit_path.is_file():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if (audit is None or audit.get("campaign_result_sha256") != result_sha
            or audit.get("core_source_sha256") != expected_core):
        env = os.environ.copy()
        repo = Path(__file__).resolve().parents[2]
        archive = result["evidence_archive"]
        data_root = repo / "data/mallory"
        materialize_campaign_evidence(
            case_dir, data_root / archive["path"],
            data_root / archive["manifest_path"])
        env["PYTHONPATH"] = str(release_manifest.parent) + os.pathsep + str(repo)
        run = subprocess.run([sys.executable, "-m", "Mallory.core.audit",
                              "--campaign", str(case_dir), "--out", str(audit_path)],
                             cwd=repo, env=env, capture_output=True, text=True, timeout=900)
        if run.returncode not in (0, 2):
            raise RuntimeError(f"audit failed for {case_dir.name}: {run.stderr[-400:]}")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if (audit.get("case_id") != case_dir.name
            or audit.get("campaign_result_sha256") != result_sha
            or audit.get("core_source_sha256") != expected_core):
        raise ValueError(f"calibration audit does not bind result/release: {case_dir}")
    archive = result["evidence_archive"]
    receipt = {
        "schema_version": 1, "case_id": case_dir.name,
        "status": result["status"], "result_sha256": result_sha,
        "audit_sha256": digest(audit_path),
        "archive_sha256": archive["sha256"],
        "archive_manifest_sha256": archive["manifest_sha256"],
        "core_release_id": release["release_id"],
        "report_gate_passed": audit.get("report_gate_passed") is True,
        "healthy_observed_path_doors": audit.get("healthy_observed_path_doors"),
        "dispatch_attempt_id": result.get("last_dispatch_attempt_id"),
    }
    atomic_json(case_dir / "calibration-receipt.json", receipt)
    return True


def remote_session_running(host: str, session: str, key: Path) -> bool:
    check = subprocess.run(["ssh", "-i", str(key), "-o", "IdentitiesOnly=yes",
                            "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
                            f"ZhenyuLi@{host}", "tmux", "has-session", "-t", session],
                           capture_output=True, text=True, timeout=12)
    if check.returncode not in (0, 1):
        raise RuntimeError(f"remote tmux probe failed: {check.stderr.strip()[:200]}")
    return check.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--host", choices=("node1", "node2"), required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--remote-session", required=True)
    parser.add_argument("--core-release-manifest", type=Path, required=True)
    parser.add_argument("--ssh-key", type=Path,
                        default=Path("/users/ZhenyuLi/.ssh/id_ed25519_nodes"))
    parser.add_argument("--poll-seconds", type=float, default=20)
    parser.add_argument("--post-exit-retries", type=int, default=3)
    args = parser.parse_args(argv)
    if not args.cohort.isalnum() or args.poll_seconds <= 0 or args.post_exit_retries < 1:
        parser.error("invalid cohort or timing")
    repo = Path(__file__).resolve().parents[2]
    release_manifest = args.core_release_manifest.resolve()
    release = verify_core_release(release_manifest)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = [row["case_id"] for row in manifest["cases"]]
    if len(cases) != len(set(cases)):
        raise ValueError("duplicate case in calibration manifest")
    output_root = repo / "data/mallory" / f"calibration_{args.cohort}"
    after_exit = 0
    while True:
        collect = subprocess.run([sys.executable, "-m", "Mallory.dispatch.collect",
                                  "--hosts", args.host, "--cohort", args.cohort],
                                 cwd=repo, capture_output=True, text=True, timeout=1200)
        print(json.dumps({"collector_exit": collect.returncode,
                          "collector_output": (collect.stdout + collect.stderr)[-600:]}), flush=True)
        complete = []
        for case_id in cases:
            case_dir = output_root / case_id
            if case_dir.joinpath("result.json").is_file():
                if audit_one(case_dir, release_manifest, release):
                    complete.append(case_id)
        print(json.dumps({"terminal_audited": len(complete), "total": len(cases),
                          "cases": complete}), flush=True)
        if len(complete) == len(cases):
            return 0
        if remote_session_running(args.host, args.remote_session, args.ssh_key):
            after_exit = 0
        else:
            after_exit += 1
            if after_exit >= args.post_exit_retries:
                print(json.dumps({"incomplete_after_remote_exit": sorted(set(cases) - set(complete))}),
                      flush=True)
                return 2
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
