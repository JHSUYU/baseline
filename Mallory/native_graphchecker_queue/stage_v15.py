"""Stage v15 control files without modifying the live v14 queue or results."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import tempfile
from contextlib import ExitStack
from pathlib import Path

from .inventory_epoch import (BASE_SHA256, _sha, freeze_epoch_receipt,
                              load_queue_inventory)


def stage_v15(v14_root: Path, v15_root: Path) -> dict:
    if (not v15_root.is_absolute() or
            not v15_root.name.startswith("native-102-queue-v15") or
            v15_root.exists() or v14_root.resolve() == v15_root.resolve()):
        raise ValueError("v15 staging requires a fresh isolated v15 root")
    base = (v14_root / "python-snapshot-bind-v14" / "Mallory" /
            "cases/inventory.json")
    state = v14_root / "state"
    pilot = state / ".native-queue/pilot-ZOOKEEPER-07.json"
    ownership = v14_root / "config/ownership.json"
    isolation = v14_root / "evidence/isolation.json"
    for path in (pilot, ownership, isolation):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"v14 control file is unavailable: {path}")
    with ExitStack() as locks:
        # A worker holds a shared host lease for its whole run; promotion has
        # its own lock. Acquiring all of them exclusively freezes the v14 set.
        for host in ("node0", "node1", "node2"):
            path = state / f".host-{host}.lock"
            handle = locks.enter_context(path.open("a+"))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("v14 worker must stop before v15 handoff") from error
        promotion = locks.enter_context((state / ".native-queue" /
                                         "promotion.lock").open("a+"))
        try:
            fcntl.flock(promotion, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("v14 promotion must stop before v15 handoff") from error
        results_lock = locks.enter_context((v14_root / "results" /
                                            ".native-results.lock").open("a+"))
        fcntl.flock(results_lock, fcntl.LOCK_EX)
        controllers = state / ".native-queue" / "controllers"
        for path in controllers.glob("*.json"):
            if json.loads(path.read_text()).get("status") == "running":
                raise ValueError("v14 controller must stop before v15 handoff")
        if ((v14_root / "config/HDFS-40.json").exists() or
                (state / ".native-queue/completions/HDFS-40.json").exists()):
            raise ValueError("HDFS-40 already has a v14 binding or completion")
        frozen = freeze_epoch_receipt(
            base, state, v14_root / "results/native-102-results.json")
        v15_root.parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=".native-v15-stage-",
                                        dir=v15_root.parent))
        try:
            epoch_receipt = scratch / "inventory-epoch-receipt.json"
            epoch_receipt.write_text(json.dumps(frozen, sort_keys=True,
                                                indent=2) + "\n")
            epoch_sha = _sha(epoch_receipt)
            _, _, epoch = load_queue_inventory(base, state, epoch_receipt,
                                               epoch_sha)
            copied = {}
            def copy(source: Path, relative: str) -> None:
                destination = scratch / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                if _sha(source) != _sha(destination):
                    raise ValueError(f"v14 control changed during copy: {source}")
                copied[relative] = _sha(destination)
            copy(base, "python-snapshot-bind-v4/Mallory/cases/inventory.json")
            for path in sorted((v14_root / "config").glob("*.json")):
                if path.is_symlink():
                    raise ValueError(f"v14 config is a symlink: {path}")
                copy(path, f"config/{path.name}")
            copy(isolation, "evidence/isolation.json")
            copy(pilot, "pilot-v15.json")
            if copied["python-snapshot-bind-v4/Mallory/cases/inventory.json"] != BASE_SHA256:
                raise ValueError("v15 copied the wrong base inventory")
            receipt = {"schema_version": 1,
                       "status": "staged_no_junit_or_fault_trial",
                       "v14_root": str(v14_root),
                       "v15_root": str(v15_root),
                       "shared_state_root": str(state),
                       "inventory_epoch": epoch,
                       "copied_control_sha256": copied}
            (scratch / "handoff-receipt.json").write_text(
                json.dumps(receipt, sort_keys=True, indent=2) + "\n")
            os.rename(scratch, v15_root)
            return receipt
        finally:
            if scratch.exists():
                shutil.rmtree(scratch)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v14-root", type=Path, required=True)
    parser.add_argument("--v15-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage_v15(args.v14_root, args.v15_root),
                     sort_keys=True))


if __name__ == "__main__":
    main()
