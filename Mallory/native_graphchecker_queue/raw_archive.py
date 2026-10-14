"""Verify sealed local raw evidence after a native campaign releases scratch."""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def pinned_archives(binding: dict, case_id: str) -> tuple[dict, list[dict]]:
    """Validate the optional, case-specific immutable archive index."""
    pin = binding.get("raw_archive_evidence")
    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"}:
        raise ValueError("missing pinned raw archive evidence")
    receipt_path = Path(pin["path"])
    if (not receipt_path.is_absolute() or receipt_path.is_symlink() or
            _sha(receipt_path) != pin["sha256"]):
        raise ValueError("raw archive receipt changed")
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("schema_version") != 1 or
            receipt.get("case_id") != case_id or
            receipt.get("status") != "reclaimed" or
            not isinstance(receipt.get("items"), list) or
            not receipt["items"]):
        raise ValueError("raw archive receipt identity changed")
    seen = set()
    for item in receipt["items"]:
        raw = Path(item["raw_dir"])
        archive = Path(item["archive"])
        if (not raw.is_absolute() or ".." in raw.parts or
                not archive.is_absolute() or archive.is_symlink() or
                str(raw) in seen or _sha(archive) != item["archive_sha256"]):
            raise ValueError("raw archive bytes or root changed")
        seen.add(str(raw))
    return pin, receipt["items"]


def verify_trial_evidence(binding: dict, case_id: str,
                          trial_hashes: dict[str, str],
                          raw_targets: dict[str, str]) -> bool:
    """Check live files and exact archived raw members, without extracting them."""
    try:
        _, archives = pinned_archives(binding, case_id)
        if not isinstance(raw_targets, dict):
            return False
        needed: dict[str, dict[str, str]] = {str(item["archive"]): {}
                                                 for item in archives}
        for name, digest in trial_hashes.items():
            path = Path(name)
            if not path.is_absolute() or path.name != "summary.json" and name in raw_targets:
                return False
            if name in raw_targets:
                target = Path(raw_targets[name])
                if (path.parent.name != "original-graph" or
                        not path.parent.is_symlink() or
                        path.parent.readlink() != target.parent):
                    return False
                matching = [item for item in archives if
                            target.is_relative_to(Path(item["raw_dir"]))]
                if len(matching) != 1:
                    return False
                item = matching[0]
                relative = target.relative_to(Path(item["raw_dir"]))
                member = str(PurePosixPath(Path(item["raw_dir"]).name,
                                            *relative.parts))
                needed[str(item["archive"])][member] = digest
            if path.is_file():
                if _sha(path) != digest:
                    return False
            elif name not in raw_targets:
                return False
        if not set(raw_targets).issubset(trial_hashes):
            return False
        for item in archives:
            archive_path = Path(item["archive"])
            members = needed[str(archive_path)]
            found = set()
            with tarfile.open(archive_path, "r:gz") as archive:
                for member in archive:
                    parts = PurePosixPath(member.name).parts
                    if (not parts or parts[0] != Path(item["raw_dir"]).name or
                            ".." in parts or member.issym() or member.islnk() or
                            not (member.isfile() or member.isdir())):
                        return False
                    if member.name in members:
                        if not member.isfile() or member.name in found:
                            return False
                        stream = archive.extractfile(member)
                        if stream is None:
                            return False
                        digest = hashlib.sha256()
                        for block in iter(lambda: stream.read(1 << 20), b""):
                            digest.update(block)
                        if digest.hexdigest() != members[member.name]:
                            return False
                        found.add(member.name)
            if found != set(members):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError,
            json.JSONDecodeError):
        return False
