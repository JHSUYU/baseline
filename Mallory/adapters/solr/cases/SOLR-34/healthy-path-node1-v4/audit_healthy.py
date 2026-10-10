#!/usr/bin/env python3
"""Audit SOLR-34 target and synthetic collection path on a named coordinator."""

from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config-healthy-node1.json").read_text())
CHECK = CONFIG["target"]["check_sites"][0]
THROW = CONFIG["target"]["throw_site"]
NATIVE = CONFIG["target_absent_bootstrap"]["door_sites"][0]
TYPED = "org.apache.zookeeper.KeeperException$ConnectionLossException"
SYNTHETIC_STATE = "/collections/.sys.COORDINATOR-COLL-conf/state.json"
ROLE = re.compile(r"MALLORY_SOLR_NODE logical=(\S+) physical=(\S+) epoch=(\d+)")


def evaluate(result: dict, pilot: dict, junit: dict, catalog: list[dict],
             events: list[dict], junit_log: str) -> dict:
    if (result.get("case_id") != "SOLR-34" or result.get("status") != "calibration_complete"
            or result.get("cluster_test") != CONFIG["cluster_test"]
            or not (result.get("bootstrap_seed_valid") or result.get("healthy_seed_valid"))):
        raise ValueError("frozen core did not accept selected healthy JUnit")
    if (junit.get("status"), junit.get("tests"), junit.get("failures"),
            junit.get("errors"), junit.get("skipped")) != ("passed", 1, 0, 0, 0):
        raise ValueError("selected JUnit did not pass once")
    att = result.get("runtime_attestation", {})
    if (att.get("valid") is not True
            or ("exact_site_catalog_valid" in att and
                att.get("exact_site_catalog_valid") is not True)
            or att.get("observed_target_class_sha256") != CONFIG["expected_target_class_sha256"]
            or len(att.get("target_class_loader_ids", [])) != 1):
        raise ValueError("loaded exact target class or catalog changed")
    if (pilot.get("source_revision") != CONFIG["mapping"]["source_git_revision"]
            or pilot.get("agent_sha256") != CONFIG["mapping"]["agent_sha256"]):
        raise ValueError("source revision or path-aware agent changed")
    wiring = pilot.get("path_agent_preflight", {})
    if (wiring.get("agent_sha256") != CONFIG["mapping"]["agent_sha256"]
            or wiring.get("agent_path") != CONFIG["agent_jar"]
            or wiring.get("site_file") != CONFIG["site_file"]
            or wiring.get("typed_resource_argument") != "first_string_parameter"):
        raise ValueError("case-local pilot path-agent wiring is absent")
    if not any(row.get("site") == NATIVE
               and row.get("resource_argument") == "first_string_parameter"
               and row.get("exception_class") == TYPED for row in catalog):
        raise ValueError("loaded native door lacks path-aware instrumentation")
    if {CHECK, THROW} - {row.get("site") for row in catalog}:
        raise ValueError("exact check or selected throw not woven into loaded class")
    roles = {(logical, int(epoch)): physical
             for logical, physical, epoch in ROLE.findall(junit_log)}
    if ("node5", 0) not in roles or len({physical for physical in roles.values()}) < 5:
        raise ValueError("five-node JUnit lacks named coordinator binding")
    doors = [row for row in events if row.get("type") == "DOOR_OBSERVED"
             and row.get("site") == NATIVE
             and row.get("fault_type") == "EXCEPTION"
             and row.get("exception_class") == TYPED
             and row.get("resource") == SYNTHETIC_STATE
             and row.get("node") == "node5" and row.get("epoch") == 0
             and isinstance(row.get("seq"), int)
             and isinstance(row.get("door_ordinal"), int)]
    if not doors:
        raise ValueError("typed synthetic-state getData path absent on coordinator actor")
    targets = [row for row in events if row.get("type") == "TARGET_CHECK"
               and row.get("site") == CHECK and row.get("node") == "node5"
               and row.get("epoch") == 0 and isinstance(row.get("seq"), int)]
    after = [(door, target) for door in doors for target in targets
             if door["seq"] < target["seq"]]
    selected_throw = any(row.get("type") == "TARGET_THROW" and row.get("site") == THROW
                         for row in events)
    return {"status": "passed_path_bootstrap", "case_id": "SOLR-34",
            "cluster_test": CONFIG["cluster_test"], "physical_actor": "node5",
            "physical_address": roles[("node5", 0)],
            "resource": SYNTHETIC_STATE, "typed_path_door_count": len(doors),
            "target_check_count": len(targets),
            "full_target_gate_passed": bool(after),
            "target_threw": selected_throw,
            "target_absent_bootstrap_only": not bool(after),
            "first_path_door_seq": min(row["seq"] for row in doors),
            "first_postpath_target_seq": min((t["seq"] for _, t in after), default=None),
            "loaded_target_class_sha256": CONFIG["expected_target_class_sha256"]}


def attest(output: Path) -> dict:
    output = output.resolve()
    if output != Path(CONFIG["admission"]["intended_output"]).resolve():
        raise ValueError("unexpected healthy output")
    trial = output / "trials/r0000"
    with gzip.open(trial / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream]
    catalog = [json.loads(line) for line in (trial / "sites.jsonl").read_text().splitlines()
               if line]
    return evaluate(json.loads((output / "result.json").read_text()),
                    json.loads((trial / "pilot-result.json").read_text()),
                    json.loads((trial / "junit-receipt.json").read_text()),
                    catalog, events, (trial / "junit.log").read_text(errors="replace"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(attest(args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
