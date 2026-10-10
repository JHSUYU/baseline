#!/usr/bin/env python3
"""JVM-free source, receipt, runtime, and full-budget checks for HBASE-19/20."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
TARGET_CLASS = "org/apache/hadoop/hbase/master/procedure/ModifyTableProcedure.class"
TARGET_SHA = "a8fa60a60a2d7731d02a3eb829b9ddfd6d3e67932f3e17b7f831b78211a0c4b1"
TEST_SHA = "eca1ba9410c4a42de82594fdb4b08f8515289ffe8225332f0699ed7f1233d17e"
SOURCE_SHA = "186e34a72dcffdbe853abaa0068ca0af6e899f44e28005710301688bbbdaf7b3"
SERVICE_SHA = "4c716b4daa5fb63a7fed6de425bc5706e525f7098dd74f19d7391d4e0e936942"
SOURCE_COMMIT = "d5f63f523c065f963992ea4e74db268d17816631"
SELECTOR = ("org.apache.hadoop.hbase.master.procedure.TestModifyTableProcedure"
            "#testModifyTableWithCoprocessorAndColumnFamilyPropertyChange")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def check(path: Path, expected: str) -> None:
    require(path.is_file(), f"missing {path}")
    require(sha(path) == expected, f"SHA mismatch: {path}")


def check_case(number: int) -> None:
    case = f"HBASE-{number}"
    config_path = HERE / f"{case}.descriptor-read-v1.full.json"
    config = json.loads(config_path.read_text())
    site_path = HERE / "sites" / f"{case}.sites.json"
    sites = json.loads(site_path.read_text())
    receipt = json.loads((HERE / "stage-receipt.json").read_text())
    check(config_path, receipt["configs"][case])
    check(site_path, receipt["sites"][case])
    check(HERE / "runtime/conf/hbase-site.xml", receipt["xerial_conf_sha256"])
    check(HERE / "run_full.sh", receipt["runner_sha256"])
    check(Path(__file__), receipt["preflight_sha256"])

    release = Path(config["core_release"]["path"])
    check(release / "manifest.json", config["core_release"]["manifest_sha256"])
    require(release.name == config["core_release"]["release_id"], "core release ID")
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import validate_config  # pylint: disable=import-outside-toplevel
    validate_config(config)

    require(config["case_id"] == case and config["cluster_test"] == SELECTOR,
            "case or selected MiniHBaseCluster test changed")
    require(config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["budget"] == {"trials": 80, "seconds": 3600,
                                 "max_faults_per_trial": 3,
                                 "trial_timeout_seconds": 600},
            "full campaign budget or healthy promotion changed")
    require(config["fault_types"] == ["EXCEPTION"] and
            config["explore_outside_closure"] is True and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False and
            config["agent_properties"]["auto.io.doors"] is False,
            "fault model or graph policy changed")
    require(config["site_file"] == str(site_path), "site path changed")
    require(config["agent_include"] == [
        "org.apache.hadoop.hbase.master.procedure.ModifyTableProcedure",
        "org.apache.hadoop.hbase.master.MasterRpcServices",
        "org.apache.hadoop.hbase.ipc.RpcServer"], "instrumented classes changed")
    require(sites["doors"] == [{"clazz": "org.apache.hadoop.hbase.master.MasterRpcServices",
                                   "method": "getTableDescriptors", "line": 1114,
                                   "exception_class": "java.io.IOException"}],
            "descriptor-read I/O door changed")
    require(config["static_fault_locations"] == [
        {"class": "org.apache.hadoop.hbase.master.MasterRpcServices",
         "method": "getTableDescriptors", "line": 1114}], "pretarget candidate changed")
    require(config["target"]["check_sites"] == [receipt["targets"][case]["check"]] and
            config["target"]["throw_site"] == receipt["targets"][case]["throw"] and
            config["target"]["exception_class"] == "org.apache.hadoop.hbase.HBaseIOException",
            "exact selected target changed")
    require(sites["targets"][0]["line"] == (133 if number == 19 else 138) and
            sites["targets"][1]["line"] == (135 if number == 19 else 139),
            "site lines changed")

    source = Path(config["source_equivalent_root"])
    require(source == Path(config["cwd"]), "source and working tree differ")
    target_source = source / config["target"]["source_path"]
    test_source = source / "hbase-server/src/test/java/org/apache/hadoop/hbase/master/procedure/TestModifyTableProcedure.java"
    service_source = source / "hbase-server/src/main/java/org/apache/hadoop/hbase/master/MasterRpcServices.java"
    check(target_source, SOURCE_SHA)
    check(test_source, TEST_SHA)
    check(service_source, receipt["service_source_sha256"])
    service_lines = service_source.read_text().splitlines()
    require("master.listTableDescriptors" in service_lines[1113], "line 1114 lost descriptor read")
    require("catch (IOException ioe)" in "\n".join(service_lines[1122:1126]),
            "service IOException conversion changed")
    require("getDescriptor(tableName)" in test_source.read_text().splitlines()[736],
            "selected test lost pretarget descriptor read")
    require(config["mapping"]["source_commit"] == SOURCE_COMMIT,
            "source commit pin changed")

    dist = Path(config["mapping"]["distribution_root"])
    with zipfile.ZipFile(dist / "lib/hbase-server-2.6.6.jar") as jar:
        require(hashlib.sha256(jar.read(TARGET_CLASS)).hexdigest() == TARGET_SHA,
                "target bytecode changed")
        require(hashlib.sha256(jar.read(
            "org/apache/hadoop/hbase/master/MasterRpcServices.class")).hexdigest() ==
            SERVICE_SHA, "descriptor-read service bytecode changed")
    require(config["expected_target_class_sha256"] == TARGET_SHA,
            "expected target class pin changed")
    for artifact in config["runtime_artifacts"]:
        check(Path(artifact["path"]), artifact["sha256"])
    require(config["agent_jar"] in [row["path"] for row in config["runtime_artifacts"]],
            "agent is not pinned")

    prior = BASE / f"data/mallory/calibration_v8/{case}"
    check(prior / "result.json", config["mapping"]["prior_healthy_result_sha256"])
    check(prior / "offline-causal-audit.json", config["mapping"]["prior_healthy_audit_sha256"])
    result = json.loads((prior / "result.json").read_text())
    audit = json.loads((prior / "offline-causal-audit.json").read_text())
    require(result["cluster_test"] == SELECTOR and result["healthy_seed_valid"] is True
            and result["healthy_junit_validation"]["succeeded"] == 1
            and result["exact_exception_trials"] == 0,
            "v8 exact guard/JUnit proof changed")
    require(audit["healthy_observed_path_doors"] == 0 and
            audit["healthy_closure_observed_edges"] == 0,
            "v8 graph finding changed")
    print(f"PASS {case}: source, class, receipts, exact target, full budget; fresh r0000 required")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=("19", "20", "all"), nargs="?", default="all")
    selected = parser.parse_args().case
    tree = ET.parse(HERE / "runtime/conf/hbase-site.xml")
    properties = {entry.findtext("name"): entry.findtext("value")
                  for entry in tree.getroot().findall("property")}
    require(properties == {"hbase.io.compress.snappy.codec":
                           "org.apache.hadoop.hbase.io.compress.xerial.SnappyCodec"},
            "Xerial codec override changed")
    for number in ((19, 20) if selected == "all" else (int(selected),)):
        check_case(number)


if __name__ == "__main__":
    main()
