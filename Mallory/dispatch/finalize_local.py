"""Finalize one node0 terminal campaign with archive, audit, and checklist update."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

try:
    from .archive import TERMINAL, ensure
    from .collect import attempt_provenance, audit_synced_campaign, sha256
    from .core_release import verify as verify_core_release
    from .worker import atomic_json
except ImportError:
    from archive import TERMINAL, ensure
    from collect import attempt_provenance, audit_synced_campaign, sha256
    from core_release import verify as verify_core_release
    from worker import atomic_json


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def terminal_receipt(case_dir: Path, dispatch_dir: Path, case_id: str) -> tuple[dict, dict] | None:
    summary = _read(case_dir / "result.json")
    receipt = _read(dispatch_dir / "result.json")
    if not summary or not receipt:
        return None
    attempt = summary.get("last_dispatch_attempt_id")
    if (summary.get("case_id") != case_id or summary.get("status") not in TERMINAL["campaign"]
            or receipt.get("case_id") != case_id or receipt.get("attempt_id") != attempt
            or receipt.get("scientific_completed") is not True
            or receipt.get("scientific_result_status") != summary.get("status")
            or receipt.get("status") not in ("command_succeeded", "command_failed")
            or not attempt or not (dispatch_dir / "attempts" / attempt / "exit.json").is_file()):
        return None
    return summary, receipt


def finalize(repo: Path, data_root: Path, dispatch_root: Path, case_id: str,
             core_release_manifest: Path) -> bool:
    case_dir = data_root / "cases" / case_id
    match = terminal_receipt(case_dir, dispatch_root / "campaign/cases" / case_id, case_id)
    if not match:
        return False
    summary, receipt = match
    release = verify_core_release(core_release_manifest)
    spec_path = (dispatch_root / "campaign/cases" / case_id / "attempts"
                 / receipt["attempt_id"] / "spec.json")
    provenance = attempt_provenance(spec_path, case_id, receipt["attempt_id"],
                                    receipt["host"], release["release_id"])
    if Path(json.loads(spec_path.read_text(encoding="utf-8"))[
            "core_release_manifest"]).resolve() != core_release_manifest.resolve():
        raise RuntimeError("finalizer release manifest differs from worker specification")
    archive = summary.get("evidence_archive")
    if archive:
        archive_path = data_root / archive["path"]
        manifest_path = data_root / archive["manifest_path"]
        if (sha256(archive_path) != archive["sha256"] or
                sha256(manifest_path) != archive["manifest_sha256"]):
            raise RuntimeError("previous local archive receipt differs")
    else:
        packed = ensure(data_root, "campaign", case_id)
        archive_path = data_root / packed["archive_relative"]
        manifest_path = data_root / packed["manifest_relative"]
        summary["evidence_archive"] = {
            "path": packed["archive_relative"], "sha256": packed["archive_sha256"],
            "manifest_path": packed["manifest_relative"],
            "manifest_sha256": packed["manifest_sha256"], "bytes": packed["archive_bytes"]}
    if summary.get("dispatch_provenance") != provenance:
        summary["dispatch_provenance"] = provenance
    atomic_json(case_dir / "result.json", summary)
    audit_synced_campaign(repo, case_dir, archive_path, manifest_path,
                          core_release_manifest)
    report = subprocess.run([sys.executable, "-m", "Mallory.report.build"], cwd=repo)
    if report.returncode:
        raise RuntimeError("report regeneration failed after local campaign finalization")
    print(json.dumps({"case_id": case_id, "status": summary["status"],
                      "attempt_id": receipt["attempt_id"],
                      "archive_sha256": summary["evidence_archive"]["sha256"],
                      "audit": str(case_dir / "offline-causal-audit.json")},
                     sort_keys=True), flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--data-root", type=Path, default=Path("data/mallory"))
    parser.add_argument("--dispatch-root", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--core-release-manifest", type=Path, required=True)
    parser.add_argument("--watch-seconds", type=float, default=0)
    args = parser.parse_args()
    if args.watch_seconds < 0:
        parser.error("watch interval must be nonnegative")
    repo = args.repo.resolve()
    while True:
        if finalize(repo, args.data_root.resolve(), args.dispatch_root.resolve(),
                    args.case_id, args.core_release_manifest.resolve()):
            return 0
        if not args.watch_seconds:
            return 1
        time.sleep(args.watch_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
