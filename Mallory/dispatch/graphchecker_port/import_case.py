"""Verify a terminal native campaign and mirror its small table receipts.

Trial traces stay in the immutable campaign directory.  This command reads
and verifies them before publishing the config, checkpoint, and summary used
by the 102-check aggregate table.  It never edits the source campaign.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Mallory.core.graphchecker_campaign import verify_trial_artifacts
from Mallory.dispatch.graphchecker_port.aggregate import _native_status
from Mallory.dispatch.graphchecker_port.plan import CASE_ID, sha256


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _trial_result(campaign: Path, case_id: str, record: dict[str, Any]) -> Path:
    name = record.get("name")
    if not isinstance(name, str) or not name.startswith("r") or not name[1:].isdigit():
        raise ValueError("invalid native trial name")
    relative = f"trials/{name}/result.json"
    if record.get("result") != relative:
        raise ValueError(f"invalid native trial result path: {name}")
    path = campaign / relative
    if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"native trial result is missing or linked: {path}")
    result = _json(path)
    if (result.get("case_id") != case_id or result.get("backend") != "graphchecker_native"
            or result.get("status") != record.get("status")
            or result.get("fault_plan") != record.get("faults")
            or result.get("target_exception_triggered") is not
            record.get("target_exception_triggered")):
        raise ValueError(f"native trial record differs from result: {name}")
    if abs(float(result.get("elapsed_seconds", -1)) -
           float(record.get("elapsed_seconds", -2))) > 0.001:
        raise ValueError(f"native trial elapsed time differs: {name}")
    verify_trial_artifacts(path.parent, result)
    return path


def _publish_index(data_root: Path, case_id: str, relative: str) -> None:
    """One atomic pointer selects a complete immutable snapshot for a case."""
    data_root.mkdir(parents=True, exist_ok=True)
    lock_path = data_root / ".import-index.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        index_path = data_root / "import-index.json"
        if index_path.exists():
            index = _json(index_path)
            if index.get("schema_version") != 1 or not isinstance(index.get("cases"), dict):
                raise ValueError("invalid existing import index")
        else:
            index = {"schema_version": 1, "cases": {}}
        index["cases"][case_id] = relative
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=data_root, prefix=".import-index.",
                                         delete=False) as temporary:
            staged = Path(temporary.name)
            json.dump(index, temporary, sort_keys=True, indent=2)
            temporary.write("\n")
        try:
            staged.replace(index_path)
        finally:
            staged.unlink(missing_ok=True)


def import_case(case_id: str, config: Path, campaign: Path, data_root: Path) -> dict:
    if not CASE_ID.fullmatch(case_id):
        raise ValueError("invalid case ID")
    config = config.resolve(strict=True)
    campaign = campaign.resolve(strict=True)
    data_root = data_root.resolve()
    source_paths = {"config": config, "checkpoint": campaign / "checkpoint.json",
                    "summary": campaign / "summary.json"}
    documents = {name: _json(source_paths[name]) for name in ("config", "checkpoint")}
    if documents["config"].get("case_id") != case_id:
        raise ValueError("config case ID differs")
    if documents["checkpoint"].get("terminal") is not True:
        raise ValueError("cannot publish a running campaign")
    documents["summary"] = _json(source_paths["summary"])
    config_hash = sha256(config)
    status, terminal, metrics = _native_status(
        case_id, documents["checkpoint"], documents["summary"], config_hash)
    if not terminal:
        raise ValueError(f"cannot publish a running campaign: {status}")
    records = documents["checkpoint"]["trials"]
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid native trial record")
        _trial_result(campaign, case_id, record)
    source_hashes = {name: sha256(path) for name, path in source_paths.items()}
    if source_hashes["config"] != config_hash:
        raise ValueError("config changed during native trial verification")
    relative = f"imports/{case_id}/{config_hash[:16]}-{source_hashes['checkpoint'][:12]}"
    destination = data_root / relative
    names = {"config": "config.json", "checkpoint": "checkpoint.json",
             "summary": "summary.json"}
    receipt = {
        "schema_version": 1, "case_id": case_id, "status": status,
        "config_sha256": config_hash, "completed_fault_trials": metrics["completed_fault_trials"],
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source_campaign": str(campaign),
        "source_paths": {name: str(path) for name, path in source_paths.items()},
        "source_sha256": source_hashes,
        "verified_native_trial_results": len(records),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".import-", dir=destination.parent))
    try:
        for name, source in source_paths.items():
            shutil.copyfile(source, staged / names[name])
            if sha256(staged / names[name]) != source_hashes[name]:
                raise ValueError(f"source changed during mirror: {source}")
        (staged / "import-receipt.json").write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if destination.exists():
            if any(sha256(destination / names[name]) != source_hashes[name]
                   for name in names):
                raise ValueError("content-addressed import path contains different evidence")
        else:
            staged.rename(destination)
        _publish_index(data_root, case_id, relative)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--data-root", type=Path,
                        default=Path("data/mallory/graphchecker_port"))
    args = parser.parse_args()
    print(json.dumps(import_case(args.case_id, args.config, args.campaign,
                                 args.data_root), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
