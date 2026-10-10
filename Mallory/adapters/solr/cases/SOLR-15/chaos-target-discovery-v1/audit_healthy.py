#!/usr/bin/env python3
"""Attest a fresh original chaos JUnit and its native retry door."""

import argparse
import json
import re
from pathlib import Path

NATIVE = "org.apache.solr.common.cloud.SolrZkClient#lambda$exists$2(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)Lorg/apache/zookeeper/data/Stat;@301:door:1"
CHECK = "org.apache.solr.cloud.api.collections.SplitShardCmd#split(Lorg/apache/solr/common/cloud/ClusterState;Lorg/apache/solr/common/cloud/ZkNodeProps;Lorg/apache/solr/common/util/NamedList;)Z@536:branch:40"
THROW = "org.apache.solr.cloud.api.collections.SplitShardCmd#split(Lorg/apache/solr/common/cloud/ClusterState;Lorg/apache/solr/common/cloud/ZkNodeProps;Lorg/apache/solr/common/util/NamedList;)Z@538:throw:1"


def attest(output: Path) -> dict:
    result = json.loads((output / "result.json").read_text())
    trial = json.loads((output / "trials/r0000/result.json").read_text())
    catalog = [json.loads(line) for line in
               (output / "trials/r0000/sites.jsonl").read_text().splitlines() if line]
    junit = result.get("healthy_junit_validation") or {}
    validation = trial.get("site_catalog_validation") or {}
    doors = [d for d in trial.get("feedback", {}).get("doors", [])
             if d.get("site") == NATIVE and
             re.fullmatch(r"node[1-9][0-9]*", str(d.get("point", {}).get("node", "")))]
    observed = {row.get("site") for row in catalog}
    reasons = []
    if not (junit.get("status") == "passed" and junit.get("tests") == 1
            and junit.get("failures") == 0 and junit.get("errors") == 0):
        reasons.append("original_junit_not_1_0_0")
    if (not result.get("bootstrap_seed_valid") or
            not result.get("runtime_attestation", {}).get("valid") or
            trial.get("feedback", {}).get("status") != "healthy_target_missing"):
        reasons.append("target_absent_bootstrap_not_valid")
    if (validation.get("valid") is not True or
            validation.get("class_hash_match") is not True or
            CHECK not in observed or THROW not in observed or NATIVE not in observed):
        reasons.append("exact_target_or_native_door_catalog_missing")
    if not doors:
        reasons.append("native_exists_door_lacks_named_physical_actor")
    return {"schema_version": 1, "case_id": "SOLR-15", "variant": "chaos-target-discovery-v1",
            "status": "passed" if not reasons else "failed", "reasons": reasons,
            "original_junit": junit, "target_check_site": CHECK, "target_throw_site": THROW,
            "native_door_site": NATIVE,
            "named_native_door_actors": sorted({d["point"]["node"] for d in doors}),
            "native_door_count": len(doors),
            "resource_path_attested": False,
            "note": "Door events identify site and node; this adapter does not record the ZooKeeper path."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    receipt = attest(args.output)
    (args.output / "chaos-healthy-gate.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
