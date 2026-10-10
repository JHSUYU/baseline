#!/usr/bin/env python3
"""Gate a fresh SOLR-14 retry JUnit seed using exact, typed runtime events."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config-full-node1.json").read_text())
REGION = CONFIG["target"]["check_sites"][0].split("@", 1)[0]
CHECK = REGION + "@165:branch:5"
FIRST = REGION + "@130:door:1"
SECOND = REGION + "@164:door:2"
TYPED = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def evaluate(result: dict, pilot: dict, junit: dict, events: list[dict]) -> dict:
    if result.get("case_id") != "SOLR-14" or result.get("healthy_seed_valid") is not True:
        raise ValueError("healthy seed not accepted by frozen core")
    if result.get("cluster_test") != CONFIG["cluster_test"]:
        raise ValueError("wrong unchanged JUnit selector")
    if (junit.get("status"), junit.get("tests"), junit.get("failures"),
            junit.get("errors"), junit.get("skipped")) != ("passed", 1, 0, 0, 0):
        raise ValueError("selected JUnit did not pass once")
    att = result.get("runtime_attestation", {})
    expected = CONFIG["expected_target_class_sha256"]
    if not att.get("valid") or att.get("observed_target_class_sha256") != expected:
        raise ValueError("loaded target class is not the pinned Solr class")
    if (pilot.get("source_revision") != CONFIG["mapping"]["source_git_revision"]
            or pilot.get("agent_sha256") != CONFIG["mapping"]["agent_sha256"]
            or pilot.get("target_throw_count") != 0):
        raise ValueError("source, agent, or healthy target outcome changed")
    by_occurrence: dict[tuple, dict[str, dict]] = {}
    for event in events:
        if event.get("type") not in {"DOOR_OBSERVED", "TARGET_CHECK"}:
            continue
        if event.get("site") not in {FIRST, SECOND, CHECK}:
            continue
        actor = event.get("node")
        occurrence = event.get("occurrence")
        epoch = event.get("epoch")
        if not actor or actor == "unknown" or not occurrence or not isinstance(epoch, int):
            raise ValueError("unnamed runtime actor or split occurrence")
        if event["site"] in {FIRST, SECOND} and (
                event.get("fault_type") != "EXCEPTION"
                or event.get("exception_class") != TYPED):
            raise ValueError("untyped pretarget ZooKeeper door")
        by_occurrence.setdefault((actor, epoch, occurrence), {})[event["site"]] = event
    matched = []
    for (actor, epoch, occurrence), hits in by_occurrence.items():
        if not all(site in hits for site in (FIRST, SECOND, CHECK)):
            continue
        a, b, target = (hits[site] for site in (FIRST, SECOND, CHECK))
        if not a["seq"] < b["seq"] < target["seq"]:
            raise ValueError("pretarget door order changed")
        matched.append((a["seq"], actor, epoch, occurrence, target["seq"]))
    matched.sort()
    if len(matched) < 2 or matched[0][1:3] != matched[1][1:3]:
        raise ValueError("first and retry split did not expose two typed target paths")
    if not matched[0][4] < matched[1][0]:
        raise ValueError("retry split did not follow first target check")
    return {"status": "healthy_retry_gate_passed", "case_id": "SOLR-14",
            "host": "node1", "matched_split_occurrences": len(matched),
            "physical_actor": matched[0][1], "epoch": matched[0][2],
            "first_target_seq": matched[0][4], "retry_door_seq": matched[1][0],
            "retry_target_seq": matched[1][4],
            "source_revision": pilot["source_revision"], "loaded_class_sha256": expected}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="fresh SOLR-14 healthy output directory")
    args = parser.parse_args()
    output = args.output.resolve()
    expected = Path(CONFIG["admission"]["intended_output"])
    if output != expected or not output.is_dir():
        raise ValueError("expected fresh node1 healthy output")
    trial = output / "trials/r0000"
    with gzip.open(trial / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream]
    receipt = evaluate(
        json.loads((output / "result.json").read_text()),
        json.loads((trial / "pilot-result.json").read_text()),
        json.loads((trial / "junit-receipt.json").read_text()), events)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
