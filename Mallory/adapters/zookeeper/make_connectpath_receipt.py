#!/usr/bin/env python3
"""Pin the connect-request door overlay to pristine source and compiled bytes."""

import argparse
import json
from pathlib import Path
import subprocess

from make_epochfix_receipt import _diff
from make_requestpath_receipt import sha


HERE = Path(__file__).resolve().parent
BASE = HERE / "zookeeper-3.8.7-requestpath-lane2-overlay.json"
BASE_PATCH = HERE / "zookeeper-3.8.7-requestpath-lane2.patch"
PATCH = HERE / "zookeeper-3.8.7-connectpath-lane2.patch"
RECEIPT = HERE / "zookeeper-3.8.7-connectpath-lane2-overlay.json"
HOOKS = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/MalloryZkHooks.java"
SERVER = "zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java"


def make(root: Path) -> dict:
    prior = json.loads(BASE.read_text(encoding="utf-8"))
    pristine = Path(prior["base_root"])
    prior_root = Path(prior["patched_root"])
    if root == prior_root:
        raise RuntimeError("Connect-path overlay must use a new isolated source root")
    sections = []
    for section in ("diff --git " + item for item in
                    BASE_PATCH.read_text(encoding="utf-8").split("diff --git ")[1:]):
        header = section.splitlines()[0]
        if header.startswith(f"diff --git a/{HOOKS} "):
            sections.append(_diff(pristine / HOOKS, root / HOOKS, HOOKS))
        elif header.startswith(f"diff --git a/{SERVER} "):
            sections.append(_diff(pristine / SERVER, root / SERVER, SERVER))
        else:
            sections.append(section)
    if not sections:
        raise RuntimeError("Request-path patch is empty")
    PATCH.write_text("".join(sections), encoding="utf-8")
    for command in (["patch", "--reverse", "--dry-run", "--batch", "-p1",
                     "-d", str(root), "-i", str(PATCH)],
                    ["patch", "--dry-run", "--batch", "-p1", "-d", str(pristine),
                     "-i", str(PATCH)]):
        run = subprocess.run(command, capture_output=True, text=True)
        if run.returncode:
            raise RuntimeError(f"Patch check failed: {run.stdout}\n{run.stderr}")

    modified = {}
    for rel, previous_sha in prior["modified_files"].items():
        source = root / rel
        if not source.is_file():
            raise RuntimeError(f"Missing patched source: {source}")
        current_sha = sha(source)
        if rel not in (HOOKS, SERVER) and current_sha != previous_sha:
            raise RuntimeError(f"Unrelated patched source changed: {rel}")
        modified[rel] = current_sha
    if any(modified[rel] == prior["modified_files"][rel] for rel in (HOOKS, SERVER)):
        raise RuntimeError("Connect-path source hook missing")

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
            raise RuntimeError(f"Compiled artifact predates source: {binary}")
        compiled.append({"path": str(binary), "sha256": sha(binary)})

    receipt = dict(prior)
    receipt.update({
        "patched_root": str(root), "patch_file": str(PATCH),
        "patch_sha256": sha(PATCH), "modified_files": modified,
        "compiled_artifacts": compiled, "version": "connect-correlated-lane2",
        "connect_path": {
            "client_door": "zookeeper.client.connect.read",
            "source": SERVER,
            "scope": "decoded ConnectRequest through createSession or validateSession",
            "task_handoff": "RequestThrottler to FollowerRequestProcessor to PrepRequestProcessor",
            "proof_limit": "Only exact observed client-connect door, task, REQUEST packet RPC, and region-parent path may justify ZK03",
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
