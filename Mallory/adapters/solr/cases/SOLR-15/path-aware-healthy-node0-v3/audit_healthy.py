#!/usr/bin/env python3
"""Bind the two SOLR-15 leader lookups to one observed live-node resource."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import re
from pathlib import Path


HERE = Path(__file__).resolve().parent
V2_AUDIT = HERE.parent / "chaos-healthy-node0-v2/audit_healthy.py"
NATIVE = ("org.apache.solr.common.cloud.SolrZkClient#lambda$exists$2"
          "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)"
          "Lorg/apache/zookeeper/data/Stat;@301:door:1")
LIVE_NODE = re.compile(r"^/live_nodes/([^/]+)$")
ROLE = re.compile(r"MALLORY_SOLR_NODE logical=(control|shard-[1-9][0-9]*) "
                  r"physical=([^\s]+) epoch=([0-9]+)")


def _v2_audit():
    spec = importlib.util.spec_from_file_location("solr15_v2_healthy_audit", V2_AUDIT)
    if spec is None or spec.loader is None:
        raise ValueError("pinned v2 actor audit missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bind_parent_resource(first: dict, second: dict,
                         registered_shard_addresses: set[str]) -> dict:
    """Require one path on the same physical split actor and registered parent."""
    if first.get("site") != NATIVE or second.get("site") != NATIVE:
        raise ValueError("native_exists_site_missing")
    for key in ("node", "epoch", "occurrence", "thread", "context"):
        if first.get(key) != second.get(key):
            raise ValueError("cross_actor_or_split_occurrence")
    if (not isinstance(first.get("seq"), int)
            or not isinstance(second.get("seq"), int)
            or first["seq"] >= second["seq"]):
        raise ValueError("leader_lookup_order_invalid")
    first_path, second_path = first.get("resource"), second.get("resource")
    if not isinstance(first_path, str) or not isinstance(second_path, str):
        raise ValueError("native_exists_resource_missing")
    if first_path != second_path:
        raise ValueError("leader_lookup_resource_changed")
    match = LIVE_NODE.fullmatch(first_path)
    if match is None:
        raise ValueError("not_exact_live_node_resource")
    parent_address = match.group(1)
    if parent_address not in registered_shard_addresses:
        raise ValueError("parent_leader_not_registered_shard_actor")
    return {"resource": first_path, "parent_physical_address": parent_address,
            "first_native_event_id": first.get("id"),
            "second_native_event_id": second.get("id"),
            "second_native_door_ordinal": second.get("door_ordinal")}


def attest(output: Path) -> dict:
    output = output.resolve()
    base = _v2_audit().attest(output)
    reasons = list(base.get("reasons", []))
    trial = output / "trials/r0000"
    witness = base.get("same_split_handoff_witness")
    resource_binding = None
    if witness:
        wanted = {witness["first_native_event_id"], witness["second_native_event_id"]}
        native_events = {}
        with gzip.open(trial / "events.jsonl.gz", "rt") as stream:
            for line in stream:
                event = json.loads(line)
                if event.get("id") in wanted:
                    native_events[event["id"]] = event
        catalog = [json.loads(line) for line in (trial / "sites.jsonl").read_text().splitlines()
                   if line]
        native_catalog = [row for row in catalog if row.get("site") == NATIVE]
        if len(native_catalog) != 1 or native_catalog[0].get("resource_argument") != "first_string_parameter":
            reasons.append("loaded_native_site_lacks_path_instrumentation")
        addresses = {physical for logical, physical, _ in
                     ROLE.findall((trial / "junit.log").read_text(errors="replace"))
                     if logical.startswith("shard-")}
        if len(native_events) != 2:
            reasons.append("selected_native_events_missing")
        else:
            try:
                resource_binding = bind_parent_resource(
                    native_events[witness["first_native_event_id"]],
                    native_events[witness["second_native_event_id"]], addresses)
            except ValueError as error:
                reasons.append(str(error))
    else:
        reasons.append("second_lookup_handoff_missing")
    base.update({"variant": "path-aware-healthy-node0-v3",
                 "status": "passed" if not reasons else "failed",
                 "reasons": reasons,
                 "resource_path_attested": resource_binding is not None,
                 "resource_binding": resource_binding,
                 "full_campaign_admitted": False})
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    receipt = attest(args.output)
    report = args.report or args.output / "path-aware-healthy-gate.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
