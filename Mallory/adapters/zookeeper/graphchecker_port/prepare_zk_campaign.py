#!/usr/bin/env python3
"""Prepare an original ZooKeeper cluster JUnit for a quorum/epoch campaign.

The case inventory supplies the check and exact IOException throw. Soot
discovers fault doors and coverage sites without a per-case I/O list.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from run_original_junit_smoke import BASE, HERE, surefire_classpath
from verify_source import verify


# These are source check-line anchors, not injection sites. The exact THROW
# line, method and original JUnit selector come from cases/inventory.json.
CHECK_LINES = {
    "ZOOKEEPER-05": 98,
    "ZOOKEEPER-06": 1471,
    "ZOOKEEPER-07": 515,
    "ZOOKEEPER-11": 1169,
    "ZOOKEEPER-12": 1193,
}


def case_spec(case_id: str, source: Path) -> tuple[dict, str, str, str, str]:
    inventory = json.loads((BASE / "Mallory/cases/inventory.json").read_text())
    matches = [item for item in inventory["cases"] if item["case_id"] == case_id]
    if len(matches) != 1 or case_id not in CHECK_LINES:
        raise ValueError(f"unsupported ZooKeeper quorum/epoch case: {case_id}")
    item = matches[0]
    target = item["target"]
    selector = item["workload"].get("selected_selector")
    if not isinstance(selector, str) or selector.count("#") != 1:
        raise ValueError(f"case lacks one selected original JUnit: {case_id}")
    junit_class, junit_method = selector.split("#")
    source_file = source / target["source_path"]
    if hashlib.sha256(source_file.read_bytes()).hexdigest() != target["source_sha256"]:
        raise ValueError(f"source hash differs from pinned inventory: {source_file}")
    function = target["function"].split("(", 1)[0]
    clazz, method = function.rsplit(".", 1)
    return target, clazz, method, junit_class, junit_method


def existing(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def classpath_file(path: Path) -> list[str]:
    return [item for item in path.read_text(encoding="utf-8").strip().split(":") if item]


def original_junit_classpath(report: Path, source: Path) -> list[str]:
    """Relocate only the original source build entries from Surefire XML.

    A pristine ZooKeeper checkout may be copied to a persistent campaign
    directory after its original JUnit run. Surefire retains absolute paths
    to the checkout used for that run; dependency JAR paths stay unchanged.
    """
    suite = ET.parse(report).getroot()
    basedirs = [p.get("value") for p in suite.findall("properties/property")
                if p.get("name") == "basedir"]
    if len(basedirs) != 1 or not basedirs[0]:
        raise ValueError(f"Surefire report has no unique basedir: {report}")
    report_source = Path(basedirs[0]).resolve().parent
    result = []
    for item in surefire_classpath(report).split(":"):
        if not item:
            continue
        path = Path(item)
        try:
            relative = path.relative_to(report_source)
        except ValueError:
            result.append(item)
            continue
        relocated = source / relative
        if not relocated.exists():
            raise FileNotFoundError(f"relocated JUnit classpath entry: {relocated}")
        result.append(str(relocated))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("--case-id", choices=sorted(CHECK_LINES),
                        default="ZOOKEEPER-07")
    parser.add_argument("--scope-jar", required=True, type=Path)
    parser.add_argument("--weaver-jar", required=True, type=Path)
    parser.add_argument("--runtime-jar", required=True, type=Path)
    parser.add_argument("--analyzer-jar", type=Path,
                        help="standalone streaming TrialGraph analyzer; defaults to runtime jar")
    parser.add_argument("--adapter-classes", type=Path, default=HERE / "target/classes")
    parser.add_argument("--verified-constructor-doors", action="store_true",
                        help="select resource-opening constructor doors after verifier validation")
    parser.add_argument("--fault-trials", type=int, default=8)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--max-faults", type=int, default=3)
    args = parser.parse_args()

    source = args.source_root.resolve()
    scratch = args.scratch.resolve()
    verify(source)
    target_info, target_class, target_method, junit_class, junit_method = case_spec(
        args.case_id, source)
    if scratch.exists() and any(scratch.iterdir()):
        raise ValueError(f"scratch must be empty: {scratch}")
    scratch.mkdir(parents=True, exist_ok=True)
    scope_jar = existing(args.scope_jar, "static planner jar")
    weaver_jar = existing(args.weaver_jar, "weaver jar")
    runtime_jar = existing(args.runtime_jar, "runtime jar")
    analyzer_jar = (existing(args.analyzer_jar, "analyzer jar")
                    if args.analyzer_jar else runtime_jar)
    adapter_classes = args.adapter_classes.resolve()
    main_classes = source / "zookeeper-server/target/classes"
    if not adapter_classes.is_dir() or not main_classes.is_dir():
        raise FileNotFoundError("build the ZooKeeper source and this adapter first")
    adapter_dependencies = existing(HERE / "target/dependency-classpath.txt",
                                    "adapter dependency classpath")
    scope_dependencies = existing(BASE / "Mallory/static_scope_port/target/classpath.txt",
                                  "static planner dependency classpath")
    reports = source / "zookeeper-server/target/surefire-reports"
    report = reports / ("TEST-" + junit_class + ".xml")
    if not report.is_file():
        # Both selected tests are in zookeeper-server. A preexisting original
        # QuorumRestartTest report pins the same module's complete Surefire CP;
        # healthy calibration below still executes this case's own JUnit.
        report = reports / "TEST-org.apache.zookeeper.test.QuorumRestartTest.xml"
    report = existing(report, "original module Surefire classpath report")

    tool_cp = [str(weaver_jar), str(runtime_jar), str(adapter_classes),
               *classpath_file(adapter_dependencies)]
    test_cp = original_junit_classpath(report, source)
    exact_cp = [*tool_cp, str(main_classes), *test_cp]
    scope_input = {
        "case_id": args.case_id,
        "target": {"class": target_class,
                   "method": target_method,
                   "line": target_info["source_line"], "kind": "THROW",
                   "exception": target_info["target_exception"],
                   "check_line": CHECK_LINES[args.case_id]},
        "analysis": {"process_dirs": [str(main_classes)], "classpath": exact_cp,
                     "constructor_io_doors_verified": args.verified_constructor_doors,
                     # Only these actor objects are registered by the
                     # ZooKeeper bridge. Helper objects in the same package
                     # (for example MultipleAddresses and QuorumMaj) inherit
                     # the active request owner instead of claiming `this`.
                     "source_owner_classes": [
                         r"org\.apache\.zookeeper\.server\.quorum\."
                         r"(?:QuorumPeer|Learner|Follower|Leader|LearnerHandler)"]},
    }
    input_path = scratch / "scope-input.json"
    input_path.write_text(json.dumps(scope_input, indent=2) + "\n", encoding="utf-8")
    scope_dir = scratch / "scope"
    scope_cp = ":".join([str(scope_jar), *classpath_file(scope_dependencies)])
    with (scratch / "scope.log").open("w", encoding="utf-8") as log:
        subprocess.run(["java", "-Xmx5g", "-cp", scope_cp,
                        "edu.uva.liftlab.mallory.scope.ScopePlanner",
                        str(input_path), str(scope_dir)], stdout=log,
                       stderr=subprocess.STDOUT, timeout=300, check=True)
    manifest = json.loads((scope_dir / "weave_manifest.json").read_text())
    selected = [row for row in manifest.get("targets", [])
                if row.get("clazz") == target_class
                and row.get("method") == target_method]
    checks = [row for row in selected if row.get("kind") == "BRANCH"]
    throws = [row for row in selected if row.get("kind") == "THROW"]
    if (not checks or len(throws) != 1
            or throws[0].get("line") != target_info["source_line"]
            or throws[0].get("exceptionClass") != target_info["target_exception"]
            or len({row.get("descriptor") for row in selected}) != 1):
        raise ValueError(f"static planner did not select exact check and throw: {selected}")

    tmp = scratch / "junit-tmp"
    test_data = scratch / "junit-data"
    tmp.mkdir()
    test_data.mkdir()
    config = {
        "schema_version": 1, "case_id": args.case_id,
        "junit": {"class": junit_class, "method": junit_method},
        "target": {"check_site_id": checks[0]["siteId"],
                   "check_site_ids": [row["siteId"] for row in checks],
                   "throw_site_id": throws[0]["siteId"],
                   "exception_class": target_info["target_exception"]},
        "weave_manifest": str(scope_dir / "weave_manifest.json"),
        "static_scope_map": str(scope_dir / "static_scope_map.jsonl"),
        "original_class_dirs": [str(main_classes)],
        "tool_classpath": tool_cp, "test_classpath": test_cp,
        "graph_jar": str(analyzer_jar), "cwd": str(source),
        "timeout_seconds": 180,
        "budget": {"fault_trials": args.fault_trials, "seconds": args.seconds,
                   "max_faults_per_trial": args.max_faults},
        "runner": {
            "main_class": "edu.uva.liftlab.mallory.graphchecker.causynth.OriginalJUnitMethodMain",
            "args": ["{class}", "{method}"],
            "jvm_args": ["-Xmx3g", f"-Djava.io.tmpdir={tmp}",
                         f"-Dbuild.test.dir={test_data}",
                         "-Dtest.junit.threads=16", "-Dzookeeper.junit.threadid=13"]},
        "post_weave": {
            "main_class": "edu.uva.liftlab.mallory.graphchecker.causynth.WeaveZooKeeperMain",
            "jvm_args": ["-Xmx4g"],
            "args": ["{generic_woven}", "{classpath}", "{final_woven}",
                     str(scope_dir / "weave_manifest.json")]},
    }
    config_path = scratch / "campaign-config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(config_path)


if __name__ == "__main__":
    main()
