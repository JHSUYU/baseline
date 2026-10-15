"""Freeze a bounded native campaign prefix without changing its checkpoint.

The compact snapshot pins accepted trial receipts and verified lossless raw
archives. It is only an input to a separate, fail-closed successor importer.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
from pathlib import Path


SIDECARS = (
    "result.json",
    "iteration-native/fault-events.jsonl",
    "iteration-native/fault-plan.json",
    "local-artifacts.json",
    "native-summary.json",
    "peer-ranking-receipt.json",
    "schedule-lineage.json",
    "native-schedule.jsonl",
)
PIN_KEYS = {
    "iteration-native/fault-events.jsonl": "fault_events_sha256",
    "local-artifacts.json": "local_artifacts_manifest_sha256",
    "native-summary.json": "native_session_sha256",
    "peer-ranking-receipt.json": "peer_ranking_receipt_sha256",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected regular file: {path}")


def freeze(source: Path, config: Path, archives: Path, destination: Path,
           expected_faults: int, dry_run: bool = False) -> dict:
    source, config, archives, destination = (
        p.resolve(strict=True) if p is not destination else p.absolute()
        for p in (source, config, archives, destination)
    )
    if destination.exists():
        raise ValueError(f"snapshot exists: {destination}")
    if destination.parent == source or source in destination.parents:
        raise ValueError("snapshot must be outside live campaign root")
    regular(config)
    if not (source / ".campaign.lock").is_file():
        raise ValueError("missing source campaign lock")
    with (source / ".campaign.lock").open("r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        cp_path, summary_path = source / "checkpoint.json", source / "summary.json"
        regular(cp_path)
        regular(summary_path)
        before = sha256(cp_path)
        cp, summary = json.loads(cp_path.read_text()), json.loads(summary_path.read_text())
        if (cp.get("status") != "bounded_checkpoint_stop" or cp.get("terminal") is not False
                or cp.get("active") is not None or cp.get("completed_fault_trials") != expected_faults
                or cp.get("next_trial_index") != expected_faults + 1):
            raise ValueError("source is not the expected inactive bounded prefix")
        if (summary.get("status") != "bounded_checkpoint_stop"
                or summary.get("completed_fault_trials") != expected_faults
                or summary.get("case_id") != cp.get("case_id")
                or summary.get("config_sha256") != cp.get("config_sha256")):
            raise ValueError("summary does not match bounded checkpoint")
        if cp["config_sha256"] != sha256(config):
            raise ValueError("config hash differs from checkpoint")
        if len(cp.get("trials", [])) != expected_faults:
            raise ValueError("accepted trial count differs from checkpoint")
        if not isinstance(cp.get("queue"), list) or not isinstance(cp.get("seen_plan_keys"), list):
            raise ValueError("queue/seen plan keys missing")

        copied = {"config.json": config, "checkpoint.json": cp_path, "summary.json": summary_path}
        raw_pins = []
        for number in range(expected_faults + 1):
            trial = source / "trials" / f"r{number:04d}"
            result_path = trial / "result.json"
            regular(result_path)
            result = json.loads(result_path.read_text())
            if result.get("case_id") != cp["case_id"]:
                raise ValueError(f"wrong case ID in trial {number}")
            for rel in SIDECARS:
                path = trial / rel
                pin_key = PIN_KEYS.get(rel)
                pinned = pin_key is not None and bool(result.get(pin_key))
                if not path.exists():
                    if pinned or rel == "result.json" or (pin_key is not None and rel != "peer-ranking-receipt.json"):
                        raise ValueError(f"missing pinned sidecar: {path}")
                    continue
                regular(path)
                if pin_key is not None and (not pinned or sha256(path) != result[pin_key]):
                    raise ValueError(f"result sidecar pin mismatch: {path}")
                copied[f"trials/r{number:04d}/{rel}"] = path
            tar = archives / f"raw-r{number:04d}.tar.gz"
            receipt_path = archives / f"raw-r{number:04d}-receipt.json"
            regular(tar)
            regular(receipt_path)
            receipt = json.loads(receipt_path.read_text())
            tar_hash = sha256(tar)
            result_hash = sha256(result_path)
            if (receipt.get("trial_index") != number
                    or receipt.get("verified_against_source") is not True
                    or receipt.get("archive_sha256") != tar_hash
                    or receipt.get("result_sha256") != result_hash):
                raise ValueError(f"raw archive receipt mismatch: {number}")
            raw_pins.append({
                "trial_index": number,
                "absolute_tar_path": str(tar),
                "archive_sha256": tar_hash,
                "absolute_receipt_path": str(receipt_path),
                "receipt_sha256": sha256(receipt_path),
                "result_sha256": result_hash,
            })
        files = {rel: {"sha256": sha256(path), "size_bytes": path.stat().st_size}
                 for rel, path in copied.items()}
        if sha256(cp_path) != before:
            raise ValueError("checkpoint changed during snapshot verification")
        manifest = {
            "schema_version": 1,
            "case_id": cp["case_id"],
            "source_output_root": str(source),
            "source_lock_verified": True,
            "source_checkpoint_before_sha256": before,
            "source_checkpoint_after_sha256": before,
            "config_sha256": files["config.json"]["sha256"],
            "checkpoint_sha256": before,
            "summary_sha256": files["summary.json"]["sha256"],
            "completed_fault_trials": expected_faults,
            "files": files,
            "raw_archives": raw_pins,
        }
        if dry_run:
            return manifest
        partial = destination.with_name(destination.name + ".partial")
        if partial.exists():
            raise ValueError(f"stale partial snapshot: {partial}")
        partial.mkdir(parents=True, mode=0o700)
        try:
            for rel, src in copied.items():
                dst = partial / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst, follow_symlinks=False)
                if sha256(dst) != files[rel]["sha256"]:
                    raise ValueError(f"copy hash mismatch: {rel}")
            if sha256(cp_path) != before:
                raise ValueError("checkpoint changed during snapshot copy")
            (partial / "bounded-snapshot-manifest.json").write_text(
                json.dumps(manifest, sort_keys=True, indent=2) + "\n")
            os.rename(partial, destination)
        except BaseException:
            shutil.rmtree(partial)
            raise
        return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--archives", type=Path, required=True)
    ap.add_argument("--destination", type=Path, required=True)
    ap.add_argument("--expected-faults", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    manifest = freeze(args.source, args.config, args.archives, args.destination,
                      args.expected_faults, args.dry_run)
    print(json.dumps({"case_id": manifest["case_id"],
                      "completed_fault_trials": manifest["completed_fault_trials"],
                      "file_count": len(manifest["files"]),
                      "raw_archive_count": len(manifest["raw_archives"]),
                      "dry_run": args.dry_run}, sort_keys=True))


if __name__ == "__main__":
    main()
