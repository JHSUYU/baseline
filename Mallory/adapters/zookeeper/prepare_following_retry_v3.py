#!/usr/bin/env python3
"""Pin a fresh ZK07 calibration to the separately compiled retry-v3 overlay."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(base_config: Path, receipt_path: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    config = json.loads(base_config.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    root = Path(receipt["patched_root"])
    if config["case_id"] != "ZOOKEEPER-07" or not root.is_dir():
        raise ValueError("expected compiled ZK07 retry-v3 overlay")
    old_site = Path(config["site_file"])
    new_site = output.with_suffix(".sites.json")
    if new_site.exists():
        raise FileExistsError(new_site)
    shutil.copyfile(old_site, new_site)
    config.update(cwd=str(root), site_file=str(new_site.resolve()),
                  source_overlay_receipt=str(receipt_path.resolve()),
                  source_overlay_receipt_sha256=sha(receipt_path),
                  calibration_only=True, auto_promote_if_healthy=False)
    mapping = config["mapping"]
    mapping.update(source_root=str(root), compiled_artifact=str(root / "zookeeper-server/target/classes"),
                   status="compiled_retry_v3_overlay_pending_fresh_healthy_seed",
                   node_identity_binding_verified=False, healthy_seed_verified=False)
    mapping.pop("verified_healthy_probe", None)
    relative = Path(mapping["target_class_relative"])
    config["expected_target_class_sha256"] = sha(root / relative)
    for artifact in config["runtime_artifacts"]:
        if artifact["path"] == str(old_site):
            artifact.update(path=str(new_site.resolve()), sha256=sha(new_site))
            break
    else:
        new_site.unlink()
        raise ValueError("site artifact missing from base config")
    output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_config", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(*(path.resolve() for path in (args.base_config, args.receipt, args.output)))
