#!/usr/bin/env python3
"""Offline source, selector and runtime-artifact checks for SOLR-39 Dimensional."""

import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = (ROOT / "Mallory/dispatch/releases/"
           "4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4")
SOLR_ADAPTERS = HERE.parents[2]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
SELECTOR = "org.apache.solr.update.processor.DimensionalRoutedAliasUpdateProcessorTest#testTimeCat"
CHECK = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
         "#lookupShardLeadersOfCollections()Ljava/util/List;@246:branch:1")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def inspect() -> dict:
    config = json.loads((HERE / "config.json").read_text())
    inventory = json.loads((HERE / "inventory.json").read_text())
    pins = json.loads((HERE / "pins.json").read_text())
    for name, expected in pins["files"].items():
        path = Path(name) if name.startswith("/") else ROOT / name
        require(path.is_file() and sha(path) == expected, f"pin changed: {name}")
    require(config["case_id"] == "SOLR-39" and config["calibration_only"] is True,
            "not a healthy-only SOLR-39 config")
    require(config["cluster_test"] == SELECTOR and config["target"]["check_sites"] == [CHECK],
            "selector or exact target changed")
    require(config["command"][1] == str(HERE / "run_pilot.py") and
            config["command"][2] == "SOLR-39" and "--campaign" in config["command"],
            "case-local runner not selected")
    require(config["env"]["MALLORY_SOLR_AWAITSFIX"] == "1" and
            "solr.disableConfigSetsCreateAuthChecks=true" in config["env"]["JAVA_TOOL_OPTIONS"],
            "required unchanged JUnit fixtures absent")
    require(config["env"]["MALLORY_ALIAS_REF_TRACE"] == "1" and
            "AliasValueTransformer" in config["agent_properties"]["adapter.transformers"],
            "per-event aliases-reference telemetry absent")
    require(len(inventory["cases"]) == 1 and
            inventory["cases"][0]["workload"]["selected_selector"] == SELECTOR,
            "isolated selector inventory changed")
    sys.path.insert(0, str(SOLR_ADAPTERS))
    import solr_junit_runner_v14 as runner  # noqa: E402
    runner.INVENTORY = HERE / "inventory.json"
    require(runner.selected_test("SOLR-39")[:2] == (SELECTOR.split("#")[0], "testTimeCat"),
            "case-local selector not accepted by existing runner")
    test = SOURCE / inventory["cases"][0]["workload"]["test_source_path"]
    target = SOURCE / config["target"]["source_path"]
    test_lines, target_lines = test.read_text().splitlines(), target.read_text().splitlines()
    require("configureCluster(4).configure()" in test.read_text() and
            "public void testTimeCat()" in test.read_text() and
            "createDimensionalRoutedAlias" in test.read_text() and
            "addDocsAndCommit(true" in test.read_text(), "Dimensional workload source changed")
    require("if (collections == null)" in target_lines[245] and
            "newAliasMustExistException" in target_lines[246], "target source changed")
    with zipfile.ZipFile(Path(config["mapping"]["compiled_jar"])) as jar:
        bytecode = jar.read("org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class")
    require(hashlib.sha256(bytecode).hexdigest() == config["expected_target_class_sha256"],
            "compiled target class changed")
    alias_adapter = Path(config["agent_properties"]["adapter.jars"].split(",")[-1])
    with zipfile.ZipFile(alias_adapter) as jar:
        require("edu/uva/liftlab/mallory/solr/aliasref/AliasValueTransformer.class"
                in jar.namelist(), "exact-reference adapter missing")
    for item in config["runtime_artifacts"]:
        path = Path(item["path"])
        require(path.is_file() and sha(path) == item["sha256"],
                f"runtime artifact changed: {path}")
    sys.path.insert(0, str(RELEASE))
    from Mallory.core import campaign, junit  # noqa: E402
    require(Path(campaign.__file__).resolve().is_relative_to(RELEASE),
            "pinned controller release unavailable")
    require(junit.runner_kind(config["command"]) == "solr_junit_wrapper",
            "case-local JUnit entry point is not recognized")
    campaign.validate_config(config)
    return {"case_id": "SOLR-39", "mode": "healthy", "host": "node1",
            "config_sha256": sha(HERE / "config.json"),
            "inventory_sha256": sha(HERE / "inventory.json"),
            "pins_sha256": sha(HERE / "pins.json"),
            "runner_sha256": sha(HERE / "run_healthy.py"),
            "selector_runner_sha256": sha(HERE / "run_pilot.py"),
            "agent_sha256": sha(Path(config["agent_jar"])),
            "intended_output": str(ROOT / "data/mallory/calibration_solr39_dimensional_healthy_v2_node1/SOLR-39"),
            "jvm_run": False, "status": "offline_preflight_passed"}


if __name__ == "__main__":
    print(json.dumps(inspect(), indent=2, sort_keys=True))
