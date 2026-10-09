"""Reclaim expanded MiniCluster scratch after a lossless audited archive exists."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import time

from .archive import TERMINAL
from .collect import sha256
from .worker import atomic_json


def _hash_stream(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def compact_case(data_root: Path, case_id: str, min_bytes: int = 1024 * 1024) -> dict:
    """Remove only trial scratch files whose bytes were re-read from the archive."""
    if not case_id or "/" in case_id or ".." in case_id or min_bytes < 0:
        raise ValueError("invalid case ID or size threshold")
    case = data_root / "cases" / case_id
    result_path = case / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    audit_path = case / "offline-causal-audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    evidence = result.get("evidence_archive") or {}
    if (result.get("case_id") != case_id or result.get("status") not in TERMINAL["campaign"]
            or audit.get("case_id") != case_id
            or audit.get("campaign_result_sha256") != sha256(result_path)
            or not evidence):
        raise ValueError("case lacks terminal result, bound archive, or completed audit")
    archive = data_root / evidence["path"]
    manifest_path = data_root / evidence["manifest_path"]
    if (sha256(archive) != evidence["sha256"]
            or sha256(manifest_path) != evidence["manifest_sha256"]):
        raise ValueError("evidence archive receipt does not match bytes on disk")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("archive_sha256") != evidence["sha256"]
            or manifest.get("case_id") != case_id):
        raise ValueError("archive manifest does not describe this case")
    candidates = {}
    for path in case.glob("trials/*/scratch/**/*"):
        if path.is_file() and not path.is_symlink() and path.stat().st_size >= min_bytes:
            candidates[str(path.relative_to(case))] = path
    if not candidates:
        return {"case_id": case_id, "removed_files": 0, "reclaimed_bytes": 0,
                "archive_sha256": evidence["sha256"]}
    if not set(candidates) <= set(manifest.get("members", [])):
        raise ValueError("expanded scratch is absent from lossless archive manifest")
    verified = []
    with tarfile.open(archive, "r:gz") as packed:
        for member in packed:
            path = candidates.get(member.name)
            if path is None:
                continue
            if not member.isfile() or member.size != path.stat().st_size:
                raise ValueError(f"archived scratch size differs: {member.name}")
            source = packed.extractfile(member)
            if source is None or _hash_stream(source) != sha256(path):
                raise ValueError(f"archived scratch hash differs: {member.name}")
            verified.append(path)
    if len(verified) != len(candidates):
        raise ValueError("archive omitted selected scratch files")
    sizes = {str(path.relative_to(case)): path.stat().st_size for path in verified}
    for path in verified:
        path.unlink()
    receipt = {"schema_version": 1, "case_id": case_id,
               "archive_sha256": evidence["sha256"],
               "audit_sha256": sha256(audit_path), "removed_files": len(verified),
               "reclaimed_bytes": sum(sizes.values()), "removed_paths": sizes,
               "finished_at": time.time()}
    atomic_json(case / "evidence-compaction.json", receipt)
    return receipt


def archive_and_compact_replay(data_root: Path, campaign: Path, archive_name: str,
                               release_manifest: Path, min_bytes: int = 1024 * 1024) -> dict:
    """Archive a versioned replay and remove only byte-verified scratch copies.

    The raw result and audit stay in place.  The archive contains every regular
    evidence file, including scratch, except the empty process lock and our own
    receipt.  This also works for campaigns outside ``cases/<case_id>``.
    """
    data_root = data_root.resolve()
    campaign = campaign.resolve()
    if (not campaign.is_dir() or not campaign.is_relative_to(data_root)
            or not archive_name or "/" in archive_name or ".." in archive_name
            or min_bytes < 0):
        raise ValueError("invalid replay path, archive name, or size threshold")
    from .core_release import verify as verify_core_release
    release = verify_core_release(release_manifest.resolve())
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    result_sha = sha256(result_path)
    audit_sha = sha256(audit_path)
    expected_core = {name: release["files"][f"Mallory/core/{name}"]
                     for name in ("audit.py", "events.py", "graph.py",
                                  "feedback.py", "campaign.py")}
    if (result.get("status") not in TERMINAL["campaign"]
            or audit.get("campaign_result_sha256") != result_sha
            or audit.get("core_source_sha256") != expected_core
            or audit.get("report_gate_passed") is not True
            or not isinstance(audit.get("healthy_observed_path_doors"), int)
            or isinstance(audit.get("healthy_observed_path_doors"), bool)
            or audit["healthy_observed_path_doors"] <= 0):
        raise ValueError("replay lacks terminal result or final-release bound audit")
    out = data_root / "evidence_archives" / "replays"
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"{archive_name}.tar.gz"
    manifest_path = out / f"{archive_name}.manifest.json"
    receipt_path = campaign / "evidence-compaction.json"
    if archive.is_file() or manifest_path.is_file():
        if not archive.is_file() or not manifest_path.is_file():
            raise ValueError("partial replay archive exists")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("archive_sha256") != sha256(archive)
                or manifest.get("result_sha256") != result_sha
                or manifest.get("audit_sha256") != audit_sha
                or manifest.get("core_release_id") != release["release_id"]
                or manifest.get("campaign_relative") != str(campaign.relative_to(data_root))):
            raise ValueError("existing replay archive is not bound to current evidence")
    else:
        if shutil.disk_usage(data_root).free < 5 * 1024**3:
            raise RuntimeError("insufficient disk reserve for replay archive")
        files = [path for path in sorted(campaign.rglob("*")) if path.is_file()
                 and path.name not in (".campaign.lock", "evidence-compaction.json")]
        if not files or any(path.is_symlink() for path in files):
            raise ValueError("replay evidence missing or contains symlink")
        members = {str(path.relative_to(campaign)): {"sha256": sha256(path),
                    "bytes": path.stat().st_size} for path in files}
        temporary = archive.with_name(f".{archive.name}.{os.getpid()}.tmp")
        try:
            with tarfile.open(temporary, "w:gz") as packed:
                for path in files:
                    packed.add(path, arcname=str(path.relative_to(campaign)), recursive=False)
            with tarfile.open(temporary, "r:gz") as packed:
                actual = {}
                for member in packed:
                    if not member.isfile() or member.name not in members:
                        raise ValueError("replay archive has unexpected member")
                    source = packed.extractfile(member)
                    if source is None:
                        raise ValueError("replay archive member unreadable")
                    actual[member.name] = {"sha256": _hash_stream(source),
                                           "bytes": member.size}
                if actual != members:
                    raise ValueError("replay archive differs from source bytes")
            os.replace(temporary, archive)
            manifest = {"schema_version": 1,
                        "campaign_relative": str(campaign.relative_to(data_root)),
                        "result_sha256": result_sha, "audit_sha256": audit_sha,
                        "core_release_id": release["release_id"],
                        "archive_sha256": sha256(archive), "members": members}
            atomic_json(manifest_path, manifest)
        finally:
            temporary.unlink(missing_ok=True)
    members = manifest["members"]
    if any(Path(name).is_absolute() or ".." in Path(name).parts for name in members):
        raise ValueError("unsafe replay archive member path")
    scratch = {name: campaign / name for name in members
                if name.startswith("trials/") and "/scratch/" in name
                and members[name]["bytes"] >= min_bytes}
    selected = {name: path for name, path in scratch.items() if path.is_file()}
    with tarfile.open(archive, "r:gz") as packed:
        archived = {}
        for member in packed:
            if member.name not in selected:
                continue
            source = packed.extractfile(member)
            if source is None:
                raise ValueError("selected scratch member unreadable")
            archived[member.name] = {"sha256": _hash_stream(source),
                                     "bytes": member.size}
        if set(archived) != set(selected):
            raise ValueError("selected scratch member absent from archive")
    for name, path in selected.items():
        if (path.is_symlink() or archived[name] != members[name]
                or sha256(path) != members[name]["sha256"]
                or path.stat().st_size != members[name]["bytes"]):
            raise ValueError(f"scratch differs from archive: {name}")
    for path in selected.values():
        path.unlink()
    removed = {name: members[name] for name in scratch
               if not (campaign / name).exists()}
    receipt = {"schema_version": 1,
               "campaign_relative": str(campaign.relative_to(data_root)),
               "result_sha256": result_sha, "audit_sha256": audit_sha,
               "archive_relative": str(archive.relative_to(data_root)),
               "archive_sha256": sha256(archive),
               "manifest_sha256": sha256(manifest_path),
               "core_release_id": release["release_id"],
               "removed_files": len(removed),
               "reclaimed_bytes": sum(item["bytes"] for item in removed.values()),
               "removed_paths": removed,
               "finished_at": time.time()}
    if receipt_path.is_file():
        old = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (old.get("archive_sha256") != receipt["archive_sha256"]
                or old.get("result_sha256") != result_sha):
            raise ValueError("existing replay compaction receipt differs")
        return old
    atomic_json(receipt_path, receipt)
    return receipt


def restore_replay_scratch(data_root: Path, campaign: Path) -> dict:
    """Restore compacted scratch from its SHA-bound archive, without overwriting files."""
    data_root = data_root.resolve()
    campaign = campaign.resolve()
    receipt_path = campaign / "evidence-compaction.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    archive = data_root / receipt["archive_relative"]
    manifest_path = archive.with_name(archive.name.removesuffix(".tar.gz") + ".manifest.json")
    if (not campaign.is_relative_to(data_root)
            or receipt.get("campaign_relative") != str(campaign.relative_to(data_root))
            or sha256(campaign / "result.json") != receipt.get("result_sha256")
            or sha256(campaign / "offline-causal-audit.json") != receipt.get("audit_sha256")
            or not archive.resolve().is_relative_to(data_root)
            or sha256(archive) != receipt.get("archive_sha256")
            or sha256(manifest_path) != receipt.get("manifest_sha256")):
        raise ValueError("replay compaction receipt or archive hash changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed = receipt.get("removed_paths") or {}
    if (manifest.get("archive_sha256") != receipt["archive_sha256"]
            or manifest.get("members") is None
            or not isinstance(removed, dict)
            or not set(removed) <= set(manifest["members"])):
        raise ValueError("replay manifest does not bind removed scratch")
    restored = 0
    restored_bytes = 0
    with tarfile.open(archive, "r:gz") as packed:
        packed_members = {member.name: member for member in packed}
        for name, metadata in removed.items():
            relative = Path(name)
            destination = campaign / relative
            if (relative.is_absolute() or ".." in relative.parts
                    or not name.startswith("trials/") or "/scratch/" not in name
                    or metadata != manifest["members"][name]
                    or not destination.parent.resolve().is_relative_to(campaign)):
                raise ValueError(f"unsafe or mismatched replay member: {name}")
            member = packed_members.get(name)
            if member is None or not member.isfile() or member.size != metadata["bytes"]:
                raise ValueError(f"missing replay archive member: {name}")
            source = packed.extractfile(member)
            if source is None or _hash_stream(source) != metadata["sha256"]:
                raise ValueError(f"mismatched replay archive member: {name}")
            if destination.exists():
                if sha256(destination) != metadata["sha256"]:
                    raise ValueError(f"existing replay scratch differs: {name}")
                continue
            source = packed.extractfile(member)
            assert source is not None
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
            try:
                with temporary.open("wb") as output:
                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
                if sha256(temporary) != metadata["sha256"]:
                    raise ValueError(f"restored replay scratch differs: {name}")
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            restored += 1
            restored_bytes += metadata["bytes"]
    return {"restored_files": restored, "restored_bytes": restored_bytes,
            "archive_sha256": receipt["archive_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data/mallory"))
    parser.add_argument("--case-id")
    parser.add_argument("--min-mib", type=int, default=1)
    parser.add_argument("--replay", type=Path,
                        help="versioned replay directory under the data root")
    parser.add_argument("--archive-name", help="unique archive basename for replay")
    parser.add_argument("--core-release-manifest", type=Path)
    args = parser.parse_args()
    if args.replay:
        if not args.archive_name or not args.core_release_manifest:
            parser.error("replay compaction needs archive name and core release manifest")
        print(json.dumps(archive_and_compact_replay(
            args.data_root.resolve(), args.replay.resolve(), args.archive_name,
            args.core_release_manifest.resolve(), args.min_mib * 1024 * 1024),
            sort_keys=True))
        return 0
    if not args.case_id:
        parser.error("--case-id is required for a canonical campaign")
    print(json.dumps(compact_case(args.data_root.resolve(), args.case_id,
                                  args.min_mib * 1024 * 1024), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
