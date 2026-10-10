#!/usr/bin/env python3
"""Attest the unchanged SOLR-38 election probe on independent node1."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "election-field-healthy-node2-v1"
PINS = {
    "config-healthy-node2.json": "5cbb30e7a4cfb98043547825548049f554546cde2982151cf1a304659b2c4a71",
    "sites.json": "8848d97a862963b6aa925287c0f83d135b0aad056258e96ed0ccf660d9490d35",
    "sha-manifest.json": "c8785576c67254e2968cfee471a31027d62b598a9b2872acb30146b55b257822",
    "run_campaign.py": "d6d44f47824043c68449889b20da2ad2723a4b7865481dd6e2f4db150fc393a3",
    "static_preflight.py": "b2d3450390978d3268fa60b9ed7f214e3aaf8d3512d3b046967ce38bfec6e099",
    "admission-request.json": "708708d316be772b88a425e767e6bb809c231335eb03ad51af63a14857dfdb04",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> dict:
    for name, expected in PINS.items():
        path = BASE / name
        if not path.is_file() or sha(path) != expected:
            raise ValueError(f"SOLR-38 base package pin differs: {name}")
    spec = importlib.util.spec_from_file_location("solr38_base_runner", BASE / "run_campaign.py")
    if spec is None or spec.loader is None:
        raise ValueError("SOLR-38 base preflight unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.preflight()
    if result.get("case_id") != "SOLR-38" or result.get("mode") != "healthy":
        raise ValueError("SOLR-38 base preflight did not pass")
    result["host_port"] = "node1"
    result["base_manifest_sha256"] = PINS["sha-manifest.json"]
    result["base_runner_sha256"] = result["runner_sha256"]
    result["runner_sha256"] = sha(HERE / "run_healthy.py")
    result["intended_output"] = str(
        HERE.parents[5] / "data/mallory/solr38_election_field_healthy_v1_node1/SOLR-38/healthy"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
