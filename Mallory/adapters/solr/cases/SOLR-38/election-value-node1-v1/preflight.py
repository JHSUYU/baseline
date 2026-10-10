#!/usr/bin/env python3
"""Static, JVM-free admission check for the SOLR-38 value diagnostic."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
BASE = HERE.parent / "election-field-healthy-node1-v1"
MANIFEST = HERE / "source-manifest.json"
OUT = ROOT / "data/mallory/solr38_election_value_healthy_v1_node1/SOLR-38/healthy"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> dict:
    spec = importlib.util.spec_from_file_location("solr38_node1_base", BASE / "preflight.py")
    if spec is None or spec.loader is None:
        raise ValueError("pinned base preflight unavailable")
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base_result = base.main()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("case_id") != "SOLR-38" or manifest.get("mode") != "healthy_value_diagnostic":
        raise ValueError("wrong diagnostic manifest")
    for relative, digest in manifest["source_sha256"].items():
        path = HERE / relative
        if not path.is_file() or sha(path) != digest:
            raise ValueError(f"diagnostic source changed: {relative}")
    transformer = (HERE / "adapter/src/main/java/edu/uva/liftlab/mallory/solr/"
                   "SolrTransformer.java").read_text(encoding="utf-8")
    hooks = (HERE / "adapter/src/main/java/edu/uva/liftlab/mallory/solr/"
             "SolrHooks.java").read_text(encoding="utf-8")
    if not all(fragment in transformer for fragment in (
            'CLOUD_DESCRIPTOR.equals(className)',
            '"(Z)V".equals(descriptor)) return leaderValue(method, true)',
            '"()Z".equals(descriptor)) return leaderValue(method, false)',
            'Opcodes.DUP', '"leaderRead"', '"leaderWrite"')):
        raise ValueError("exact value capture hook absent")
    if not all(fragment in hooks for fragment in (
            'Probe.stateWrite(descriptor, "solr38:isLeader=" + value',
            'Probe.stateRead(descriptor, "solr38:isLeader=" + value')):
        raise ValueError("structured value event absent")
    return {"case_id": "SOLR-38", "mode": "healthy", "host": "node1",
            "base_preflight": base_result["case_id"],
            "source_manifest_sha256": sha(MANIFEST),
            "runner_sha256": sha(HERE / "run_healthy.py"),
            "intended_output": str(OUT), "go": False,
            "full_promotion_authorized": False}


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
