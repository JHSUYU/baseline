#!/usr/bin/env python3
"""Prepare a GraphChecker HDFS case from the reviewed 102-check inventory.

The inventory identifies the original JUnit and target throw. Soot selects
the backward scope and every I/O door; this script never lists fault sites.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


SOURCE_OWNERS = [
    r"^org\.apache\.hadoop\.hdfs\.server\.datanode\.DataNode$",
    r"^org\.apache\.hadoop\.hdfs\.server\.namenode\.NameNode$",
]


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to replace {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def inventory_case(path: Path, case_id: str) -> dict:
    rows = read_json(path).get("cases", [])
    matches = [row for row in rows if row.get("case_id") == case_id
               and row.get("system") == "hdfs"]
    if len(matches) != 1:
        raise ValueError(f"expected one HDFS inventory row for {case_id}")
    row = matches[0]
    if not row.get("eligibility", {}).get("may_attempt_seed"):
        raise ValueError(f"{case_id} has no eligible original cluster test")
    selector = row.get("workload", {}).get("selected_selector")
    if not isinstance(selector, str) or selector.count("#") != 1:
        raise ValueError(f"{case_id} has no unique original JUnit selector")
    return row


def target_identity(row: dict) -> tuple[str, str, int, str, list[int]]:
    target = row["target"]
    function = target.get("function", "")
    prefix = function.split("(", 1)[0]
    if "." not in prefix:
        raise ValueError("target.function needs a qualified class and method")
    clazz, method = prefix.rsplit(".", 1)
    line = target.get("source_line")
    exception = target.get("target_exception")
    if not isinstance(line, int) or line <= 0 or not isinstance(exception, str):
        raise ValueError("target throw needs source line and exception class")
    checks = target.get("runtime_mapping", {}).get("check_sites", [])
    check_lines = []
    for check in checks:
        match = re.search(r"@(\d+):branch:\d+$", check)
        if not match:
            raise ValueError(f"unmapped branch anchor: {check}")
        check_lines.append(int(match.group(1)))
    if not check_lines:
        raise ValueError("inventory has no mapped check branch")
    return clazz, method, line, exception, sorted(set(check_lines))


def exact_classpath(path: Path) -> list[str]:
    entries = path.read_text(encoding="utf-8").strip().split(":")
    if not entries or any(not entry or not Path(entry).is_absolute()
                          or not Path(entry).exists() for entry in entries):
        raise ValueError("exact classpath has a missing or nonabsolute entry")
    return entries


def scope_input(args: argparse.Namespace) -> None:
    row = inventory_case(args.inventory, args.case_id)
    clazz, method, line, exception, checks = target_identity(row)
    cp = exact_classpath(args.classpath_file)
    if not args.classes.is_dir() or str(args.classes.resolve()) != cp[0]:
        raise ValueError("first exact classpath entry must be the merged process directory")
    # A THROW target makes ScopePlanner retain all controlling guards. This
    # includes the two-branch HDFS inventory checks without choosing one here.
    plan = {
        "case_id": args.case_id,
        "target": {"class": clazz, "method": method, "line": line,
                   "kind": "THROW", "exception": exception},
        "analysis": {"process_dirs": [str(args.classes.resolve())],
                     "classpath": cp,
                     "source_owner_classes": SOURCE_OWNERS},
    }
    write_json(args.out, plan)
    write_json(args.out.with_name("expected-anchors.json"), {
        "case_id": args.case_id,
        "inventory_selector": row["workload"]["selected_selector"],
        "throw": {"class": clazz, "method": method,
                  "line": line, "exception": exception},
        "check_lines": checks,
        "scope_policy": "HDFS main + HDFS client + all Hadoop IPC classes",
        "classpath_sha256": hashlib.sha256(":".join(cp).encode()).hexdigest(),
    })


def campaign_config(args: argparse.Namespace) -> None:
    row = inventory_case(args.inventory, args.case_id)
    clazz, method, line, exception, expected_checks = target_identity(row)
    manifest = read_json(args.scope_output / "weave_manifest.json")
    targets = manifest.get("targets", [])
    throws = [site for site in targets if site.get("kind") == "THROW"
              and site.get("clazz") == clazz and site.get("method") == method
              and site.get("line") == line
              and site.get("exceptionClass") == exception]
    checks = [site for site in targets if site.get("kind") == "BRANCH"
              and site.get("clazz") == clazz and site.get("method") == method]
    emitted_lines = {site.get("line") for site in checks}
    if len(throws) != 1 or not set(expected_checks) <= emitted_lines:
        raise ValueError("Soot did not retain the unique throw and every inventory check branch")
    if not checks:
        raise ValueError("Soot emitted no target check anchor")
    primary = read_json(args.scope_output / "analysis.json").get("targetSiteId")
    if primary not in {site.get("siteId") for site in checks}:
        raise ValueError("planner primary check is absent from manifest")
    cp = exact_classpath(args.classpath_file)
    digest = hashlib.sha256(":".join(cp).encode()).hexdigest()
    if manifest.get("sootDependencyClasspathSha256") != digest:
        raise ValueError("scope and trial dependency classpaths differ")
    weaver_deps = exact_classpath(args.weaver_deps_file)
    selector = row["workload"]["selected_selector"]
    junit_class, junit_method = selector.split("#")
    template = args.out.parent / (args.case_id + "-trial-template")
    if template.exists():
        raise FileExistsError(f"refusing to replace {template}")
    (template / "logs").mkdir(parents=True)
    (template / "test-data").mkdir()
    config = {
        "schema_version": 1, "case_id": args.case_id,
        "junit": {"class": junit_class, "method": junit_method},
        "target": {"check_site_id": primary,
                   "all_check_site_ids": [site["siteId"] for site in checks],
                   "throw_site_id": throws[0]["siteId"],
                   "exception_class": exception},
        "weave_manifest": str((args.scope_output / "weave_manifest.json").resolve()),
        "static_scope_map": str((args.scope_output / "static_scope_map.jsonl").resolve()),
        "original_class_dirs": [cp[0]],
        "soot_dependency_classpath": cp,
        "tool_classpath": [str(args.weaver_jar.resolve()),
                           str(args.runtime_jar.resolve()), *weaver_deps],
        "test_classpath": [str(args.test_classes.resolve())],
        "graph_jar": str(args.graph_jar.resolve()),
        "cwd": str(args.hadoop_root.resolve()),
        "java": str(args.java.resolve()),
        "runner": {"main_class":
                   "edu.uva.liftlab.mallory.adapters.hdfs.graphchecker.RunOriginalJUnit",
                   "args": ["{class}", "{method}"],
                   "jvm_args": ["-Xmx4g", "-Dhadoop.log.dir={trial_cwd}/logs",
                                "-Dtest.build.data={trial_cwd}/test-data"]},
        "trial_cwd_template": str(template.resolve()),
        "budget": {"fault_trials": args.fault_trials,
                   "seconds": args.seconds,
                   "max_faults_per_trial": args.max_faults_per_trial},
        "timeout_seconds": args.timeout_seconds,
        "scope_boundary": "HDFS main + HDFS client + all Hadoop IPC classes",
    }
    write_json(args.out, config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    scope = sub.add_parser("scope-input")
    scope.add_argument("--classes", type=Path, required=True)
    scope.add_argument("--classpath-file", type=Path, required=True)
    scope.add_argument("--out", type=Path, required=True)
    scope.set_defaults(run=scope_input)
    config = sub.add_parser("campaign-config")
    config.add_argument("--scope-output", type=Path, required=True)
    config.add_argument("--classpath-file", type=Path, required=True)
    config.add_argument("--weaver-deps-file", type=Path, required=True)
    config.add_argument("--weaver-jar", type=Path, required=True)
    config.add_argument("--runtime-jar", type=Path, required=True)
    config.add_argument("--graph-jar", type=Path, required=True)
    config.add_argument("--test-classes", type=Path, required=True)
    config.add_argument("--hadoop-root", type=Path, required=True)
    config.add_argument("--java", type=Path, required=True)
    config.add_argument("--out", type=Path, required=True)
    config.add_argument("--fault-trials", type=int, default=64)
    config.add_argument("--seconds", type=int, default=1800)
    config.add_argument("--max-faults-per-trial", type=int, default=4)
    config.add_argument("--timeout-seconds", type=int, default=600)
    config.set_defaults(run=campaign_config)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
