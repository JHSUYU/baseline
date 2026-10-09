#!/usr/bin/env python3
"""Pin a fresh ZK11 healthy run to a cloned source and approved scoped-root agent."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(base_config: Path, overlay_receipt: Path, agent_jar: Path,
            core_release: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    base = json.loads(base_config.read_text(encoding="utf-8"))
    receipt = json.loads(overlay_receipt.read_text(encoding="utf-8"))
    if base["case_id"] != "ZOOKEEPER-11" or not agent_jar.is_file():
        raise ValueError("expected ZK11 and an approved, built agent JAR")
    if not (core_release / "manifest.json").is_file():
        raise ValueError("immutable core release manifest is absent")
    manifest = json.loads((core_release / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("release_id") != core_release.name:
        raise ValueError("core release ID does not match its manifest")
    root = Path(receipt["patched_root"])
    if not root.is_dir() or not receipt.get("compiled_artifacts"):
        raise ValueError("overlay receipt lacks a compiled source root")
    for relative, digest in receipt["modified_files"].items():
        if sha(root / relative) != digest:
            raise ValueError(f"overlay source hash mismatch: {relative}")
    artifacts = {}
    for artifact in receipt["compiled_artifacts"]:
        path = Path(artifact["path"])
        if not path.is_relative_to(root) or sha(path) != artifact["sha256"]:
            raise ValueError(f"overlay class hash mismatch: {path}")
        artifacts[path] = artifact["sha256"]
    base_mapping = base["mapping"]
    target_class = root / base_mapping["target_class_relative"]
    if artifacts.get(target_class) != base_mapping["compiled_class_sha256"]:
        raise ValueError("target class is not the attested compiled class")
    for name in ("target_source", "test_source"):
        relative = base_mapping.get(f"{name}_path") or base["target"].get("source_path")
        expected = base_mapping.get(f"{name}_sha256")
        if relative and expected and sha(root / relative) != expected:
            raise ValueError(f"{name} hash mismatch")
    old_site = Path(base["site_file"])
    site = output.with_suffix(".sites.json")
    if site.exists():
        raise FileExistsError(site)
    shutil.copyfile(old_site, site)
    config = dict(base)
    config.update(cwd=str(root), site_file=str(site.resolve()),
                  agent_jar=str(agent_jar.resolve()), core_release=str(core_release.resolve()),
                  source_overlay_receipt=str(overlay_receipt.resolve()),
                  source_overlay_receipt_sha256=sha(overlay_receipt),
                  calibration_only=True, auto_promote_if_healthy=False,
                  allow_local_timeline_doors=True,
                  reject_coarse_roots=True, require_event_time_paths=True)
    mapping = dict(base["mapping"])
    mapping.update(source_root=str(root), compiled_artifact=str(root / "zookeeper-server/target/classes"),
                   status="scoped_root_target_pending_fresh_healthy_seed",
                   healthy_seed_verified=False, agent_sha256=sha(agent_jar))
    mapping.pop("verified_healthy_probe", None)
    config["mapping"] = mapping
    config["expected_target_class_sha256"] = sha(
        root / mapping["target_class_relative"])
    config["runtime_artifacts"] = [
        {"path": str(agent_jar.resolve()), "sha256": sha(agent_jar)},
        {"path": str(site.resolve()), "sha256": sha(site)},
    ]
    output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base_config", "overlay_receipt", "agent_jar", "core_release", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    prepare(*(getattr(args, name).resolve() for name in
              ("base_config", "overlay_receipt", "agent_jar", "core_release", "output")))
