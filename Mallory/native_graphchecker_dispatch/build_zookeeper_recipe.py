"""Pin a target-free ZooKeeper native profile for the preparation queue.

The recipe refers to one shared adapter and transport gate.  The dispatcher
supplies each original JUnit and target from the pinned 102-case inventory.
No observed I/O site or fault door is selected here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from Mallory.instrumentation.graphchecker_port.native_original_weave import (
    class_tree_digest, file_tree_digest,
)
from . import zookeeper_native_adapter as zk
from .preparation import _atomic, _audit_zookeeper_recipe_pins, _object, _sha


def _pin(path: str, *, classes: bool = False) -> str:
    value = Path(path)
    if not value.is_absolute() or value.is_symlink() or not value.exists():
        raise ValueError(f"unpinnable ZooKeeper recipe input: {value}")
    if value.is_file():
        if classes:
            raise ValueError(f"expected class tree: {value}")
        return _sha(value)
    return class_tree_digest(value) if classes else file_tree_digest(value)


def build(profile_file: Path, inventory: Path, output: Path,
          timeout_seconds: int = 7200) -> dict:
    if output.exists() or not output.is_absolute() or output.parent.is_symlink():
        raise ValueError("ZooKeeper recipe output must be a fresh absolute file")
    profile = _object(profile_file)
    if profile.get("mode") != zk.PROFILE_MODE:
        raise ValueError("expected shared ZooKeeper native profile")
    gate = _object(Path(profile["protocol_gate"]))
    if not zk._reusable_gate_claims(gate):
        raise ValueError("ZooKeeper transport gate is not accepted")
    here = Path(__file__).resolve().parent
    file_paths = [
        Path(sys.executable).resolve(strict=True),
        profile_file, Path(profile["protocol_gate"]), Path(profile["java"]),
        Path(gate["session_reader_receipt_path"]),
        Path(gate["session_reader_verifier_source_path"]),
        Path(gate["healthy_stdout_path"]),
        Path(gate["healthy_trace_manifest_path"]),
        here / "zookeeper_native_adapter.py",
        here / "run_zookeeper_native_adapter.py",
        here / "preparation.py", here / "checklist.py",
        here / "build_zookeeper_protocol_gate.py",
        here / "build_zookeeper_recipe.py",
        here / "NativeZooKeeperCombinedPostWeave.java",
        here / "NativeZooKeeperSessionVerifier.java",
    ]
    if profile.get("runner_source"):
        file_paths.append(Path(profile["runner_source"]))
    if profile.get("post_weave_source"):
        file_paths.append(Path(profile["post_weave_source"]))
    source_paths = [Path(profile["source_root"]),
                    Path(gate["session_dir_path"])]
    class_paths = [Path(profile["source_classes"]),
                   Path(gate["postweave_class_tree_path"])]
    mapping_paths = [Path(profile["communication_mapping"]),
                     Path(gate["static_map_path"])]
    cp_paths = [Path(value) for key in (
        "analysis_classpath", "scope_planner_classpath", "runtime_classpath",
        "runner_classpath", "post_weave_classpath")
        for value in profile[key]]
    cp_paths += [Path(gate["adapter_build_path"]),
                 Path(gate["session_reader_verifier_artifact_path"])]
    # A class tree is pinned with class_tree_digest; no conflicting generic
    # directory digest is inserted in classpath_pins for the same path.
    class_names = {str(path) for path in class_paths}
    recipe = {
        "argv": [str(Path(sys.executable).resolve(strict=True)),
                 str(here / "run_zookeeper_native_adapter.py"),
                 str(profile_file), "{request}", "{output}"],
        "pins": {str(path): _pin(str(path)) for path in file_paths},
        "source_tree_pins": {str(path): _pin(str(path))
                             for path in source_paths},
        "class_tree_pins": {str(path): _pin(str(path), classes=True)
                            for path in class_paths},
        "mapping_pins": {str(path): _pin(str(path))
                         for path in mapping_paths},
        "classpath_pins": {str(path): _pin(str(path))
                           for path in cp_paths if str(path) not in class_names},
        "timeout_seconds": timeout_seconds,
    }
    _audit_zookeeper_recipe_pins(recipe)
    document = {"schema_version": 1, "inventory_sha256": _sha(inventory),
                "systems": {"zookeeper": recipe}}
    _atomic(output, document)
    return document


def main() -> None:
    if len(sys.argv) not in (4, 5):
        raise SystemExit("usage: python -m Mallory.native_graphchecker_dispatch."
                         "build_zookeeper_recipe PROFILE INVENTORY OUTPUT "
                         "[TIMEOUT_SECONDS]")
    timeout = int(sys.argv[4]) if len(sys.argv) == 5 else 7200
    build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), timeout)


if __name__ == "__main__":
    main()
