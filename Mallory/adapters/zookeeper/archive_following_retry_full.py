#!/usr/bin/env python3
"""Archive one terminal ZooKeeper retry campaign without changing its raw files."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive(campaign: Path, continuation: Path, output: Path,
            manifest_path: Path) -> dict:
    if output.exists() or manifest_path.exists():
        raise FileExistsError("archive or manifest already exists")
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    result_path, audit_path, config_path = (
        campaign / name for name in
        ("result.json", "offline-causal-audit.json", "config.json"))
    result, audit, config, proof = map(read, (
        result_path, audit_path, config_path, continuation))
    if (result.get("case_id") != "ZOOKEEPER-07"
            or result.get("status") not in {"budget_exhausted", "queue_exhausted"}
            or result.get("fault_trials_completed") != 80
            or audit.get("report_gate_passed") is not True
            or audit.get("campaign_result_sha256") != sha(result_path)
            or proof.get("status") != "postfault_retry_target_proven"
            or proof.get("proven_postfault_path_trials", 0) < 1
            or proof.get("campaign_result_sha256") != sha(result_path)
            or proof.get("offline_audit_sha256") != sha(audit_path)
            or proof.get("config_sha256") != sha(config_path)
            or sha(Path(config["source_overlay_receipt"])) !=
                config["source_overlay_receipt_sha256"]):
        raise ValueError("terminal campaign or strict continuation is not attested")
    files = sorted(path for path in campaign.rglob("*") if path.is_file())
    if not files or any(path.is_symlink() for path in files):
        raise ValueError("raw campaign is empty or contains a symlink")
    members = {str(path.relative_to(campaign)): {
        "sha256": sha(path), "bytes": path.stat().st_size} for path in files}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with tarfile.open(temporary, "w:gz") as packed:
            for path in files:
                packed.add(path, arcname=str(path.relative_to(campaign)), recursive=False)
        with tarfile.open(temporary, "r:gz") as packed:
            extracted = {}
            for member in packed:
                if not member.isfile() or member.name not in members:
                    raise ValueError(f"unexpected archive member: {member.name}")
                stream = packed.extractfile(member)
                if stream is None:
                    raise ValueError(f"unreadable archive member: {member.name}")
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                extracted[member.name] = {"sha256": digest.hexdigest(),
                                          "bytes": member.size}
            if extracted != members:
                raise ValueError("archive members differ from raw evidence")
        if sha(result_path) != proof["campaign_result_sha256"]:
            raise ValueError("campaign result changed during archiving")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    manifest = {
        "schema_version": 1, "case_id": "ZOOKEEPER-07",
        "source_campaign": str(campaign.resolve()),
        "archive_sha256": sha(output), "archive_bytes": output.stat().st_size,
        "campaign_result_sha256": sha(result_path),
        "offline_audit_sha256": sha(audit_path),
        "config_sha256": sha(config_path),
        "continuation_receipt_sha256": sha(continuation),
        "source_overlay_receipt_sha256": config["source_overlay_receipt_sha256"],
        "trial_count": len(result["trials"]),
        "strict_path_trials": proof["proven_postfault_path_trials"],
        "members": members,
        "scratch_preservation": "full archive includes trial test-data; node0 expanded copy may omit it",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("campaign", "continuation", "output", "manifest"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    manifest = archive(*(getattr(args, name).resolve() for name in
                         ("campaign", "continuation", "output", "manifest")))
    print(json.dumps({key: manifest[key] for key in (
        "archive_sha256", "archive_bytes", "trial_count", "strict_path_trials")},
        sort_keys=True))
