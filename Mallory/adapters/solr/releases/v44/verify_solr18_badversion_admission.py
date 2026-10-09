#!/usr/bin/env python3
"""Pin the untried SOLR-18 BadVersion recovery door to source and healthy trace."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


DOOR = (
    "org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
    "#applyModificationAndExportToZk(Ljava/util/function/UnaryOperator;)V@2259:door:1"
)
TARGET_PREFIX = (
    "org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
    "#setIfNewer(Lorg/apache/solr/common/cloud/Aliases;)Z@2347:branch:"
)
BAD_VERSION = "org.apache.zookeeper.KeeperException$BadVersionException"
CONNECTION_LOSS = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review(source: Path, test_source: Path, healthy: Path, pilot: Path) -> dict:
    source_text = source.read_text()
    method = source_text.split("public void applyModificationAndExportToZk(", 1)[1].split(
        "public boolean update()", 1
    )[0]
    update = source_text.split("public boolean update()", 1)[1].split(
        "public void process(WatchedEvent event)", 1
    )[0]
    assert method.index("getZkClient().setData(ALIASES, modAliasesJson") < method.index(
        "catch (KeeperException.BadVersionException e)"
    ) < method.index("update();", method.index("catch (KeeperException.BadVersionException e)"))
    assert "setIfNewer(Aliases.fromJSON(modAliasesJson, stat.getVersion()));" in method
    assert "final byte[] data = zkClient.getData(ALIASES, null, stat, true);" in update
    assert "return setIfNewer(Aliases.fromJSON(data, stat.getVersion()));" in update
    assert "testDeleteAliasWithExistingCollectionName()" in test_source.read_text()

    healthy_result = json.loads((healthy / "result.json").read_text())
    healthy_audit = json.loads((healthy / "offline-causal-audit.json").read_text())
    pilot_result = json.loads((pilot / "result.json").read_text())
    prior_gap = Path("data/mallory/quality_reviews/solr18_v40p_gap/SOLR-18.json")
    gap = json.loads(prior_gap.read_text())
    assert healthy_result["status"] == "calibration_complete"
    assert pilot_result["status"] == "budget_exhausted"
    assert healthy_audit["campaign_result_sha256"] == sha(healthy / "result.json")
    assert healthy_audit["report_gate_passed"] is True
    assert gap["source_sha256"] == sha(source)
    assert gap["pilot_result_sha256"] == sha(pilot / "result.json")
    assert gap["same_actor_postfault_target_trials"] == 0

    catalog = [json.loads(line) for line in (healthy / "trials/r0000/sites.jsonl").read_text().splitlines()]
    catalog_door = [row for row in catalog if row.get("type") == "DOOR_OBSERVED" and row.get("site") == DOOR]
    assert len(catalog_door) == 1
    assert catalog_door[0]["exception_class"] == CONNECTION_LOSS
    events_path = healthy / "trials/r0000/events.jsonl.gz"
    with gzip.open(events_path, "rt") as stream:
        events = [json.loads(line) for line in stream]
    doors = [row for row in events if row.get("type") == "DOOR_OBSERVED" and row.get("site") == DOOR]
    enter = {row["occurrence"]: row for row in events if row.get("type") == "REGION_ENTER"}
    exits = {row["occurrence"]: row for row in events if row.get("type") == "REGION_EXIT"}
    target_regions = [row for row in events if row.get("type") == "REGION_ENTER"
                      and "AliasesManager#setIfNewer" in row.get("site", "")]
    targets = [row for row in events if row.get("type") == "TARGET_CHECK"
               and row.get("site", "").startswith(TARGET_PREFIX)]
    rows = []
    for door in doors:
        parent = enter[door["occurrence"]]
        assert parent["seq"] < door["seq"] < exits[door["occurrence"]]["seq"]
        children = [row for row in target_regions if row.get("parent_id") == door["occurrence"]
                    and door["seq"] < row["seq"] < exits[door["occurrence"]]["seq"]]
        child_checks = [row for row in targets if row["occurrence"] in {child["occurrence"] for child in children}]
        rows.append({
            "event_id": door["id"], "node": door["node"], "epoch": door["epoch"],
            "thread_id": door["thread_id"], "occurrence": door["occurrence"],
            "door_ordinal": door["door_ordinal"], "exception_class": door["exception_class"],
            "normal_success_child_set_if_newer": len(children),
            "normal_success_selected_checks": len(child_checks),
        })
    assert len(rows) == 5
    assert Counter(row["node"] for row in rows) == Counter({"node2": 4, "client": 1})
    assert all(row["normal_success_child_set_if_newer"] == 1 for row in rows)
    assert all(row["normal_success_selected_checks"] == 0 for row in rows)
    assert all(row["thread_id"] is not None for row in rows)
    assert any(row["planned_point"]["site"] == DOOR and not row["exact_applied"]
               for row in gap["trials"])
    assert not any(row["planned_point"]["site"] == DOOR and row["exact_applied"]
                   for row in gap["trials"])

    return {
        "schema_version": 1, "case_id": "SOLR-18", "classification": "source_backed_untried_typed_recovery_door",
        "full_campaign_promoted": False, "bug_confirmed": False,
        "healthy_result_sha256": sha(healthy / "result.json"),
        "healthy_audit_sha256": sha(healthy / "offline-causal-audit.json"),
        "healthy_events_gzip_sha256": sha(events_path),
        "healthy_catalog_sha256": sha(healthy / "trials/r0000/sites.jsonl"),
        "pilot_result_sha256": sha(pilot / "result.json"),
        "prior_gap_receipt_sha256": sha(prior_gap),
        "source_sha256": sha(source), "test_source_sha256": sha(test_source),
        "old_sites_file_sha256": sha(Path("Mallory/adapters/solr/cases/SOLR-18/sites-v19.json")),
        "door_site": DOOR, "proposed_exception_class": BAD_VERSION,
        "original_exception_class": CONNECTION_LOSS,
        "door_rows": rows,
        "source_reason": (
            "BadVersionException from setData is caught inside applyModificationAndExportToZk; "
            "the catch invokes update, whose successful getData invokes setIfNewer on the same "
            "AliasesManager before the outer operation returns. The old ConnectionLossException "
            "door propagates. Normal successful setData calls enter setIfNewer but skip the "
            "selected equal-version assertion; the BadVersion recovery update may take that branch."
        ),
        "runtime_gate": (
            "Fresh healthy must show a named, numeric-thread door on a uniquely bound node/epoch. "
            "A bounded typed pilot must prove DOOR_OBSERVED, FAULT_MATCHED, FAULT_APPLIED, "
            "then exact @2347 TARGET_CHECK in the same applyModificationAndExportToZk "
            "occurrence, node, epoch and thread, with JUnit oracle checked."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--test-source", required=True, type=Path)
    parser.add_argument("--healthy", required=True, type=Path)
    parser.add_argument("--pilot", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    row = review(args.source, args.test_source, args.healthy, args.pilot)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": row["classification"], "healthy_door_count": len(row["door_rows"])}))


if __name__ == "__main__":
    main()
