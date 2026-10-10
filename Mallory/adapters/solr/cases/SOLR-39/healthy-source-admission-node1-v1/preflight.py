#!/usr/bin/env python3
"""Verify the immutable SOLR-39 healthy package on node1 without a JVM."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "healthy-source-admission-v2"
PINS = {
    "config.json": "51165a762fb089a1848e1b9b411adae325f2644dd08976c6ce0d74adcc56579f",
    "sites.json": "3c9ae0c6cb109c777afbe367c9fae7a6dbb65ecd32276b2660e11b22f732f313",
    "manifest.json": "9cd93a4c5270436a7dd278ffdb9f0ed4a0a59ead0312a54007a62c357600a863",
    "preflight.py": "b18575c23cbe107abce0a65c3f7b6e66884ba24b8e72a4b3e60fc793034da77a",
    "run_healthy.py": "191f7549faeab827cb298e930d06f8108ced698d080c2c54a7a9684fed138d9f",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> dict:
    for name, expected in PINS.items():
        path = BASE / name
        if not path.is_file() or sha(path) != expected:
            raise ValueError(f"SOLR-39 base package pin differs: {name}")
    spec = importlib.util.spec_from_file_location("solr39_base_preflight", BASE / "preflight.py")
    if spec is None or spec.loader is None:
        raise ValueError("SOLR-39 base preflight unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.main()
    if result.get("status") != "offline_preflight_passed_healthy_only":
        raise ValueError("SOLR-39 base preflight did not admit healthy observation")
    result["host_port"] = "node1"
    result["base_package_manifest_sha256"] = PINS["manifest.json"]
    return result


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
