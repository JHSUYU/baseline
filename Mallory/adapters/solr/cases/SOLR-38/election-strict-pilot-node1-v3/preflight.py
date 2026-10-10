#!/usr/bin/env python3
"""JVM-free preflight for the bounded SOLR-38 strict-path pilot."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import config_v3
import graph_overlay

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "source-manifest.json"
REFERENCE = HERE / "reference-events.jsonl.gz"


def main() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name, expected in manifest["package_sha256"].items():
        path = HERE / name
        if not path.is_file() or config_v3.sha(path) != expected:
            raise ValueError(f"v3 package changed: {name}")
    for name, expected in manifest["dependency_sha256"].items():
        path = config_v3.ROOT / name
        if not path.is_file() or config_v3.sha(path) != expected:
            raise ValueError(f"pinned dependency changed: {name}")
    if config_v3.sha(REFERENCE) != graph_overlay.unique_writer.SEALED_TRACE_SHA256:
        raise ValueError("sealed v2 reference trace changed")
    if config_v3.sha(config_v3.ADAPTER) != graph_overlay.unique_writer.ADAPTER_SHA256:
        raise ValueError("v3 adapter differs from sealed v2 adapter")
    graph_overlay.unique_writer.verify_source(graph_overlay.SOURCE)
    sites = json.loads((HERE / "sites.json").read_text(encoding="utf-8"))
    if (len(sites["doors"]) != 1 or sites["doors"][0]["line"] != 396 or
            sites["doors"][0]["exception_class"] != graph_overlay.unique_writer.EXCEPTION):
        raise ValueError("fault site is not the exact typed election I/O door")
    config = config_v3.generate()
    from Mallory.core import campaign, feedback
    campaign.validate_config(config)
    if (config["case_id"] != "SOLR-38" or config["cluster_test"] !=
            "org.apache.solr.client.solrj.impl.CloudHttp2SolrClientTest#testAliasHandling"
            or config["budget"] != {"trials": 4, "seconds": 1800,
                                   "trial_timeout_seconds": 480, "max_faults_per_trial": 1}
            or not config["require_event_time_paths"] or
            config["explore_outside_closure"] or not config["auto_promote_if_healthy"]):
        raise ValueError("strict bounded pilot policy differs")
    compressed = REFERENCE.read_bytes()
    import hashlib
    if hashlib.sha256(compressed).hexdigest() != graph_overlay.unique_writer.SEALED_TRACE_SHA256:
        raise ValueError("sealed trace differs")
    events = tuple(json.loads(line) for line in gzip.decompress(compressed).splitlines())
    graph_overlay.install()
    from Mallory.core.events import Trace
    base = json.loads((HERE.parent / "election-field-healthy-node2-v1/"
                       "config-healthy-node2.json").read_text(encoding="utf-8"))
    result = feedback.analyze(Trace(events), base["target"], [],
                              return_code=0, timed_out=False,
                              reject_coarse_roots=True, require_event_time_paths=True)
    in_closure = [door for door in result["doors"] if door["in_closure"]
                  and door["site"].startswith(graph_overlay.unique_writer.DOOR)]
    if (result["status"] != "observed" or len(in_closure) != 2 or
            result["graph"]["edges_by_kind"].get("state", 0) < 4):
        raise ValueError("source-backed graph failed sealed replay")
    return {"case_id": "SOLR-38", "host": "node1", "mode": "strict_fault_pilot_v3",
            "source_manifest_sha256": config_v3.sha(MANIFEST),
            "runner_sha256": config_v3.sha(HERE / "run_campaign.py"),
            "adapter_sha256": config_v3.sha(config_v3.ADAPTER),
            "graph_overlay_sha256": config_v3.sha(HERE / "graph_overlay.py"),
            "sealed_replay_strict_doors": len(in_closure),
            "intended_output": str(config_v3.OUT),
            "budget": config["budget"], "go": False,
            "full_campaign_authorized": False}


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
