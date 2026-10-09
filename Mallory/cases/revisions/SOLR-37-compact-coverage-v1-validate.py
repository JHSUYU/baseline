"""Offline checks for the staged SOLR-37 compact-coverage healthy config."""

from __future__ import annotations

from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from Mallory.core.campaign import validate_config


BASE = ROOT / "Mallory/adapters/solr/cases/SOLR-37/config-v14a-lane1-junit.json"
STAGED = ROOT / "Mallory/adapters/solr/cases/SOLR-37/config-v22-compact-coverage-healthy.json"
TRACE = ROOT / "data/mallory/calibration_v14a_config_lane1/SOLR-37/trials/r0000/events.jsonl.gz"
CATALOG = ROOT / "data/mallory/calibration_v14a_config_lane1/SOLR-37/trials/r0000/sites.jsonl"
COMPATIBLE_TRACE = ROOT / "data/mallory/calibration_v21a_lane4/SOLR-36/trials/r0000/events.jsonl.gz"
REPORT = ROOT / "Mallory/cases/revisions/SOLR-37-compact-coverage-v1.validation.json"
AGENT_SHA = "1ac1a88de5533fb5f9af1ebd5756a6b96aa7bfaaaad0fc2ca9999587981abb40"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    base = json.loads(BASE.read_text())
    staged = json.loads(STAGED.read_text())
    # The pinned execution checkout is on the admitted lane, not this host.
    local_schema_copy = dict(staged)
    local_schema_copy["cwd"] = staged["mapping"]["source_root"]
    validate_config(local_schema_copy)
    assert staged["calibration_only"] is True
    assert staged["auto_promote_if_healthy"] is False
    assert staged["budget"]["trials"] == 1
    for key in ("case_id", "cluster_test", "command", "cwd", "site_file", "target", "agent_include", "expected_target_class_sha256"):
        assert staged[key] == base[key], key
    for key in ("coverage.methods", "coverage.branches", "auto.io.doors"):
        assert staged["agent_properties"][key] is True, key
        assert staged["agent_properties"][key] == base["agent_properties"][key], key
    assert staged["agent_properties"]["max.bytes"] == 100 * 1024 * 1024
    assert staged["agent_properties"]["max.events"] == 1_000_000
    agent = Path(staged["agent_jar"])
    assert sha(agent) == AGENT_SHA
    assert staged["env"]["MALLORY_SOLR_AGENT_JAR"] == str(agent)
    assert staged["mapping"]["agent_sha256"] == AGENT_SHA
    assert any(row["path"] == str(agent) and row["sha256"] == AGENT_SHA
               for row in staged["runtime_artifacts"])
    with ZipFile(agent) as archive:
        probe = archive.read("edu/uva/liftlab/mallory/instrumentation/Probe.class")
    assert b"COVERAGE_DEF" in probe and b"COVERAGE_SUMMARY" in probe
    assert b"TARGET_CHECK" in probe and b"DOOR_OBSERVED" in probe
    assert b"METHOD" not in probe and b"BRANCH" not in probe

    target_checks = set(staged["target"]["check_sites"])
    target_throw = staged["target"]["throw_site"]
    catalog_sites = set()
    with CATALOG.open() as stream:
        for line in stream:
            item = json.loads(line)
            if item.get("type") in ("TARGET_CHECK", "TARGET_THROW"):
                catalog_sites.add((item["type"], item["site"]))
    assert all(("TARGET_CHECK", site) in catalog_sites for site in target_checks)
    assert ("TARGET_THROW", target_throw) in catalog_sites
    # The same immutable agent already wove this Solr class in a valid SOLR-36
    # calibration; its compact coverage definitions confirm both bytecode ordinals.
    compatible_coverage = set()
    with gzip.open(COMPATIBLE_TRACE, "rt") as stream:
        for line in stream:
            item = json.loads(line)
            if item["type"] == "COVERAGE_DEF":
                compatible_coverage.add(item["coverage_id"])
    assert all(any(coverage_id.startswith(site + ":")
                   for coverage_id in compatible_coverage) for site in target_checks)

    refs: dict[str, int] = {}
    occurrence_coverage: dict[tuple[str, int, str], set[int]] = defaultdict(set)
    retained = Counter()
    target_count = 0
    door_count = 0
    retained_bytes = 0
    original_events = 0
    coverage_events = 0
    with gzip.open(TRACE, "rt") as stream:
        for line in stream:
            event = json.loads(line)
            original_events += 1
            kind = event["type"]
            if kind in ("METHOD", "BRANCH"):
                coverage_events += 1
                coverage_id = event["coverage_id"]
                ref = refs.setdefault(coverage_id, len(refs) + 1)
                occurrence_coverage[(event["node"], event["epoch"], event["occurrence"])].add(ref)
            elif kind != "TRACE_TRUNCATED":
                retained[kind] += 1
                retained_bytes += len(line.encode())
                if kind == "TARGET_CHECK" and event["site"] in target_checks:
                    target_count += 1
                if kind == "DOOR_OBSERVED":
                    door_count += 1

    # Conservative allowance covers the sink-added id/seq fields for each summary row.
    def row_bytes(row: dict) -> int:
        return len(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode()) + 81

    summary_bytes = sum(row_bytes({
        "type": "COVERAGE_DEF", "node": "unknown", "epoch": 0,
        "occurrence": "coverage-definition", "site": "mallory:coverage-definition",
        "coverage_ref": ref, "coverage_id": coverage_id, "ts": 790000000000000,
    }) for coverage_id, ref in refs.items())
    summary_bytes += sum(row_bytes({
        "type": "COVERAGE_SUMMARY", "node": node, "epoch": epoch,
        "occurrence": occurrence, "site": "mallory:coverage-summary",
        "coverage_refs": sorted(coverage_refs), "ts": 790000000000000,
    }) for (node, epoch, occurrence), coverage_refs in occurrence_coverage.items())
    projected = retained_bytes + summary_bytes
    assert target_count == 108 and door_count == 1464
    assert projected < 10 * 1024 * 1024
    report = {
        "schema_version": 1,
        "revision": "SOLR-37-compact-coverage-v1",
        "scope": "offline static and truncated-prefix projection only; no JVM trial executed",
        "status": "offline_validated_full_trial_pending",
        "base_config_sha256": sha(BASE),
        "staged_config_sha256": sha(STAGED),
        "agent_sha256": AGENT_SHA,
        "source_trace_gzip_sha256": sha(TRACE),
        "source_site_catalog_sha256": sha(CATALOG),
        "compatible_solr36_trace_gzip_sha256": sha(COMPATIBLE_TRACE),
        "compact_agent_solr36_exact_site_ordinals_confirmed": True,
        "same_junit_target_sites_include": True,
        "offhost_execution_cwd_exists_here": Path(staged["cwd"]).is_dir(),
        "method_and_branch_coverage_enabled": True,
        "agent_uses_compact_coverage_definitions_and_summaries": True,
        "old_prefix_events": original_events,
        "old_prefix_coverage_events_compacted": coverage_events,
        "old_prefix_retained_event_counts": dict(sorted(retained.items())),
        "old_prefix_distinct_coverage_ids": len(refs),
        "old_prefix_coverage_occurrence_groups": len(occurrence_coverage),
        "old_prefix_target_checks_retained": target_count,
        "old_prefix_door_events_retained": door_count,
        "old_prefix_projected_compact_raw_bytes": projected,
        "raw_sink_cap_bytes": staged["agent_properties"]["max.bytes"],
        "limitation": "The old trace ends at 32.7 seconds due to truncation. This projection cannot establish the complete new trial's size or successful JVM exit; require a fresh healthy run and complete COVERAGE_DEF/SUMMARY audit before promotion.",
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(REPORT)


if __name__ == "__main__":
    main()
