#!/usr/bin/env python3
"""Attest the request-correlated ZooKeeper overlay against pristine source."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from make_epochfix_receipt import _diff


HERE = Path(__file__).resolve().parent
BASE = HERE / "zookeeper-3.8.7-epochfix-lane2-overlay.json"
BASE_PATCH = HERE / "zookeeper-3.8.7-epochfix-lane2.patch"
PATCH = HERE / "zookeeper-3.8.7-requestpath-lane2.patch"
RECEIPT = HERE / "zookeeper-3.8.7-requestpath-lane2-overlay.json"
HOOKS = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/MalloryZkHooks.java"
FOLLOWER = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/FollowerRequestProcessor.java"
HANDLER = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/LearnerHandler.java"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make(root: Path) -> dict:
    prior = json.loads(BASE.read_text(encoding="utf-8"))
    pristine = Path(prior["base_root"])
    prior_root = Path(prior["patched_root"])
    if root == prior_root:
        raise RuntimeError("Request-path overlay must not overwrite the epoch-fix source")
    sections = []
    patch = BASE_PATCH.read_text(encoding="utf-8")
    for section in ("diff --git " + item for item in patch.split("diff --git ")[1:]):
        header = section.splitlines()[0]
        if header.startswith(f"diff --git a/{HOOKS} "):
            sections.append(_diff(pristine / HOOKS, root / HOOKS, HOOKS))
        elif header.startswith(f"diff --git a/{HANDLER} "):
            sections.append(_diff(pristine / HANDLER, root / HANDLER, HANDLER))
        else:
            sections.append(section)
    sections.append(_diff(pristine / FOLLOWER, root / FOLLOWER, FOLLOWER))
    PATCH.write_text("".join(sections), encoding="utf-8")
    for args in (["patch", "--reverse", "--dry-run", "--batch", "-p1",
                  "-d", str(root), "-i", str(PATCH)],
                 ["patch", "--dry-run", "--batch", "-p1", "-d", str(pristine),
                  "-i", str(PATCH)]):
        run = subprocess.run(args, capture_output=True, text=True)
        if run.returncode:
            raise RuntimeError(f"Patch check failed: {run.stdout}\n{run.stderr}")

    modified = dict(prior["modified_files"])
    for rel in modified:
        source = root / rel
        if not source.is_file():
            raise RuntimeError(f"Missing patched source: {source}")
        new = sha(source)
        if rel not in (HOOKS, HANDLER) and new != modified[rel]:
            raise RuntimeError(f"Unrelated patched source changed: {rel}")
        modified[rel] = new
    modified[FOLLOWER] = sha(root / FOLLOWER)
    modified[HANDLER] = sha(root / HANDLER)

    compiled = []
    previous_paths = {Path(item["path"]).relative_to(prior_root) for item in prior["compiled_artifacts"]}
    additional_paths = {
        Path("zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/FollowerRequestProcessor.class"),
    }
    for rel in sorted(previous_paths | additional_paths):
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
    receipt.update({
        "patched_root": str(root), "patch_file": str(PATCH), "patch_sha256": sha(PATCH),
        "modified_files": modified, "compiled_artifacts": compiled,
        "version": "request-correlated-lane2",
        "request_path": {
            "client_door": "zookeeper.client.request.read",
            "queue_sources": ["RequestThrottler", "FollowerRequestProcessor",
                              "PrepRequestProcessor"],
            "quorum_request_sources": [FOLLOWER, HANDLER, HOOKS],
            "packet_identity": "actual TCP direction and ordinal, QuorumPacket type, and SHA-256 of request bytes",
            "receiver_join": "the same QuorumPacket object holds its read correlation until LearnerHandler submits the request",
            "required_probe_api": "Probe.withCausalContext(String)",
            "proof_limit": "only a fully observed client-door, task, quorum RPC, region-parent path may justify ZK02; root-context cooccurrence is insufficient",
        },
    })
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    row = make(args.source_root.resolve())
    print(json.dumps({"receipt": str(RECEIPT), "patch_sha256": row["patch_sha256"],
                      "compiled_artifacts": len(row["compiled_artifacts"])}))
