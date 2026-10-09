#!/usr/bin/env python3
"""Bind the current SOLR-38/39 I/O-fault gaps to source and prior JUnit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def line(source: Path, number: int) -> str:
    return source.read_text().splitlines()[number - 1]


def solr38(base: Path, source_root: Path) -> dict:
    source = source_root / "solr/core/src/java/org/apache/solr/update/processor/DistributedZkUpdateProcessor.java"
    healthy = base / "data/mallory/calibration_v24_lane1/SOLR-38"
    pilot = base / "data/mallory/pilot_v24p_lane1/SOLR-38"
    sites = base / "Mallory/adapters/solr/cases/SOLR-38/sites-v24p-observed-http2.json"
    h, p = json.loads((healthy / "result.json").read_text()), json.loads((pilot / "result.json").read_text())
    rule = json.loads(sites.read_text())
    assert h["case_id"] == p["case_id"] == "SOLR-38"
    assert h["status"] == "calibration_complete" and h["healthy_seed_valid"]
    assert h["healthy_junit_validation"]["status"] == "passed"
    assert h["trials"][0]["target_reached"] is True
    assert p["status"] == "budget_exhausted" and p["fault_trials_completed"] == 4
    assert p["strict_injected_trials"] == 4 and p["strict_target_trials"] == 0
    assert all(not row["target_reached"] for row in p["trials"][1:])
    assert rule["doors"] == [{"class": "org.apache.solr.client.solrj.impl.Http2SolrClient",
                              "method": "request", "line": 776,
                              "exception_class": "java.io.IOException"}]
    assert "DocCollection docCollection = clusterState.getCollection(collection)" in line(source, 980)
    assert "localIsLeader = cloudDesc.isLeader()" in line(source, 1013)
    assert "Thread.sleep(500)" in line(source, 1015)
    assert "catch (InterruptedException e)" in line(source, 1016)
    assert "if ((isLeader && !localIsLeader)" in line(source, 1021)
    assert not any("zkClient." in row or "httpClient." in row
                   for row in source.read_text().splitlines()[973:1021])
    return {"schema_version": 1, "case_id": "SOLR-38",
            "classification": "current_typed_io_fault_model_no_retained_target",
            "full_campaign_promoted": False, "new_bug_confirmed": False,
            "source_path": str(source.relative_to(source_root)), "source_sha256": sha(source),
            "exact_check_line": 1021, "exact_throw_line": 1023,
            "healthy_result_sha256": sha(healthy / "result.json"),
            "healthy_audit_sha256": sha(healthy / "offline-causal-audit.json"),
            "pilot_result_sha256": sha(pilot / "result.json"),
            "pilot_audit_sha256": sha(pilot / "offline-causal-audit.json"),
            "typed_io_site_file_sha256": sha(sites),
            "pilot_effective_fault_trials": 4, "pilot_postfault_target_trials": 0,
            "source_finding": ("doDefensiveChecks reads the cached clusterState and cloudDesc "
                               "before line 1021. Its only caught pretarget exception in the "
                               "method is InterruptedException at Thread.sleep (lines 1015-1017), "
                               "which is not an I/O point. The already tested client HTTP/2 "
                               "IOException door had four effective injections and zero "
                               "postfault target reaches. This does not exclude a distinct "
                               "background state-changing I/O fault model."),
            "next_step": "Require a source-backed I/O-to-leader-state path and bounded retained-target pilot before full promotion."}


def solr39(base: Path, source_root: Path) -> dict:
    source = source_root / "solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java"
    reader = source_root / "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"
    aliases = source_root / "solr/solrj/src/java/org/apache/solr/common/cloud/Aliases.java"
    healthy = base / "data/mallory/calibration_v10_lane1_remaining/SOLR-39/result.json"
    review = base / "Mallory/cases/revisions/SOLR-39-source-review-no-suitable-test-v1.json"
    staged = base / "Mallory/adapters/solr/cases/SOLR-39/config-v23-configset-auth-healthy.json"
    result = json.loads(healthy.read_text())
    assert result["case_id"] == "SOLR-39" and result["status"] == "healthy_seed_invalid"
    assert not result["healthy_seed_valid"] and result["healthy_eligible_doors"] == 0
    assert "lookupShardLeadersOfCollections()" in line(source, 195)
    assert "lookupShardLeadersOfCollections()" in line(source, 201)
    assert "cmdDistrib.distribDelete" in line(source, 196)
    assert "cmdDistrib.distribCommit" in line(source, 202)
    assert "cmdDistrib.blockAndDoRetries" in line(source, 203)
    assert "getAliases()" in line(source, 244)
    assert "getCollectionAliasListMap()" in line(source, 245)
    assert "if (collections == null)" in line(source, 246)
    assert "return aliasesManager.getAliases()" in line(reader, 2198)
    assert "return aliases; // volatile read" in line(reader, 2223)
    assert "Collections.unmodifiableMap(collectionAliases)" in line(aliases, 173)
    assert json.loads(staged.read_text())["calibration_only"] is True
    return {"schema_version": 1, "case_id": "SOLR-39",
            "classification": "current_selector_and_typed_io_path_unproven",
            "full_campaign_promoted": False, "new_bug_confirmed": False,
            "source_path": str(source.relative_to(source_root)), "source_sha256": sha(source),
            "state_reader_source_sha256": sha(reader), "aliases_source_sha256": sha(aliases),
            "exact_check_line": 246, "exact_throw_line": 247,
            "prior_invalid_result_sha256": sha(healthy),
            "prior_source_review_sha256": sha(review),
            "unrun_fixture_overlay_config_sha256": sha(staged),
            "source_finding": ("lookupShardLeadersOfCollections reads a volatile cached Aliases "
                               "reference and an immutable map before its line-246 null guard; "
                               "there is no I/O or catch in that invocation before the guard. "
                               "processDelete and processCommit call this check before their "
                               "distributor I/O. The prior opt-in cluster JUnit failed in "
                               "createConfigSet before reaching the target; the later configset "
                               "fixture overlay has not been run for this case."),
            "next_step": "First obtain a passing existing cluster JUnit and trace a background alias-update I/O effect to this guard; then pilot a typed fault."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--case-id", choices=("SOLR-38", "SOLR-39"), required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    receipt = (solr38 if args.case_id == "SOLR-38" else solr39)(args.base, args.source_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_id": args.case_id, "classification": receipt["classification"]}, sort_keys=True))


if __name__ == "__main__":
    main()
