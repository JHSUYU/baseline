#!/usr/bin/env python3
"""Attest the separately patched ZooKeeper lane and its compiled classes."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
BASE_RECEIPT = HERE / "zookeeper-3.8.7-overlay.json"
BASE_PATCH = HERE / "zookeeper-3.8.7-mallory.patch"
PATCH = HERE / "zookeeper-3.8.7-lane2.patch"
RECEIPT = HERE / "zookeeper-3.8.7-lane2-overlay.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_patch(root: Path, base_root: Path) -> None:
    generic = BASE_PATCH.read_text(encoding="utf-8")
    marker = "diff --git a/zookeeper-server/src/main/java/org/apache/zookeeper/server/PrepRequestProcessor.java"
    if generic.count(marker) != 1:
        raise RuntimeError("Cannot isolate the base patch's POM hunk")
    remainder = marker + generic.split(marker, 1)[1]
    rel = "zookeeper-server/pom.xml"
    pom_diff = subprocess.run(
        ["diff", "-u", "--label", f"a/{rel}", "--label", f"b/{rel}",
         str(base_root / rel), str(root / rel)],
        text=True, capture_output=True,
    )
    if pom_diff.returncode != 1:
        raise RuntimeError(f"Could not derive lane POM patch: {pom_diff.stderr}")
    patch = f"diff --git a/{rel} b/{rel}\n" + pom_diff.stdout + remainder
    PATCH.write_text(patch, encoding="utf-8")
    checked = subprocess.run(
        ["git", "apply", "--reverse", "--check", str(PATCH)],
        cwd=root, text=True, capture_output=True,
    )
    if checked.returncode:
        raise RuntimeError(f"Lane patch does not reverse cleanly: {checked.stderr}")
    forward = subprocess.run(
        ["patch", "--dry-run", "--batch", "-p1", "-d", str(base_root)],
        input=patch, text=True, capture_output=True,
    )
    if forward.returncode:
        raise RuntimeError(f"Lane patch does not apply to pristine source: {forward.stdout}\n{forward.stderr}")


def make_receipt(root: Path) -> None:
    original = json.loads(BASE_RECEIPT.read_text(encoding="utf-8"))
    make_patch(root, Path(original["base_root"]))
    modified = {}
    for rel, expected in original["modified_files"].items():
        path = root / rel
        if not path.is_file():
            raise RuntimeError(f"Missing patched source: {path}")
        actual = sha(path)
        if rel != "zookeeper-server/pom.xml" and actual != expected:
            raise RuntimeError(f"Generic hook source changed in lane2: {rel}")
        modified[rel] = actual
    for rel, expected in original["test_sources"].items():
        source = root / rel
        if not source.is_file() or sha(source) != expected:
            raise RuntimeError(f"Selected test source changed in lane2: {rel}")
    artifacts = []
    for item in original["compiled_artifacts"]:
        rel = Path(item["path"]).relative_to(original["patched_root"])
        path = root / rel
        if not path.is_file():
            raise RuntimeError(f"Missing compiled artifact: {path}")
        source_rel = None
        if str(rel).startswith("zookeeper-server/target/classes/"):
            source_rel = Path("zookeeper-server/src/main/java") / rel.relative_to(
                "zookeeper-server/target/classes"
            ).with_suffix(".java")
        elif str(rel).startswith("zookeeper-server/target/test-classes/"):
            source_rel = Path("zookeeper-server/src/test/java") / rel.relative_to(
                "zookeeper-server/target/test-classes"
            ).with_suffix(".java")
        if source_rel is not None and path.stat().st_mtime < (root / source_rel).stat().st_mtime:
            raise RuntimeError(f"Compiled artifact is older than its source: {path}")
        artifacts.append({"path": str(path), "sha256": sha(path)})
    receipt = dict(original)
    receipt.update({
        "patched_root": str(root),
        "patch_file": str(PATCH),
        "patch_sha256": sha(PATCH),
        "modified_files": modified,
        "compiled_artifacts": artifacts,
        "lane": {
            "id": "zookeeper-lane2",
            "port_range": [30072, 32764],
            "port_range_process_count": 8,
            "port_range_process_id": 8,
            "test_data_property": "mallory.test.dir",
            "default_test_data": str(root / "mallory-test-data"),
            "lock_path": "/tmp/mallory-lanes/zookeeper-lane2.lock",
        },
        "generic_test_command": original["generic_test_command"][:-1]
            + ["-Dmallory.test.dir={trial_directory}/test-data", "test"],
    })
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(RECEIPT)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    make_receipt(args.source_root.resolve())
