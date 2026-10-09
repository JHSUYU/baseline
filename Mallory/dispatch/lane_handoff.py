"""Run one audited fault campaign at a time on an isolated host-local JVM lane.

The tmux coordinator is restartable.  Each case still has its own scheduler
lease, worker-held lane flock, atomic checkpoint, archive, and offline audit.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .archive import TERMINAL
from .collect import sha256
from .compact import compact_case
from .core_release import verify as verify_core_release
from .finalize_local import finalize, terminal_receipt
from .scheduler import worker_busy
from .worker import atomic_json


CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def finalized(data_root: Path, case_id: str) -> bool:
    case_dir = data_root / "cases" / case_id
    result_path = case_dir / "result.json"
    result = _read(result_path)
    audit = _read(case_dir / "offline-causal-audit.json")
    archive = (result or {}).get("evidence_archive") or {}
    if (not result or result.get("case_id") != case_id
            or result.get("status") not in TERMINAL["campaign"]
            or not archive or not audit
            or audit.get("campaign_result_sha256") != sha256(result_path)
            or audit.get("case_id") != case_id):
        return False
    archive_path = data_root / archive.get("path", "")
    manifest_path = data_root / archive.get("manifest_path", "")
    return (archive_path.is_file() and manifest_path.is_file()
            and sha256(archive_path) == archive.get("sha256")
            and sha256(manifest_path) == archive.get("manifest_sha256"))


def assignment_for_manifest(manifest: dict, base_owner_path: Path,
                            inventory_path: Path, source_reference: Path,
                            host: str) -> dict[str, str]:
    """Apply a pinned, case-specific host offload without editing original shards."""
    base = _read(base_owner_path)
    if not base or not isinstance(base.get("owner"), dict):
        raise ValueError("original case ownership is unavailable")
    owners = base["owner"].copy()
    revision_path = manifest.get("ownership_revision_path")
    revision_sha = manifest.get("ownership_revision_sha256")
    if not revision_path and not revision_sha:
        return owners
    if not isinstance(revision_path, str) or not isinstance(revision_sha, str):
        raise ValueError("ownership revision path and hash must both be pinned")
    path = Path(revision_path)
    if not path.is_absolute() or not path.is_file() or sha256(path) != revision_sha:
        raise ValueError("ownership revision hash changed or path is unavailable")
    revision = _read(path)
    if (not revision or revision.get("schema_version") != 1
            or revision.get("base_ownership_sha256") != sha256(base_owner_path)
            or revision.get("inventory_sha256") != sha256(inventory_path)
            or revision.get("source_reference_sha256") != sha256(source_reference)
            or not isinstance(revision.get("overrides"), list)
            or not revision["overrides"]):
        raise ValueError("ownership revision is not bound to the pinned sources")
    manifest_ids = {row.get("case_id") for row in manifest.get("cases", [])}
    seen = set()
    for row in revision["overrides"]:
        if not isinstance(row, dict):
            raise ValueError("invalid ownership revision entry")
        case_id = row.get("case_id")
        if (not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id)
                or case_id in seen or case_id not in manifest_ids
                or row.get("from_host") != owners.get(case_id)
                or row.get("to_host") != host
                or row.get("from_host") == host
                or not isinstance(row.get("reason"), str) or not row["reason"].strip()):
            raise ValueError(f"invalid ownership offload for {case_id}")
        seen.add(case_id)
        owners[case_id] = host
    effective_path = revision.get("effective_ownership_path")
    effective_sha = revision.get("effective_ownership_sha256")
    if not isinstance(effective_path, str) or not isinstance(effective_sha, str):
        raise ValueError("offloaded cases need a pinned collector ownership map")
    effective_file = Path(effective_path)
    effective = _read(effective_file) if effective_file.is_absolute() else None
    if (not effective or sha256(effective_file) != effective_sha
            or effective.get("owner") != owners):
        raise ValueError("collector ownership does not match the admitted offload")
    mapping_path = revision.get("mapping_manifest_path")
    mapping_sha = revision.get("mapping_manifest_sha256")
    mapping_file = Path(mapping_path) if isinstance(mapping_path, str) else Path()
    if (not mapping_file.is_absolute() or not mapping_file.is_file()
            or not isinstance(mapping_sha, str) or sha256(mapping_file) != mapping_sha):
        raise ValueError("offload source and calibration manifest hash changed")
    mapping = _read(mapping_file)
    mapped_cases = {row.get("case_id"): row for row in mapping.get("cases", [])
                    if isinstance(row, dict)} if mapping else {}
    ready_cases_by_id = {row.get("case_id"): row for row in manifest.get("cases", [])
                         if isinstance(row, dict)}
    for case_id in seen:
        mapped = mapped_cases.get(case_id)
        ready = ready_cases_by_id.get(case_id)
        if (not mapped or not ready
                or mapped.get("promoted_sha256") != ready.get("promoted_sha256")
                or mapped.get("healthy_result_sha256") != ready.get("calibration_sha256")
                or mapped.get("healthy_audit_sha256") != ready.get("healthy_audit_sha256")
                or mapped.get("status") != "runtime_attested_healthy_only_full_not_started"):
            raise ValueError(f"offload mapping manifest disagrees with {case_id} admission")
    return owners


def ready_cases(manifest_path: Path, inventory_path: Path, source_reference: Path,
                core_release_id: str, host: str, priority: list[str],
                excluded: set[str], release_core_hashes: dict[str, str]) -> list[dict]:
    manifest = _read(manifest_path)
    inventory = _read(inventory_path)
    reference = _read(source_reference)
    if (not manifest or not inventory or not reference or manifest.get("host") != host
            or manifest.get("schema_version") != 1
            or manifest.get("inventory_sha256") != sha256(inventory_path)
            or manifest.get("source_reference_sha256") != sha256(source_reference)
            or reference.get("inventory_sha256") != sha256(inventory_path)):
        raise ValueError("ready queue, inventory, or source reference changed")
    rows = {row["case_id"]: row for row in inventory["cases"]}
    owner = assignment_for_manifest(manifest,
                                    Path(__file__).with_name("shards") / "ownership.json",
                                    inventory_path, source_reference, host)
    candidates = []
    seen = set()
    for entry in manifest["cases"]:
        case_id = entry.get("case_id")
        if (entry.get("state") != "ready" or case_id in excluded):
            continue
        if (not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id)
                or case_id in seen or case_id not in rows
                or owner.get(case_id) != host
                or entry.get("core_release_id") != core_release_id):
            raise ValueError(f"ready entry has invalid owner or release: {case_id}")
        seen.add(case_id)
        config_path = Path(entry["promoted_config"]).resolve()
        if not config_path.is_file() or sha256(config_path) != entry.get("promoted_sha256"):
            raise ValueError(f"promoted config hash changed: {case_id}")
        config = _read(config_path)
        if (not config or config.get("case_id") != case_id
                or config.get("system") != rows[case_id]["system"]
                or config.get("mapping", {}).get("status") != "runtime_attested"
                or config.get("calibration_only") is not False):
            raise ValueError(f"promoted config is not campaign ready: {case_id}")
        budget = config.get("budget", {})
        if (not isinstance(budget, dict) or not 0 < budget.get("trials", 0) <= 80
                or not 0 < budget.get("seconds", 0) <= 3600):
            raise ValueError(f"fault budget exceeds per-case limit: {case_id}")
        audit_receipt = config.get("calibration_attestation", {}).get("healthy_causal_audit", {})
        audit_path = Path(audit_receipt.get("path", ""))
        if (not audit_path.is_file() or sha256(audit_path) != audit_receipt.get("sha256")):
            raise ValueError(f"healthy causal audit hash changed: {case_id}")
        audit = _read(audit_path)
        calibration_result = audit_path.parent / "result.json"
        if (not calibration_result.is_file()
                or sha256(calibration_result) != entry.get("calibration_sha256")):
            raise ValueError(f"healthy calibration result hash changed: {case_id}")
        expected_core = {name: release_core_hashes[f"Mallory/core/{name}"]
                         for name in ("audit.py", "events.py", "graph.py",
                                      "feedback.py", "campaign.py")}
        if (not audit or audit.get("case_id") != case_id
                or audit.get("campaign_result_sha256") != entry["calibration_sha256"]
                or audit.get("report_gate_passed") is not True
                or audit.get("healthy_closure_proven") is not True
                or not isinstance(audit.get("healthy_observed_path_doors"), int)
                or isinstance(audit.get("healthy_observed_path_doors"), bool)
                or audit["healthy_observed_path_doors"] <= 0
                or audit.get("core_source_sha256") != expected_core):
            raise ValueError(f"healthy causal audit is not promotable: {case_id}")
        candidates.append({**entry, "config_path": config_path,
                           "system": rows[case_id]["system"]})
    ranks = {case_id: i for i, case_id in enumerate(priority)}
    return sorted(candidates, key=lambda row: (ranks.get(row["case_id"], len(ranks)),
                                               row["case_id"]))


def one_case_command(*, repo: Path, state_root: Path, data_root: Path,
                     case_id: str, system: str, config_path: Path,
                     inventory: Path, source_reference: Path, hosts_file: Path,
                     release_manifest: Path, lane_id: str,
                     case_estimate_gib: float = 4) -> list[str]:
    manifest_path = state_root / "handoff" / f"{case_id}.json"
    pinned = {"schema_version": 1, "cases": [{"case_id": case_id, "system": system}]}
    if manifest_path.is_file() and _read(manifest_path) != pinned:
        raise ValueError(f"one-case manifest changed: {case_id}")
    atomic_json(manifest_path, pinned)
    return [sys.executable, str(repo / "Mallory/dispatch/scheduler.py"),
            "--manifest", str(manifest_path), "--hosts-file", str(hosts_file),
            "--inventory", str(inventory), "--case-config-template", str(config_path),
            "--source-reference", str(source_reference), "--phase", "campaign",
            "--state-root", str(state_root),
            "--scratch-root", str(Path("/tmp/mallory-scratch") / state_root.name),
            "--build-root", str(Path("/tmp/mallory-build") / state_root.name),
            "--max-parallel", "1", "--lane-id", lane_id,
            "--core-release-manifest", str(release_manifest),
            "--remote-case-gib", str(case_estimate_gib)]


def _command_env(repo: Path, release_manifest: Path) -> dict:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = (str(release_manifest.parent) + os.pathsep + str(repo)
                                 + (os.pathsep + environment["PYTHONPATH"]
                                    if environment.get("PYTHONPATH") else ""))
    return environment


def run_one(*, repo: Path, data_root: Path, state_root: Path,
            case: dict, inventory: Path, source_reference: Path,
            hosts_file: Path, release_manifest: Path, lane_id: str,
            retain_expanded_scratch: bool = False,
            case_estimate_gib: float = 4) -> None:
    case_id = case["case_id"]
    dispatch = state_root / "campaign/cases" / case_id
    case_dir = data_root / "cases" / case_id
    if finalized(data_root, case_id):
        if not retain_expanded_scratch:
            compact_case(data_root, case_id)
        return
    command = one_case_command(repo=repo, state_root=state_root, data_root=data_root,
                               case_id=case_id, system=case["system"],
                               config_path=case["config_path"], inventory=inventory,
                               source_reference=source_reference, hosts_file=hosts_file,
                               release_manifest=release_manifest, lane_id=lane_id,
                               case_estimate_gib=case_estimate_gib)
    environment = _command_env(repo, release_manifest)
    if not terminal_receipt(case_dir, dispatch, case_id):
        validation = subprocess.run([*command, "--validate-only"], cwd=repo,
                                    env=environment, capture_output=True, text=True,
                                    timeout=180)
        records = []
        for line in validation.stdout.splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        pending = next((row.get("pending") for row in records if "pending" in row), None)
        active = worker_busy(dispatch) if dispatch.is_dir() else False
        if validation.returncode or (pending != 1 and not active):
            raise RuntimeError(f"{case_id}: preflight did not admit one case: "
                               f"{validation.stderr.strip()[:240]} {records[-3:]}")
        while not terminal_receipt(case_dir, dispatch, case_id):
            completed = subprocess.run(command, cwd=repo, env=environment,
                                       stdout=sys.stdout, stderr=sys.stderr)
            if completed.returncode:
                raise RuntimeError(f"{case_id}: scheduler exited {completed.returncode}")
            if terminal_receipt(case_dir, dispatch, case_id):
                break
            if not dispatch.is_dir() or not worker_busy(dispatch):
                raise RuntimeError(f"{case_id}: scheduler ended without active worker or terminal result")
            time.sleep(10)
    if not terminal_receipt(case_dir, dispatch, case_id):
        raise RuntimeError(f"{case_id}: no terminal scientific dispatch receipt")
    if not finalize(repo, data_root, state_root, case_id, release_manifest):
        raise RuntimeError(f"{case_id}: terminal result could not be finalized")
    if not finalized(data_root, case_id):
        raise RuntimeError(f"{case_id}: archive or offline audit receipt is incomplete")
    if not retain_expanded_scratch:
        compaction = compact_case(data_root, case_id)
        print(json.dumps({"case_id": case_id, "scratch_compaction": {
            "removed_files": compaction["removed_files"],
            "reclaimed_bytes": compaction["reclaimed_bytes"]}}), flush=True)


def supervise(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    data_root = args.data_root.resolve()
    state_root = args.state_root.resolve()
    release_manifest = args.core_release_manifest.resolve()
    release = verify_core_release(release_manifest)
    release_id = release["release_id"]
    state_root.mkdir(parents=True, exist_ok=True)
    with (state_root / "handoff.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another lane handoff coordinator is active") from exc
        while True:
            waiting_session = False
            for session in args.wait_for_tmux_exit:
                check = subprocess.run(["tmux", "has-session", "-t", session],
                                       capture_output=True, text=True, timeout=10)
                if check.returncode not in (0, 1):
                    raise RuntimeError(f"tmux status unavailable for {session}")
                if check.returncode == 0:
                    print(json.dumps({"lane": args.lane_id,
                                      "waiting_for_tmux_exit": session}), flush=True)
                    waiting_session = True
                    break
            if waiting_session:
                if args.dry_run:
                    return 0
                time.sleep(args.poll_seconds)
                continue
            for predecessor in args.wait_for_case:
                if not finalized(data_root, predecessor):
                    print(json.dumps({"lane": args.lane_id, "waiting_for_terminal_audit": predecessor}),
                          flush=True)
                    if args.dry_run:
                        return 0
                    time.sleep(args.poll_seconds)
                    break
            else:
                candidates = ready_cases(args.ready_manifest.resolve(), args.inventory.resolve(),
                                         args.source_reference.resolve(), release_id,
                                         args.host, args.priority, set(args.exclude_case),
                                         release["files"])
                remaining = [entry for entry in candidates
                             if not finalized(data_root, entry["case_id"])]
                if not remaining:
                    print(json.dumps({"lane": args.lane_id, "ready_remaining": 0,
                                      "reason": "no eligible original case in pinned queue"}),
                          flush=True)
                    if args.once or args.dry_run or args.stop_when_empty:
                        return 0
                    time.sleep(args.poll_seconds)
                    continue
                case = remaining[0]
                if shutil.disk_usage(data_root).free < args.min_free_gib * 1024**3:
                    raise RuntimeError("lane disk reserve prevents next campaign")
                print(json.dumps({"lane": args.lane_id, "selected": case["case_id"],
                                  "core_release_id": release_id}), flush=True)
                if args.dry_run:
                    return 0
                run_one(repo=repo, data_root=data_root, state_root=state_root,
                        case=case, inventory=args.inventory.resolve(),
                        source_reference=args.source_reference.resolve(),
                        hosts_file=args.hosts_file.resolve(),
                        release_manifest=release_manifest, lane_id=args.lane_id,
                        retain_expanded_scratch=args.retain_expanded_scratch,
                        case_estimate_gib=getattr(args, "case_estimate_gib", 4))
                atomic_json(state_root / "handoff-result.json", {
                    "case_id": case["case_id"], "result_sha256": sha256(
                        data_root / "cases" / case["case_id"] / "result.json"),
                    "offline_audit_sha256": sha256(data_root / "cases" /
                                                    case["case_id"] / "offline-causal-audit.json"),
                    "finished_at": time.time(), "core_release_id": release_id})
                if args.once:
                    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--data-root", type=Path, default=Path("data/mallory"))
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--host", choices=("node0", "node1", "node2"), required=True)
    parser.add_argument("--lane-id", required=True)
    parser.add_argument("--hosts-file", type=Path, required=True)
    parser.add_argument("--ready-manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, default=Path("Mallory/cases/inventory.json"))
    parser.add_argument("--source-reference", type=Path,
                        default=Path("Mallory/dispatch/source_reference.json"))
    parser.add_argument("--core-release-manifest", type=Path, required=True)
    parser.add_argument("--wait-for-case", action="append", default=[])
    parser.add_argument("--wait-for-tmux-exit", action="append", default=[])
    parser.add_argument("--exclude-case", action="append", default=[])
    parser.add_argument("--priority", action="append", default=[])
    parser.add_argument("--min-free-gib", type=float, default=5)
    parser.add_argument("--case-estimate-gib", type=float, default=4,
                        help="additional disk admission estimate for one case")
    parser.add_argument("--retain-expanded-scratch", action="store_true",
                        help="keep duplicate trial scratch files beside the verified archive")
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--stop-when-empty", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if (not CASE_ID.fullmatch(args.lane_id) or args.poll_seconds <= 0
            or args.min_free_gib < 0 or args.case_estimate_gib <= 0
            or any(not CASE_ID.fullmatch(case)
                                           for case in (args.wait_for_case + args.exclude_case
                                                        + args.priority + args.wait_for_tmux_exit))):
        parser.error("invalid lane, timing, or case ID")
    return supervise(args)


if __name__ == "__main__":
    raise SystemExit(main())
