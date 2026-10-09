"""Build and verify an immutable Mallory core Python release for each launch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


CORE_FILES = ("__init__.py", "audit.py", "campaign.py", "events.py",
              "feedback.py", "graph.py", "junit.py", "scheduler.py")
PACKAGE_INIT = ("from pkgutil import extend_path\n"
                "__path__ = extend_path(__path__, __name__)\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_hashes(root: Path) -> dict[str, str]:
    return {"Mallory/__init__.py": sha256(root / "Mallory/__init__.py"),
            **{f"Mallory/core/{name}": sha256(root / "Mallory/core" / name)
               for name in CORE_FILES}}


def release_id(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def verify(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    expected = manifest.get("files")
    if (manifest.get("schema_version") != 1 or not isinstance(expected, dict)
            or set(expected) != {"Mallory/__init__.py", *
                                 (f"Mallory/core/{name}" for name in CORE_FILES)}
            or manifest.get("release_id") != release_id(expected)
            or root.name != manifest["release_id"]):
        raise ValueError("invalid core release manifest")
    actual = file_hashes(root)
    if actual != expected:
        raise ValueError("core release file hashes differ")
    return manifest


def build(repo: Path, output_root: Path) -> Path:
    source = repo / "Mallory/core"
    files = {"Mallory/__init__.py": hashlib.sha256(PACKAGE_INIT.encode()).hexdigest(),
             **{f"Mallory/core/{name}": sha256(source / name) for name in CORE_FILES}}
    identity = release_id(files)
    destination = output_root / identity
    manifest_path = destination / "manifest.json"
    if destination.exists():
        if verify(manifest_path)["files"] != files:
            raise ValueError("existing core release differs")
        return manifest_path
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".mallory-core-release-", dir=output_root))
    try:
        target = temporary / "Mallory/core"
        target.mkdir(parents=True)
        (temporary / "Mallory/__init__.py").write_text(PACKAGE_INIT, encoding="utf-8")
        for name in CORE_FILES:
            shutil.copy2(source / name, target / name)
        (temporary / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "release_id": identity, "files": files},
            sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if file_hashes(temporary) != files:
            raise ValueError("core changed during release build")
        os.replace(temporary, destination)
        verify(manifest_path)
        return manifest_path
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out-root", type=Path,
                        default=Path("Mallory/dispatch/releases"))
    parser.add_argument("--verify", type=Path, metavar="MANIFEST")
    args = parser.parse_args()
    path = args.verify if args.verify else build(args.repo.resolve(), args.out_root.resolve())
    manifest = verify(path)
    print(json.dumps({"manifest": str(path), "release_id": manifest["release_id"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
