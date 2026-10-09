"""Offline validation for unchanged routed-alias JUnit tests with a configset policy overlay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from Mallory.core.campaign import validate_config
from Mallory.dispatch.prepare_solr_lane import lane_config

CASES = ("SOLR-10", "SOLR-13", "SOLR-39", "SOLR-40")
ADAPTER_CASES = ROOT / "Mallory/adapters/solr/cases"
REPORT = ROOT / "Mallory/cases/revisions/SOLR-routed-alias-configset-auth-v1.validation.json"
ISOLATED_LANE_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/solr-routed-alias-v23")
POLICY_OPTION = "-Dsolr.disableConfigSetsCreateAuthChecks=true"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    handler_source = ROOT / "Mallory/cases/revisions/SOLR-10-source-review-no-suitable-test-v1.json"
    source_root = Path(json.loads(handler_source.read_text())["source_root"])
    handler = source_root / "solr/core/src/java/org/apache/solr/handler/admin/ConfigSetsHandler.java"
    base_test = source_root / "solr/core/src/test/org/apache/solr/update/processor/RoutedAliasUpdateProcessorTest.java"
    runner = ROOT / "Mallory/adapters/solr/solr_junit_runner_v8.py"
    controller = ROOT / "Mallory/core/campaign.py"
    handler_text = handler.read_text()
    base_text = base_test.read_text()
    runner_text = runner.read_text()
    controller_text = controller.read_text()
    assert 'Boolean.getBoolean("solr.disableConfigSetsCreateAuthChecks")' in handler_text
    assert '!DISABLE_CREATE_AUTH_CHECKS' in handler_text
    assert '.setBaseConfigSetName("_default")' in base_text
    assert 'build_env.pop("JAVA_TOOL_OPTIONS", None)' in runner_text
    assert 'subprocess.run(command, cwd=source' in runner_text
    assert 'env.get("JAVA_TOOL_OPTIONS", "") + " " + option' in controller_text
    compiled = Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist/solr-core-8.11.4.jar")
    with ZipFile(compiled) as archive:
        handler_class = archive.read("org/apache/solr/handler/admin/ConfigSetsHandler.class")
    assert b"solr.disableConfigSetsCreateAuthChecks" in handler_class

    rows = []
    for case in CASES:
        base_path = ADAPTER_CASES / case / "config-v10-lane1-junit.json"
        staged_path = ADAPTER_CASES / case / "config-v23-configset-auth-healthy.json"
        base = json.loads(base_path.read_text())
        staged = json.loads(staged_path.read_text())
        schema_copy = dict(staged)
        schema_copy["cwd"] = str(source_root)  # the actual pinned worktree is offhost
        validate_config(schema_copy)
        assert staged["env"]["JAVA_TOOL_OPTIONS"] == POLICY_OPTION
        assert staged["env"]["MALLORY_SOLR_AWAITSFIX"] == "1"
        assert staged["calibration_only"] is True
        assert staged["auto_promote_if_healthy"] is False
        assert staged["budget"]["trials"] == 1
        for key in ("case_id", "system", "cluster_test", "command", "cwd", "site_file",
                    "target", "agent_include", "agent_jar", "agent_properties", "runtime_artifacts"):
            assert staged[key] == base[key], (case, key)
        for key, value in base["env"].items():
            assert staged["env"][key] == value, (case, key)
        assert set(staged["env"]) == set(base["env"]) | {"JAVA_TOOL_OPTIONS"}
        lane = lane_config(staged, ISOLATED_LANE_ROOT)
        assert lane["cwd"] == lane["source_equivalent_root"] == str(ISOLATED_LANE_ROOT)
        assert str(ISOLATED_LANE_ROOT) in lane["command"]
        assert lane["cluster_test"] == staged["cluster_test"]
        rows.append({
            "case_id": case,
            "selector": staged["cluster_test"],
            "base_config_sha256": sha(base_path),
            "staged_config_sha256": sha(staged_path),
            "isolated_lane_source_path": str(ISOLATED_LANE_ROOT),
            "isolated_lane_config_sha256_if_prepared": hashlib.sha256(
                (json.dumps(lane, sort_keys=True, indent=2) + "\n").encode()).hexdigest(),
        })
    report = {
        "schema_version": 1,
        "revision": "SOLR-routed-alias-configset-auth-v1",
        "status": "offline_validated_lane_admission_and_healthy_jvm_pending",
        "scope": "Config-only healthy probe; original JUnit selectors, test source, target sites, agent, and adapter unchanged",
        "policy_option": POLICY_OPTION,
        "policy_source_sha256": sha(handler),
        "fixture_source_sha256": sha(base_test),
        "runner_sha256": sha(runner),
        "controller_sha256": sha(controller),
        "compiled_jar_sha256": sha(compiled),
        "compiled_handler_has_policy_option": True,
        "controller_appends_javaagent_to_java_tool_options": True,
        "test_compilation_removes_java_tool_options": True,
        "cases": rows,
        "limitation": "The policy option has not been run in the routed-alias JUnit. A fresh isolated-lane healthy trial must pass JUnit and report named exact target checks with an untruncated, audited trace before any source-only receipt is superseded.",
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(REPORT)


if __name__ == "__main__":
    main()
