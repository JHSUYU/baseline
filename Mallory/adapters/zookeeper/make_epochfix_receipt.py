#!/usr/bin/env python3
"""Attest the versioned ZooKeeper tracker-epoch overlay and compiled outputs."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
BASE = HERE / "zookeeper-3.8.7-lane2-overlay.json"
BASE_PATCH = HERE / "zookeeper-3.8.7-lane2.patch"
PATCH = HERE / "zookeeper-3.8.7-epochfix-lane2.patch"
RECEIPT = HERE / "zookeeper-3.8.7-epochfix-lane2-overlay.json"
TRACKER = "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java"
HOOKS = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/MalloryZkHooks.java"
POM = "zookeeper-server/pom.xml"
SERVER = "zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java"
READ_ONLY = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _diff(base: Path, changed: Path, rel: str) -> str:
    process = subprocess.run(
        ["diff", "-u", "--label", f"a/{rel}" if base.exists() else "/dev/null",
         "--label", f"b/{rel}", str(base if base.exists() else Path("/dev/null")), str(changed)],
        capture_output=True, text=True,
    )
    if process.returncode != 1:
        raise RuntimeError(f"No source delta for {rel}: {process.stderr}")
    return f"diff --git a/{rel} b/{rel}\n" + process.stdout


def make(root: Path, *, patch_only: bool = False) -> dict:
    prior = json.loads(BASE.read_text(encoding="utf-8"))
    pristine = Path(prior["base_root"])
    prior_root = Path(prior["patched_root"])
    if root == prior_root:
        raise RuntimeError("Epoch-fix overlay must not overwrite the pinned lane2 source")
    sections = []
    patch = BASE_PATCH.read_text(encoding="utf-8")
    for section in ("diff --git " + item for item in patch.split("diff --git ")[1:]):
        header = section.splitlines()[0]
        if header.startswith(f"diff --git a/{POM} "):
            sections.append(_diff(pristine / POM, root / POM, POM))
        elif header.startswith(f"diff --git a/{TRACKER} "):
            sections.append(_diff(pristine / TRACKER, root / TRACKER, TRACKER))
        elif header.startswith(f"diff --git a/{HOOKS} "):
            sections.append(_diff(pristine / HOOKS, root / HOOKS, HOOKS))
        else:
            sections.append(section)
    sections.append(_diff(pristine / SERVER, root / SERVER, SERVER))
    sections.append(_diff(pristine / READ_ONLY, root / READ_ONLY, READ_ONLY))
    PATCH.write_text("".join(sections), encoding="utf-8")
    for command, cwd in ((["patch", "--reverse", "--dry-run", "--batch", "-p1",
                           "-d", str(root), "-i", str(PATCH)], root),
                         (["patch", "--dry-run", "--batch", "-p1", "-d", str(pristine),
                           "-i", str(PATCH)], root)):
        process = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
        if process.returncode:
            raise RuntimeError(f"Patch check failed: {process.stdout}\n{process.stderr}")
    if patch_only:
        return {"patch_sha256": sha(PATCH), "compiled_artifacts": []}

    modified = {}
    for rel, old_sha in prior["modified_files"].items():
        source = root / rel
        if not source.is_file():
            raise RuntimeError(f"Missing patched source: {source}")
        new_sha = sha(source)
        if rel not in (TRACKER, HOOKS, POM) and old_sha != new_sha:
            raise RuntimeError(f"Unrelated source changed: {rel}")
        if rel in (TRACKER, HOOKS) and old_sha == new_sha:
            raise RuntimeError(f"Epoch-fix source did not change: {rel}")
        modified[rel] = new_sha
    modified[SERVER] = sha(root / SERVER)
    modified[READ_ONLY] = sha(root / READ_ONLY)
    compiled = []
    for item in prior["compiled_artifacts"]:
        rel = Path(item["path"]).relative_to(prior_root)
        binary = root / rel
        if not binary.is_file():
            raise RuntimeError(f"Missing compiled artifact: {binary}")
        if str(rel).startswith("zookeeper-server/target/classes/"):
            source_rel = (Path("zookeeper-server/src/main/java") /
                          rel.relative_to("zookeeper-server/target/classes")).with_suffix(".java")
        elif str(rel).startswith("zookeeper-server/target/test-classes/"):
            source_rel = (Path("zookeeper-server/src/test/java") /
                          rel.relative_to("zookeeper-server/target/test-classes")).with_suffix(".java")
        else:
            source_rel = None
        if source_rel is not None and (root / source_rel).is_file() and \
                binary.stat().st_mtime < (root / source_rel).stat().st_mtime:
            raise RuntimeError(f"Compiled artifact predates patched source: {binary}")
        compiled.append({"path": str(binary), "sha256": sha(binary)})
    receipt = dict(prior)
    receipt.update({"patched_root": str(root), "patch_file": str(PATCH),
                    "patch_sha256": sha(PATCH), "modified_files": modified,
                    "compiled_artifacts": compiled,
        "epoch_fix": {"kind": "receiver_alias_registration_and_client_request_scope",
                      "registration_sources": [TRACKER, READ_ONLY],
                      "probe_method": "Probe.registerNode",
                      "expected_lifecycle": "QuorumPeer.run/startPeer",
                      "client_request_source": SERVER,
                      "client_io_door": "zookeeper.client.request.read",
                      "quorum_packet_limit": "sid-only packet wrappers can use the latest epoch when two live ensembles reuse a server ID; such unscoped quorum edges are not accepted as ZK02 causal-path proof"}})
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--patch-only", action="store_true")
    args = parser.parse_args()
    result = make(args.source_root.resolve(), patch_only=args.patch_only)
    print(json.dumps({"receipt": str(RECEIPT), "patch_sha256": result["patch_sha256"],
                      "compiled_artifacts": len(result["compiled_artifacts"])}))
