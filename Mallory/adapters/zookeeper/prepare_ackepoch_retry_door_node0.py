#!/usr/bin/env python3
"""Stage the precise follower ACKEPOCH write door in a separate source tree."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from install_ackepoch_retry_door import SITE, install


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(base_receipt: Path, destination: Path, receipt_path: Path) -> None:
    if destination.exists() or receipt_path.exists():
        raise FileExistsError("v2 source and receipt must be fresh")
    base = json.loads(base_receipt.read_text(encoding="utf-8"))
    old = Path(base["patched_root"])
    if base["status"] != "source_only_pending_compilation_and_healthy_trace":
        raise ValueError("v1 ACKEPOCH retry source is not a staged overlay")
    for name, expected in base["modified_files"].items():
        if sha(old / name) != expected:
            raise ValueError(f"v1 source hash mismatch: {name}")
    shutil.copytree(old, destination, symlinks=True)
    try:
        install(destination)
        modified = {name: sha(destination / name) for name in
                    sorted(base["modified_files"])}
        learner_name = ("zookeeper-server/src/main/java/org/apache/"
                        "zookeeper/server/quorum/Learner.java")
        hook_name = ("zookeeper-server/src/main/java/org/apache/"
                     "zookeeper/server/quorum/MalloryZkHooks.java")
        if (modified[learner_name] == base["modified_files"][learner_name]
                or modified[hook_name] == base["modified_files"][hook_name]):
            raise ValueError("precise door did not modify Learner and hook")
        for name in modified:
            if name not in (learner_name, hook_name) and \
                    modified[name] != base["modified_files"][name]:
                raise ValueError(f"unrelated source changed: {name}")
        receipt = dict(base)
        receipt.update(
            version="ackepoch-following-retry-exact-door-node0-source-v2",
            patched_root=str(destination), modified_files=modified,
            previous_source_receipt=str(base_receipt),
            previous_source_receipt_sha256=sha(base_receipt),
            precise_door_site=SITE,
            precise_door_installer=str(Path(__file__).with_name(
                "install_ackepoch_retry_door.py").resolve()),
            precise_door_installer_sha256=sha(Path(__file__).with_name(
                "install_ackepoch_retry_door.py")),
            source_rule=(
                "The ACKEPOCH door is after a possible setAcceptedEpoch(newEpoch) "
                "and immediately before writePacket(ackNewEpoch,true). A thrown "
                "IOException is caught by Follower.followLeader; an exact "
                "same-peer/thread/epoch retry may send a new ACKEPOCH packet."
            ),
            evidence_limit=(
                "Source-only staging. Require compiled bytecode and fresh "
                "healthy exact packet path; pilot only this precise door, "
                "then require observed retry token and postfault target."
            ),
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
    except BaseException:
        shutil.rmtree(destination)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_receipt", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    prepare(args.base_receipt.resolve(), args.destination.resolve(),
            args.receipt.resolve())
