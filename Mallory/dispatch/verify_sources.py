"""Verify remote source content against clean, inventory-pinned local trees.

Remote worktree .git pointers are often broken, so compare every tracked file
against node0's clean tree at the expected commit.  Per-case target/test hashes
from the inventory are checked separately before a trial is admitted.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

try:
    from .worker import atomic_json
except ImportError:
    from worker import atomic_json

try:
    from .scheduler import ssh_prefix
except ImportError:
    from scheduler import ssh_prefix


FINGERPRINT_SCRIPT = r'''
import hashlib, json, os, pathlib, sys
root = pathlib.Path(sys.argv[1])
paths = json.load(sys.stdin)
result = hashlib.sha256()
total = 0
for relative in paths:
    file = root / relative
    try:
        if file.is_symlink():
            payload = b'L' + os.fsencode(os.readlink(file))
        elif file.is_file():
            digest = hashlib.sha256()
            with file.open('rb') as inp:
                for chunk in iter(lambda: inp.read(1024 * 1024), b''):
                    digest.update(chunk)
                    total += len(chunk)
            payload = b'F' + digest.digest()
        else:
            payload = b'MISSING'
    except OSError:
        payload = b'ERROR'
    result.update(os.fsencode(relative) + b'\0' + payload + b'\0')
print(json.dumps({'digest': result.hexdigest(), 'files': len(paths), 'bytes': total}))
'''


def local_reference(root: Path, expected_commit: str) -> tuple[list[str], dict]:
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    if head != expected_commit:
        raise RuntimeError(f"{root}: commit {head} differs from inventory {expected_commit}")
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True).stdout
    if dirty:
        raise RuntimeError(f"{root}: tracked source tree is dirty")
    raw = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                         capture_output=True, check=True).stdout
    paths = sorted(os.fsdecode(path) for path in raw.split(b"\0") if path)
    reference = subprocess.run([sys.executable, "-c", FINGERPRINT_SCRIPT, str(root)],
                               input=json.dumps(paths), capture_output=True, text=True, check=True)
    return paths, json.loads(reference.stdout)


def remote_fingerprint(host: dict, key: Path, root: Path, paths: list[str]) -> dict:
    command = ssh_prefix(host, key) + [shlex.join(["python3", "-c", FINGERPRINT_SCRIPT, str(root)])]
    result = subprocess.run(command, input=json.dumps(paths), capture_output=True, text=True,
                            timeout=240)
    if result.returncode:
        raise RuntimeError(f"{host['name']}: source fingerprint failed: {result.stderr.strip()[:300]}")
    return json.loads(result.stdout)


def verify_root(host: dict, key: Path, root: Path, expected_commit: str) -> dict:
    paths, local = local_reference(root, expected_commit)
    remote = local if host["kind"] == "local" else remote_fingerprint(host, key, root, paths)
    return {
        "host": host["name"], "source_root": str(root), "expected_commit": expected_commit,
        "tracked_files": len(paths), "reference_digest": local["digest"],
        "host_digest": remote["digest"], "content_match": local["digest"] == remote["digest"],
        "host_git_commit": expected_commit if host["kind"] == "local" else None,
        "verification": "local_git_commit_and_clean_tree" if host["kind"] == "local"
                        else "all_tracked_files_equal_to_clean_node0_commit",
    }


def build_reference(inventory_path: Path, out: Path) -> dict:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    roots = {}
    for row in inventory["cases"]:
        provenance = row["provenance"]
        root, commit = provenance["source_root"], provenance["source_commit"]
        if root in roots and roots[root] != commit:
            raise ValueError(f"conflicting commits for {root}")
        roots[root] = commit
    entries = {}
    for root, commit in sorted(roots.items()):
        paths, fingerprint = local_reference(Path(root), commit)
        entries[root] = {"commit": commit, "paths": paths,
                         "digest": fingerprint["digest"], "files": len(paths)}
    document = {"schema_version": 1, "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
                "roots": entries}
    atomic_json(out, document)
    return document


def verify_from_reference(host: dict, key: Path, root: Path, expected_commit: str,
                          reference: dict, actual_root: Path | None = None) -> dict:
    entry = reference["roots"].get(str(root))
    if not entry or entry["commit"] != expected_commit:
        raise RuntimeError(f"{root}: source reference absent or commit differs from inventory")
    actual_root = actual_root or root
    if host["kind"] == "local":
        checked = subprocess.run([sys.executable, "-c", FINGERPRINT_SCRIPT, str(actual_root)],
                                 input=json.dumps(entry["paths"]), capture_output=True,
                                 text=True, check=True)
        actual = json.loads(checked.stdout)
    else:
        actual = remote_fingerprint(host, key, actual_root, entry["paths"])
    return {"host": host["name"], "source_root": str(root),
            "actual_root": str(actual_root),
            "expected_commit": expected_commit, "tracked_files": entry["files"],
            "reference_digest": entry["digest"], "host_digest": actual["digest"],
            "content_match": entry["digest"] == actual["digest"],
            "verification": "all_tracked_files_equal_to_clean_node0_commit"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def overlay_receipt(row: dict, config: dict | None) -> tuple[Path, dict | None]:
    root = Path(row["provenance"]["source_root"])
    if config and config.get("source_equivalent_root"):
        if config.get("source_overlay_receipt"):
            raise ValueError(f"{row['case_id']}: clean equivalent root and patched overlay are exclusive")
        equivalent = Path(config["source_equivalent_root"])
        if not equivalent.is_absolute() or not equivalent.is_dir():
            raise ValueError(f"{row['case_id']}: clean equivalent root is missing or relative")
        return equivalent, None
    if not config or not config.get("source_overlay_receipt"):
        return root, None
    receipt_path = Path(config["source_overlay_receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if config.get("source_overlay_receipt_sha256") != sha256_file(receipt_path):
        raise ValueError(f"{row['case_id']}: overlay receipt digest missing or mismatched")
    if Path(receipt["base_root"]).resolve() != root.resolve():
        raise ValueError(f"{row['case_id']}: overlay base root mismatch")
    patched_root = Path(receipt["patched_root"]).resolve()
    patch_file = Path(receipt["patch_file"])
    if not patch_file.is_file() or sha256_file(patch_file) != receipt["patch_sha256"]:
        raise ValueError(f"{row['case_id']}: overlay patch hash mismatch")
    modified = receipt.get("modified_files")
    artifacts = receipt.get("compiled_artifacts")
    if not isinstance(modified, dict) or not modified or not isinstance(artifacts, list) or not artifacts:
        raise ValueError(f"{row['case_id']}: overlay file/artifact hashes missing")
    for relative, expected in modified.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{row['case_id']}: unsafe overlay file path")
        file = patched_root / path
        if not file.is_file() or sha256_file(file) != expected:
            raise ValueError(f"{row['case_id']}: modified file hash mismatch: {file}")
    for artifact in artifacts:
        file = Path(artifact["path"])
        if not file.is_file() or sha256_file(file) != artifact["sha256"]:
            raise ValueError(f"{row['case_id']}: compiled artifact hash mismatch: {file}")
    return patched_root, receipt


def case_expected_files(row: dict, config: dict | None = None) -> list[tuple[Path, str]]:
    root, overlay = overlay_receipt(row, config)
    target = row["target"]
    mapping = config.get("mapping", {}) if config else {}
    target_hash = mapping.get("target_source_sha256", target["source_sha256"])
    if not overlay and target_hash != target["source_sha256"]:
        raise ValueError(f"{row['case_id']}: pristine target source hash differs from inventory")
    expected = [(target["source_path"], target_hash)]
    test_path = row.get("workload", {}).get("test_source_path")
    if not test_path:
        raise ValueError(f"{row['case_id']}: no mapped cluster test source")
    matches = [candidate for candidate in row["workload"].get("candidates", [])
               if candidate.get("source_path") == test_path and candidate.get("source_sha256")]
    if not matches:
        raise ValueError(f"{row['case_id']}: selected test source hash missing")
    test_hash = mapping.get("test_source_sha256", matches[0]["source_sha256"])
    if not overlay and test_hash != matches[0]["source_sha256"]:
        raise ValueError(f"{row['case_id']}: pristine test source hash differs from inventory")
    expected.append((test_path, test_hash))
    files = []
    for relative, digest in expected:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not digest:
            raise ValueError(f"{row['case_id']}: unsafe or unhashed source path: {relative}")
        files.append((root / path, digest))
    return files


def verify_case_files(host: dict, key: Path, row: dict,
                      config: dict | None = None) -> tuple[bool, str]:
    expected = case_expected_files(row, config)
    if host["kind"] == "local":
        actual = []
        for path, _ in expected:
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
            actual.append(digest)
    else:
        script = "import hashlib,json,pathlib,sys; print(json.dumps([hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() if pathlib.Path(p).is_file() else 'missing' for p in json.loads(sys.argv[1])]))"
        command = ssh_prefix(host, key) + [shlex.join(["python3", "-c", script,
                                                      json.dumps([str(path) for path, _ in expected])])]
        result = subprocess.run(command, capture_output=True, text=True, timeout=25)
        if result.returncode:
            return False, result.stderr.strip()[:240]
        actual = json.loads(result.stdout)
    mismatches = [str(path) for (path, digest), observed in zip(expected, actual) if digest != observed]
    return (False, "source SHA-256 mismatch: " + ", ".join(mismatches)) if mismatches else (True, "target and test source SHA-256 match inventory")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--make-reference", type=Path, required=True)
    args = parser.parse_args()
    report = build_reference(args.inventory, args.make_reference)
    print(json.dumps({"roots": len(report["roots"]),
                      "tracked_files": sum(x["files"] for x in report["roots"].values()),
                      "output": str(args.make_reference)}))
