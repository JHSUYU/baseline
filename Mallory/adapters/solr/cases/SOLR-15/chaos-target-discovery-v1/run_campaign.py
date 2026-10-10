#!/usr/bin/env python3
"""Healthy-only, GO-gated SOLR-15 chaos workload bootstrap."""

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(HERE.parents[2]))
from fault_discovery_runner import check_go, preflight, read, sha, campaign  # noqa: E402

SELECTOR = "org.apache.solr.cloud.api.collections.ShardSplitTest#testSplitWithChaosMonkey"
NATIVE = "org.apache.solr.common.cloud.SolrZkClient#lambda$exists$2(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)Lorg/apache/zookeeper/data/Stat;@301:door:1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["healthy"], required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    config = read(HERE / "config-healthy-node2.json")
    metadata = preflight(HERE, "healthy")
    package = read(HERE / "sha-manifest.json")
    inventory = read(HERE / "inventory.json")["cases"][0]
    workload = inventory["workload"]
    native = package["retry_internal_exists"]
    source = Path(config["cwd"]) / native["source_path"]
    solrj = Path(config["mapping"]["solrj_compiled_jar"])
    with zipfile.ZipFile(solrj) as archive:
        class_hash = hashlib.sha256(archive.read(
            "org/apache/solr/common/cloud/SolrZkClient.class")).hexdigest()
    if (config["cluster_test"] != SELECTOR
            or config["command"][1] != str(HERE / "run_pilot.py")
            or config["env"].get("MALLORY_SOLR_NIGHTLY") != "1"
            or workload["selected_selector"] != SELECTOR
            or workload["test_source_path"] != package["test_source_path"]
            or workload["candidates"][0]["source_sha256"] != package["test_source_sha256"]
            or config["mapping"]["solrj_compiled_jar_sha256"] != sha(solrj)
            or class_hash != native["class_sha256"]
            or sha(source) != native["source_sha256"]
            or "keeper.exists(" not in source.read_text().splitlines()[300]
            or native["site"] != NATIVE
            or NATIVE not in config["target_absent_bootstrap"]["door_sites"]
            or not any(row.get("class") == "org.apache.solr.common.cloud.SolrZkClient"
                       and row.get("method") == "lambda$exists$2"
                       and row.get("line") == 301
                       and row.get("callee") == native["callee"]
                       and row.get("exception_class") == "org.apache.zookeeper.KeeperException$ConnectionLossException"
                       for row in read(HERE / "sites.json")["doors"])):
        raise ValueError("isolated JUnit or retry-internal typed exists door changed")
    out = ROOT / "data/mallory/solr_fault_discovery_node2_v1/healthy/SOLR-15-chaos-v1"
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", "selector": SELECTOR,
                          "native_door": NATIVE, **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.admission_receipt, "SOLR-15",
                                             "healthy", metadata["config_sha256"],
                                             out, HERE / "run_campaign.py")
    print(json.dumps({"preflight": "passed", **metadata}, sort_keys=True), flush=True)
    state = campaign.run(HERE / "config-healthy-node2.json", out)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"],
                      "elapsed_seconds": state["elapsed_seconds"]}, sort_keys=True))
    return subprocess.run([sys.executable, str(HERE / "audit_healthy.py"), str(out)],
                          check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
