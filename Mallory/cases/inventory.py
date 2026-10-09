#!/usr/bin/env python3
"""Derive Mallory's case inventory from the immutable 102-site selection.

This is an inventory, not a claim that a Mallory seed or fault run succeeded.
The recorded CrashFuzz status is retained only as historical context.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import statistics
from collections import Counter
from pathlib import Path


BASELINE = Path(__file__).resolve().parents[2]
LEGACY = BASELINE / "data" / "crashfuzz"
HERE = Path(__file__).resolve().parent
SOLR_DIRECT_RUNNER = BASELINE / "Mallory" / "adapters" / "solr" / "run_pilot.py"
SOLR_ISOLATED_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/solr")
HDFS_ISOLATED_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs")
HDFS_LANE2_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
ZOOKEEPER_ISOLATED_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/zookeeper")
HBASE_RUNTIME_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/hbase/runtime")
HBASE_RECEIPT = BASELINE / "Mallory" / "adapters" / "hbase" / "overlay-receipt.json"
HBASE_LANE2_RECEIPT = BASELINE / "Mallory" / "adapters" / "hbase" / "lane2-receipt.json"
SOURCES = {
    "hbase": ("2.6.6", Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6"), Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6")),
    "hdfs": ("3.4.3", Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"), Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")),
    "solr": ("8.11.4", Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4"), Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4")),
    "zookeeper": ("3.8.7", Path("/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7"), Path("/users/ZhenyuLi/.baseline-deps/apache-zookeeper-3.8.7-bin")),
}
FIXTURE_MARKERS = (
    "MiniDFSCluster", "MiniQJMHACluster", "MiniHBaseCluster", "HBaseTestingUtility",
    "MiniSolrCloudCluster", "SolrCloudTestCase", "MiniZooKeeperCluster", "MiniZKCluster",
    "QuorumBase", "QuorumUtil", "configureCluster(", "startMiniCluster(",
    "startMiniZKCluster(", "startMiniHBaseCluster(", "startCluster(",
)
METHOD = re.compile(r"(?:^|[.#])(?P<class>[A-Za-z_][\w$]*)(?:[.#])(?P<method>[A-Za-z_]\w*)$")
TEST_ANNOTATION = re.compile(r"@(?:Test|TestTemplate|ParameterizedTest)\b")
# Source-inspected candidates missing from the old selection. These have a
# real embedded-cluster fixture, but target reach still requires calibration.
INFERRED_TESTS = {
    "HBASE-23": {
        "selector": "TestZKProcedureControllers#testZKCoordinatorControllerWithSingleMemberCohort",
        "evidence": "The @Test calls runMockCommitWithOrchestratedControllers, which invokes sendGlobalBarrierReached against a MiniZKCluster.",
    },
    "HDFS-13": {
        "selector": "TestBlockTokenWithDFS#testEnd2End",
        "evidence": "The @Test enables block tokens and invokes TestBalancer.integrationTest, which uses MiniDFSCluster.",
    },
}
ALTERNATE_TESTS = {
    "HDFS-01": {
        "selector": "TestDFSInputStream#testSkipWithRemoteBlockReader",
        "evidence": "MiniDFSCluster creates a four MiB file; testSkipInner reads in-range positions while skipping and does not explicitly request an EOF exception.",
    },
    "HDFS-43": {
        "selector": "TestFileTruncate#testMultipleTruncate",
        "evidence": "@Before builds a three-DataNode MiniDFSCluster. The test immediately repeats the same-length truncate during block recovery; a separate healthy calibration reached the selected nn0 guard seven times without its exception.",
    },
    "HDFS-49": {
        "selector": "TestSnapshot#testUpdateDirectory",
        "evidence": "The MiniDFSCluster test creates one snapshot and checks directory metadata. A separate healthy calibration reached the selected nn0 snapshot-quota guard once without its exception or trace truncation.",
    },
    "ZOOKEEPER-02": {
        "selector": "QuorumTest#testMultiToFollower",
        "evidence": "Three-peer test submits a multi-operation through a follower and reads the created nodes without intentionally moving a session; exact owner-comparison reach is unverified.",
    },
    "ZOOKEEPER-03": {
        "selector": "QuorumTest#testMultiToFollower",
        "evidence": "Three-peer source workload avoids the deliberate session move; exact setOwner guard reach is unverified.",
    },
    "ZOOKEEPER-13": {
        "selector": "ReadOnlyModeTest#testConnectionEvents;ReadOnlyModeTest#testReadOnlyClient",
        "evidence": "Both quorum tests enable local sessions. testConnectionEvents keeps the original local-session client alive across quorum loss, making read-only renewal plausible; testReadOnlyClient closes it first, so target reach is less likely. Neither alternate has exact target/no-throw calibration.",
    },
}
SOURCE_ORACLE_WARNINGS = {
    "HDFS-01": "The selected TestPread workload calls writeFile and pReadFile, which intentionally read beyond EOF and catch IOException. A healthy target EOFException may therefore be expected; inspect the exact target throw in a healthy trace before using this workload as an oracle.",
    "ZOOKEEPER-02": "The recorded QuorumTest#testSessionMoved intentionally exercises rejection and is unsuitable as a healthy oracle. The selected QuorumTest#testMultiToFollower alternate has a separately verified three-peer healthy calibration.",
    "ZOOKEEPER-03": "The recorded QuorumTest#testSessionMoved intentionally replaces a session owner. The selected QuorumTest#testMultiToFollower alternate has a separately verified three-peer healthy calibration.",
    "ZOOKEEPER-13": "ReadOnlyModeTest#testGlobalSessionInRO intentionally tries to renew a global session in read-only mode and expects rejection. Its CloseRequestException is normal for that selector. Local-session alternates need exact target/no-throw calibration.",
    "HDFS-13": "The selected TestBlockTokenWithDFS#testEnd2End MiniCluster test executes the six-argument Token.checkAccess overload, whereas this check is in the four-argument Token overload. The latter is called directly from TestBlockToken without a cluster in the known source tests; an appropriate cluster workload remains unmapped.",
    "HDFS-43": "The recorded testTruncateTwiceTogether deliberately expects the selected AlreadyBeingCreatedException. The selected testMultipleTruncate alternate has a separate healthy MiniDFSCluster calibration with seven exact nn0 checks and zero selected throws; fault trials remain pending.",
    "HDFS-49": "The recorded TestSnapshot#testSnapshot workload produced a truncated trace. The selected testUpdateDirectory alternate has a separate healthy MiniDFSCluster calibration with one exact nn0 check, zero selected throws, 44 eligible doors, and no truncation; fault trials remain pending.",
}
HDFS_PARAMETERIZED_CLASS_SELECTORS = {"HDFS-11", "HDFS-12", "HDFS-14"}
HEALTHY_PILOT_ATTESTATIONS = {
    "HDFS-43": "data/mallory/calibration_v2/HDFS-43/result.json",
    "HDFS-49": "data/mallory/calibration_v2/HDFS-49/result.json",
    "ZOOKEEPER-11": "Mallory/instrumentation/pilots/zookeeper11/attestation.json",
    "ZOOKEEPER-02": "data/mallory/calibration/ZOOKEEPER-02-03-alternate/healthy/calibration.json",
    "ZOOKEEPER-03": "data/mallory/calibration/ZOOKEEPER-02-03-alternate/healthy/calibration.json",
}
VERIFIED_ALTERNATE_SELECTORS = {
    "HDFS-43": "verified_three_datanode_healthy_alternate",
    "HDFS-49": "verified_snapshot_healthy_alternate",
    "ZOOKEEPER-02": "verified_three_peer_healthy_alternate",
    "ZOOKEEPER-03": "verified_three_peer_healthy_alternate",
}
RECORDED_SELECTOR_STATUSES = {
    "HDFS-43": "oracle_unfit_expected_rejection",
    "HDFS-49": "trace_truncated_before_valid_seed",
    "ZOOKEEPER-02": "oracle_unfit_expected_rejection",
    "ZOOKEEPER-03": "oracle_unfit_expected_rejection",
}


def digest(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None


def revision(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return None


def historical_seed_seconds(row: dict | None) -> float | None:
    if not row:
        return None
    for key in ("healthy_elapsed_seconds", "seed_seconds", "baseline_seconds",
                "healthy_test_elapsed_seconds", "healthy_probe_elapsed_seconds",
                "healthy_seed_seconds"):
        value = row.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    healthy = row.get("healthy")
    if isinstance(healthy, dict):
        value = healthy.get("elapsed_seconds")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        if isinstance(value, list):
            times = [float(item) for item in value if isinstance(item, (int, float)) and item > 0]
            if times:
                return statistics.median(times)
    return None


def index_tests(root: Path) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for path in root.rglob("*.java"):
        if "/src/test/" in str(path):
            result.setdefault(path.stem, []).append(path)
    return result


def parse_selectors(raw: str | None) -> list[dict]:
    result = []
    if not raw:
        return result
    for original in raw.split(";"):
        original = original.strip()
        clean = original.split(" (")[0]
        parameter_variant = None
        match = re.search(r"(?:\[(\d+)\]|\((true|false)\))$", clean)
        if match:
            parameter_variant = match.group(0)
            clean = clean[: match.start()]
        m = METHOD.search(clean)
        if m:
            result.append({"raw": original, "simple_class": m.group("class"),
                           "method": m.group("method"), "parameter_variant": parameter_variant})
    return result


def test_evidence(root: Path, index: dict[str, list[Path]], selector: dict,
                  preferred_path: str | None) -> dict:
    paths = index.get(selector["simple_class"], [])
    if preferred_path:
        preferred = root / preferred_path
        if preferred.is_file() and preferred.stem == selector["simple_class"]:
            paths = [preferred]
    if len(paths) != 1:
        return {**selector, "source_path": None, "resolution":
                "missing_test_source" if not paths else "ambiguous_test_source",
                "candidate_paths": [str(p.relative_to(root)) for p in paths]}
    path = paths[0]
    lines = path.read_text(errors="replace").splitlines()
    package = re.search(r"^\s*package\s+([\w.]+)\s*;", "\n".join(lines), re.M)
    declarations = [i for i, line in enumerate(lines) if re.search(
        r"\b" + re.escape(selector["method"]) + r"\s*\(", line)
        and re.search(r"\b(?:public|protected)\b", line)]
    if len(declarations) == 1:
        offset = declarations[0]
        prefix = "\n".join(lines[max(0, offset - 8):offset])
        annotated = bool(TEST_ANNOTATION.search(prefix))
        # Solr/Lucene's randomized runner also discovers public test* methods.
        test_like = annotated or selector["method"].startswith("test")
        resolution = "test_method_found" if test_like else "method_not_confirmed_test"
        line_number = offset + 1
    else:
        annotated = False
        test_like = False
        resolution = "test_method_missing" if not declarations else "ambiguous_method_declaration"
        line_number = None
    markers = [marker for marker in FIXTURE_MARKERS if marker in "\n".join(lines)]
    return {**selector, "class":
            (package.group(1) + "." if package else "") + selector["simple_class"],
            "selector": ((package.group(1) + "." if package else "")
                         + selector["simple_class"] + "#" + selector["method"]),
            "source_path": str(path.relative_to(root)), "source_sha256": digest(path),
            "method_line": line_number, "has_junit_annotation": annotated,
            "test_like": test_like, "cluster_fixture_markers_in_test_source": markers,
            "resolution": resolution}


def build_recipe(system: str, source_root: Path, test: dict | None,
                 case_id: str) -> dict | None:
    if not test or test.get("resolution") != "test_method_found":
        return None
    module = test["source_path"].split("/src/test/")[0]
    if system == "solr":
        return {"tool": "direct_junit", "cwd": str(SOLR_ISOLATED_ROOT), "module": module,
                "cwd_relative_to_source_root": ".",
                "argv": ["python3", str(SOLR_DIRECT_RUNNER), "{case_id}",
                         "--source", str(SOLR_ISOLATED_ROOT),
                         "--distribution", str(SOURCES["solr"][2]),
                         "--output", "{trial_dir}", "--campaign"],
                "runner_path": str(SOLR_DIRECT_RUNNER),
                "runner_designated_host": "node2",
                "runner_ready_on_designated_host": True,
                "tool_available_on_inventory_host": SOLR_ISOLATED_ROOT.is_dir(),
                "runner_validation_scope": "SOLR-05 JUnit pilot only; each other method requires its own healthy calibration",
                "validated_by_execution": False}
    if system == "hdfs":
        # Surefire's Class#method filter executes zero tests for this JUnit
        # Parameterized class. The class filter is a calibration workload;
        # actual test count and target reach remain runtime gates.
        test_filter = (test["simple_class"] if case_id in HDFS_PARAMETERIZED_CLASS_SELECTORS
                       else test["simple_class"] + "#" + test["method"])
        selected_root = HDFS_LANE2_ROOT if case_id in {"HDFS-43", "HDFS-49"} else HDFS_ISOLATED_ROOT
        return {"tool": "maven", "cwd": str(selected_root), "module": module,
                "cwd_relative_to_source_root": ".",
                "argv": ["mvn", "-B", "-ntp", "-pl", "hadoop-hdfs-project/hadoop-hdfs",
                         "-Dtest=" + test_filter,
                         "-Dsurefire.failIfNoSpecifiedTests=false",
                         *(["-Dtest.build.data={trial_dir}/hdfs-data"]
                           if case_id in {"HDFS-43", "HDFS-49"} else []),
                         "surefire:test"],
                "agent_arg_property": "maven-surefire-plugin.argLine",
                "selector_scope": ("entire_parameterized_class_pending_test_count"
                                   if case_id in HDFS_PARAMETERIZED_CLASS_SELECTORS else "selected_method"),
                "precondition": "isolated source has pinned compiled classes and test-classes",
                "tool_available_on_inventory_host": selected_root.is_dir() and shutil.which("mvn") is not None,
                "validated_by_execution": False}
    if system == "zookeeper":
        return {"tool": "maven", "cwd": str(ZOOKEEPER_ISOLATED_ROOT), "module": module,
                "cwd_relative_to_source_root": ".",
                "argv": ["mvn", "-pl", "zookeeper-server", "-am",
                         "-Dtest=" + test["simple_class"] + "#" + test["method"],
                         "-Dsurefire.failIfNoSpecifiedTests=false", "test"],
                "agent_arg_property": "mallory.agent.arg",
                "tool_available_on_inventory_host": ZOOKEEPER_ISOLATED_ROOT.is_dir() and shutil.which("mvn") is not None,
                "validated_by_execution": False}
    if system == "hbase":
        receipt_path = HBASE_RECEIPT if case_id == "HBASE-01" else HBASE_LANE2_RECEIPT
        receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
        classpath = (receipt.get("classpath_template") if case_id == "HBASE-01"
                     else next((arg for i, arg in enumerate(receipt.get("command_template", []))
                                if i and receipt["command_template"][i - 1] == "-cp"), None))
        selected_root = (source_root if case_id == "HBASE-01"
                         else Path(receipt.get("source_equivalent_root", source_root)))
        command = (["/usr/lib/jvm/java-8-openjdk-amd64/bin/java", "-ea", "-Xmx4g",
                    "-Djava.io.tmpdir={trial_dir}",
                    "-Dtest.build.data.basedirectory={trial_dir}", "-cp", classpath,
                    receipt.get("runner", "edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit"),
                    test["class"], test["method"]] if classpath else [])
        return {"tool": "direct_junit", "cwd": str(selected_root), "module": module,
                "cwd_relative_to_source_root": ".", "argv": command,
                "runner_designated_host": "node1",
                "runtime_root": str(HBASE_RUNTIME_ROOT if case_id == "HBASE-01"
                                    else receipt.get("runtime_root", HBASE_RUNTIME_ROOT)),
                "receipt": str(receipt_path),
                "runner_ready_on_designated_host": bool(
                    (receipt.get("runner_ready_for_calibration")
                     or receipt.get("status") == "runner_ready_for_case_calibration") and command),
                "tool_available_on_inventory_host": False,
                "runner_validation_scope": "HBASE-01 healthy closure pilot only; other selectors require their own healthy calibration",
                "validated_by_execution": False}
    return {"tool": "maven", "cwd": str(source_root), "module": module,
            "cwd_relative_to_source_root": ".",
            "argv": ["mvn", "-pl", module, "-am",
                     "-Dtest=" + test["simple_class"] + "#" + test["method"],
                     "-Dsurefire.failIfNoSpecifiedTests=false", "test"],
            "tool_available_on_inventory_host": shutil.which("mvn") is not None,
            "validated_by_execution": False}


def case_entry(site: dict, historical: dict | None, roots: dict,
               indexes: dict, control: bool = False) -> dict:
    system = site["system"]
    version, source_root, distribution_root = SOURCES[system]
    selected_test = historical.get("cluster_test") if historical else None
    selector_source = "legacy_executed_test" if selected_test else "selection_proposed_test"
    raw = selected_test or site.get("proposed_cluster_test")
    inference = INFERRED_TESTS.get(site["case_id"])
    if not raw and inference:
        raw = inference["selector"]
        selector_source = "source_inspection_candidate"
    selectors = parse_selectors(raw)
    if not selectors and site.get("proposed_cluster_test") != raw:
        selector_source = "selection_proposed_test"
        selectors = parse_selectors(site.get("proposed_cluster_test"))
    tests = [test_evidence(source_root, indexes[system], s,
                           site.get("proposed_cluster_test_path")) for s in selectors]
    alternate = ALTERNATE_TESTS.get(site["case_id"])
    alternate_tests = ([test_evidence(source_root, indexes[system], s, None)
                        for s in parse_selectors(alternate["selector"])]
                       if alternate else [])
    selected = next((t for t in tests if t["resolution"] == "test_method_found"), None)
    if site["case_id"] in VERIFIED_ALTERNATE_SELECTORS:
        selected = next((t for t in alternate_tests if t["resolution"] == "test_method_found"), None)
        selector_source = VERIFIED_ALTERNATE_SELECTORS[site["case_id"]]
        tests += alternate_tests
    source_file = source_root / site["source_path"]
    source_lines = source_file.read_text(errors="replace").splitlines() if source_file.is_file() else []
    source_line = site.get("source_line")
    source_at_line = (source_lines[source_line - 1].strip()
                      if isinstance(source_line, int) and 0 < source_line <= len(source_lines)
                      else None)
    if selected:
        eligibility = "mapped_test_pending_healthy_calibration"
    elif tests:
        eligibility = "mapped_test_unresolved"
    else:
        eligibility = "no_mapped_cluster_test"
    return {
        "case_id": site["case_id"], "system": system, "system_version": version,
        "cohort": "known_issue_control" if control else "original_102",
        "target": {key: site.get(key) for key in (
            "site_id", "source_path", "source_line", "function", "check_code",
            "target_guard", "target_throw", "target_exception")}
        | {"source_line_text": source_at_line, "source_sha256": digest(source_file)},
        "workload": {"selector_source": selector_source, "recorded_selector": raw,
                     "recorded_selector_status": RECORDED_SELECTOR_STATUSES.get(site["case_id"]),
                     "healthy_pilot_attestation": HEALTHY_PILOT_ATTESTATIONS.get(site["case_id"]),
                     "mapping_evidence": inference["evidence"] if inference else None,
                     "source_oracle_warning": SOURCE_ORACLE_WARNINGS.get(site["case_id"]),
                     "alternate_test_candidates": alternate_tests,
                     "alternate_mapping_evidence": alternate["evidence"] if alternate else None,
                     "candidates": tests, "selected_selector": selected["selector"] if selected else None,
                     "test_class": selected["class"] if selected else None,
                     "test_method": selected["method"] if selected else None,
                     "test_source_path": selected["source_path"] if selected else None,
                     "parameter_variant_note": (
                         "Build selector runs all parameterized variants; bind target occurrence during calibration."
                         if selected and selected.get("parameter_variant") else None)},
        "eligibility": {"state": eligibility,
                        "may_attempt_seed": selected is not None,
                        "cluster_and_target_reach_verified_for_mallory": False,
                        "historical_status_is_not_eligibility": True},
        "build": build_recipe(system, source_root, selected, site["case_id"]),
        "provenance": {"selection_file": "data/crashfuzz/selection102.json",
                       "historical_result_file": "data/crashfuzz/checklist102.json",
                       "source_root": str(source_root), "source_commit": roots[system],
                       "source_root_env": "MALLORY_" + system.upper() + "_SOURCE_ROOT",
                       "distribution_root": str(distribution_root),
                       "distribution_root_env": "MALLORY_" + system.upper() + "_DIST_ROOT",
                       "source_file_exists": source_file.is_file(),
                       "historical_seed_seconds": historical_seed_seconds(historical),
                       "historical_crashfuzz_status": historical.get("status") if historical else None,
                       "historical_crashfuzz_test": selected_test,
                       "historical_exclusion_reason": historical.get("reason") if historical else None},
    }


def main() -> None:
    selection = json.loads((LEGACY / "selection102.json").read_text())
    history = {row["case_id"]: row for row in json.loads(
        (LEGACY / "checklist102.json").read_text())["rows"]}
    assert selection["count"] == 102 and len(selection["checks"]) == 102
    assert len({item["case_id"] for item in selection["checks"]}) == 102
    roots = {name: revision(source_root) for name, (_, source_root, _) in SOURCES.items()}
    indexes = {name: index_tests(source_root) for name, (_, source_root, _) in SOURCES.items()}
    entries = [case_entry(site, history.get(site["case_id"]), roots, indexes)
               for site in selection["checks"]]
    controls = [case_entry(site, history.get(site["case_id"]), roots, indexes, True)
                for site in selection.get("additional_known_issue_checks", [])]
    assert len(entries) == 102 and len(controls) == 2
    assert all(entry["provenance"]["source_file_exists"] for entry in entries)
    result = {"schema_version": 1,
              "description": "Static inventory only; no Mallory test execution is claimed.",
              "count": len(entries), "eligibility_counts": dict(Counter(
                  item["eligibility"]["state"] for item in entries)),
              "cases": entries, "known_issue_controls": controls}
    output = HERE / "inventory.json"
    # Preserve current mapping audit when regenerating an otherwise identical
    # inventory. This prevents a transient downgrade before generate.py runs.
    if output.is_file():
        old = json.loads(output.read_text())
        old_by_id = {row["case_id"]: row for row in old.get("cases", [])}
        for row in entries:
            previous = old_by_id.get(row["case_id"])
            if (previous and previous["target"]["source_sha256"] == row["target"]["source_sha256"]
                    and previous["workload"].get("selected_selector") == row["workload"].get("selected_selector")
                    and previous["workload"].get("test_source_path") == row["workload"].get("test_source_path")
                    and previous["build"] == row["build"]
                    and "bytecode_mapping_status" in previous["eligibility"]):
                row["eligibility"] = previous["eligibility"]
        result["eligibility_counts"] = dict(Counter(
            item["eligibility"]["state"] for item in entries))
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, output)
    print(output, result["eligibility_counts"])


if __name__ == "__main__":
    main()
