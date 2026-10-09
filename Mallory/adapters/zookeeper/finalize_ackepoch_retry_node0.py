#!/usr/bin/env python3
"""Pin compiled ZK06 ACKEPOCH retry overlay and prepare one healthy JUnit.

Run only after an admitted test-compile in the isolated source tree. This
command does not start a JVM or change the source tree.
"""

import argparse
import difflib
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, data: str) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def finalize(source_receipt: Path, patch_file: Path, compiled_receipt: Path,
             base_config: Path, config_file: Path) -> None:
    for output in (patch_file, compiled_receipt, config_file):
        if output.exists():
            raise FileExistsError(output)
    source = json.loads(source_receipt.read_text(encoding="utf-8"))
    base = json.loads(Path(source["base_ackepoch_receipt"]).read_text(encoding="utf-8"))
    root = Path(source["patched_root"])
    pristine = Path(source["base_root"])
    if source["status"] != "source_only_pending_compilation_and_healthy_trace":
        raise ValueError("wrong source receipt state")
    if sha(Path(source["base_ackepoch_receipt"])) != source["base_ackepoch_receipt_sha256"]:
        raise ValueError("base ACKEPOCH receipt changed")
    modified = source["modified_files"]
    for relative, expected in modified.items():
        if sha(root / relative) != expected:
            raise ValueError(f"source changed since staging: {relative}")
    compiled = []
    old_root = Path(base["patched_root"])
    for artifact in base["compiled_artifacts"]:
        relative = Path(artifact["path"]).relative_to(old_root)
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        compiled.append({"path": str(path), "sha256": sha(path)})
    lines = []
    for relative in sorted(modified):
        before = pristine / relative
        old = before.read_text(encoding="utf-8").splitlines(keepends=True) if before.is_file() else []
        new = (root / relative).read_text(encoding="utf-8").splitlines(keepends=True)
        if old == new:
            raise ValueError(f"modified file equals pristine: {relative}")
        lines.extend(difflib.unified_diff(
            old, new, fromfile=f"a/{relative}" if before.is_file() else "/dev/null",
            tofile=f"b/{relative}"))
    write_new(patch_file, "".join(lines))
    receipt = {
        "schema_version": 1,
        "version": "ackepoch-following-retry-node0-compiled-v1",
        "base_root": str(pristine),
        "patched_root": str(root),
        "patch_file": str(patch_file),
        "patch_sha256": sha(patch_file),
        "modified_files": modified,
        "compiled_artifacts": compiled,
        "source_staging_receipt": str(source_receipt),
        "source_staging_receipt_sha256": sha(source_receipt),
        "source_rule": source["source_rule"],
        "evidence_limit": "Compiled hooks require a fresh exact-packet healthy trace and a bounded fault retry trace before full admission.",
    }
    write_new(compiled_receipt, json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    config = json.loads(base_config.read_text(encoding="utf-8"))
    if config["case_id"] != "ZOOKEEPER-06" or not config["calibration_only"]:
        raise ValueError("base config is not ZK06 healthy-only")
    config["cwd"] = str(root)
    config["source_overlay_receipt"] = str(compiled_receipt)
    config["source_overlay_receipt_sha256"] = sha(compiled_receipt)
    config["mapping"]["source_root"] = str(root)
    config["mapping"]["compiled_artifact"] = str(root / "zookeeper-server/target/classes")
    config["mapping"]["target_source_sha256"] = sha(root / config["target"]["source_path"])
    config["mapping"]["test_source_sha256"] = sha(root / config["mapping"]["test_source_path"])
    config["mapping"]["status"] = "compiled_retry_overlay_pending_fresh_healthy_seed"
    config["mapping"]["healthy_seed_verified"] = False
    config["mapping"]["node_identity_binding_verified"] = False
    target_class = root / config["mapping"]["target_class_relative"]
    config["mapping"]["compiled_class_sha256"] = sha(target_class)
    config["expected_target_class_sha256"] = sha(target_class)
    config["budget"] = {
        "trials": 1, "seconds": 300, "max_faults_per_trial": 1,
        "trial_timeout_seconds": 180,
        "trial_timeout_basis": "existing_quorum_restart_healthy_ceiling",
    }
    config["auto_promote_if_healthy"] = False
    write_new(config_file, json.dumps(config, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source_receipt", "patch_file", "compiled_receipt",
                 "base_config", "config_file"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    finalize(*(getattr(args, name).resolve() for name in
               ("source_receipt", "patch_file", "compiled_receipt",
                "base_config", "config_file")))
