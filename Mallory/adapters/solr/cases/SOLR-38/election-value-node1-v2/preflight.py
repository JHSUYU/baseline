#!/usr/bin/env python3
"""JVM-free admission check for the isolated SOLR-38 value diagnostic v2."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import build_adapter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V1 = HERE.parent / "election-value-node1-v1"
MANIFEST = HERE / "source-manifest.json"
OUT = ROOT / "data/mallory/solr38_election_value_healthy_v2_node1/SOLR-38/healthy"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> dict:
    spec = importlib.util.spec_from_file_location("solr38_value_v1_preflight", V1 / "preflight.py")
    if spec is None or spec.loader is None:
        raise ValueError("pinned v1 diagnostic preflight missing")
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    previous = old.main()
    if previous.get("case_id") != "SOLR-38" or previous.get("host") != "node1":
        raise ValueError("pinned v1 diagnostic differs")
    built = build_adapter.preflight()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for relative, digest in manifest["source_sha256"].items():
        path = HERE / relative
        if not path.is_file() or sha(path) != digest:
            raise ValueError(f"SOLR-38 v2 source changed: {relative}")
    runner = (HERE / "run_pilot.py").read_text(encoding="utf-8")
    healthy = (HERE / "run_healthy.py").read_text(encoding="utf-8")
    if not all(token in runner for token in (
            "runner.AGENT = AGENT", "runner.ADAPTER = ADAPTER",
            'os.environ["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)',
            'os.environ["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)',
            "verify_campaign_context(args.output.resolve()")):
        raise ValueError("direct JUnit runner lost pinned agent/adapter override")
    if ("build_adapter.build()" not in healthy or
            'subprocess.run(["mvn"' in healthy or
            'config["env"]["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)' not in healthy):
        raise ValueError("healthy runner still depends on Maven or lost adapter pin")
    return {"case_id": "SOLR-38", "host": "node1", "mode": "healthy",
            "build_tool": built["build_tool"], "maven_required": False,
            "source_manifest_sha256": sha(MANIFEST),
            "runner_sha256": sha(HERE / "run_healthy.py"),
            "base_adapter_sha256": built["base_adapter_sha256"],
            "agent_sha256": built["agent_sha256"],
            "intended_output": str(OUT), "go": False,
            "full_promotion_authorized": False}


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
