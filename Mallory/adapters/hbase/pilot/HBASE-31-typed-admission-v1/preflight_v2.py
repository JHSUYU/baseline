#!/usr/bin/env python3
"""Offline SHA and scope checks for the HBASE-31 master dispatch binding pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from preflight import HERE, STAGED, check, main as base_preflight, require, sha


def main(allow_detached_source: bool = False) -> None:
    base_preflight(allow_detached_source)
    admission = json.loads((HERE / "admission-v2.json").read_text())
    prior = HERE / "healthy-v1-negative-receipt.json"
    check(prior, admission["prior_negative_receipt_sha256"])
    require(json.loads(prior.read_text())["qualification"] ==
            "blocked_unknown_master_actor_no_strict_event_time_path",
            "prior identity gap changed")
    release = HERE / "binding-overlay/releases/a8ddd472a72345b4"
    check(release / "manifest.json", admission["overlay_manifest_sha256"])
    manifest = json.loads((release / "manifest.json").read_text())
    overlay = release / "adapter.jar"
    check(overlay, admission["overlay_jar_sha256"])
    require(manifest["overlay_jar_sha256"] == admission["overlay_jar_sha256"] and
            manifest["base_adapter_sha256"] == admission["base_adapter_jar_sha256"] and
            manifest["maven_tests"] == {"run": 3, "failures": 0, "errors": 0},
            "overlay release identity changed")
    for relative, expected in manifest["source_sha256"].items():
        check(HERE / "binding-overlay" / relative, expected)

    config_path = HERE / "HBASE-31.dispatch-binding-v2.healthy.json"
    check(config_path, admission["config_sha256"])
    config = json.loads(config_path.read_text())
    baseline = json.loads((STAGED / "HBASE-31.healthy.json").read_text())
    require(config["target"] == baseline["target"] and
            config["site_file"] == baseline["site_file"] and
            config["cluster_test"] == baseline["cluster_test"] and
            config["core_release"] == baseline["core_release"] and
            config["agent_jar"] == baseline["agent_jar"],
            "target, test, site, core, or agent changed")
    require(config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False and
            config["agent_properties"]["auto.io.doors"] is False and
            config["mapping"]["fault_admission_blocked"] is True and
            config["budget"]["trials"] == 1, "healthy-only policy changed")
    base_jar = baseline["agent_properties"]["adapter.jar"]
    require(config["agent_properties"]["adapter.jars"] ==
            base_jar + "," + str(overlay) and
            config["agent_properties"]["adapter.transformers"] ==
            "edu.uva.liftlab.mallory.hbase.HBaseAdapterTransformer,"
            "edu.uva.liftlab.mallory.hbase31.DispatchBindingTransformer" and
            config["mapping"]["prior_typed_healthy_negative_receipt_sha256"] == sha(prior),
            "binding is not isolated to the pinned adapter pair")
    require(config["runtime_artifacts"][:-1] == baseline["runtime_artifacts"] and
            config["runtime_artifacts"][-1] ==
            {"path": str(overlay), "sha256": admission["overlay_jar_sha256"]},
            "runtime artifact set changed")
    for artifact in config["runtime_artifacts"]:
        check(Path(artifact["path"]), artifact["sha256"])
    require(str(overlay) in config["command"][6].split(":") and
            base_jar in config["command"][6].split(":"),
            "binding classes absent from test classpath")
    print("PASS HBASE-31 v2 offline preflight: exact target/test, immutable binding overlay, "
          "and strict healthy policy")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-detached-source", action="store_true")
    main(parser.parse_args().allow_detached_source)
