#!/usr/bin/env python3
"""Prepare an inventory-selected original Solr JUnit for the generic graph campaign.

The template supplies the pinned Solr protocol build and ordered toolchain, not
case-specific I/O points. The static planner generates the region and door set.
Run ``scope`` first, execute its run_scope.sh, then run ``campaign``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shlex
from pathlib import Path


HERE = Path(__file__).resolve().parent
INVENTORY = HERE.parents[2] / "cases" / "inventory.json"
SOURCE_RECEIPT = HERE / "protocol_source_receipt.json"
SOURCE_SUFFIX = "/solr/build/solr-core/classes/java"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def write_once(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() != value:
        raise FileExistsError(f"refusing to replace different pinned input: {path}")
    path.write_text(value)


def emit_json(path: Path, value: dict) -> None:
    write_once(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def case_row(case_id: str, inventory: Path) -> dict:
    rows = [r for r in read_json(inventory)["cases"]
            if r.get("system") == "solr" and r.get("case_id") == case_id]
    if len(rows) != 1:
        raise ValueError(f"expected exactly one Solr inventory row: {case_id}")
    row = rows[0]
    if not row["eligibility"].get("may_dispatch_healthy_seed"):
        raise ValueError(f"inventory does not admit a healthy seed: {case_id}: "
                         f"{row['eligibility']['state']}")
    return row


def attest_source(row: dict, source: Path, receipt_path: Path) -> dict:
    receipt = read_json(receipt_path)
    if row["provenance"]["source_commit"] != receipt["source_commit"]:
        raise ValueError("inventory source commit differs from Solr protocol pin")
    if receipt["patch_sha256"] != digest(HERE / "solr-e27f44e-mallory-causal.patch"):
        raise ValueError("Solr protocol patch differs from its receipt")
    mismatches = [rel for rel, expected in receipt["patched_source_sha256"].items()
                  if not (source / rel).is_file() or digest(source / rel) != expected]
    if mismatches:
        raise ValueError(f"Solr protocol source differs from pinned patch: {mismatches}")
    target = row["target"]
    if digest(source / target["source_path"]) != target["source_sha256"]:
        raise ValueError(f"target source changed: {target['source_path']}")
    workload = row["workload"]
    selected = workload["selected_selector"]
    matches = [candidate for candidate in workload["candidates"]
               if candidate.get("selector") == selected and
               candidate.get("source_path") == workload["test_source_path"]]
    if len(matches) != 1 or not matches[0].get("source_sha256"):
        raise ValueError(f"selected original JUnit has no unique source receipt: {selected}")
    if digest(source / workload["test_source_path"]) != matches[0]["source_sha256"]:
        raise ValueError(f"selected original JUnit source changed: {selected}")
    return {"source_commit": receipt["source_commit"],
            "protocol_patch_sha256": receipt["patch_sha256"],
            "target_source_sha256": target["source_sha256"],
            "junit_source_sha256": matches[0]["source_sha256"]}


def selected_target(row: dict) -> dict:
    target = row["target"]
    head = target["function"].split("(", 1)[0]
    class_name, method = head.rsplit(".", 1)
    check_lines = {int(line) for site in target["runtime_mapping"]["check_sites"]
                   for line in re.findall(r"@(\d+):branch", site)}
    if len(check_lines) != 1:
        raise ValueError(f"target guard has no unique source line: {row['case_id']}: "
                         f"{sorted(check_lines)}")
    return {"class": class_name, "method": method,
            "line": int(target["source_line"]),
            "check_line": check_lines.pop(),
            "exception": target["target_exception"], "kind": "THROW"}


def template_root(scope: dict) -> Path:
    core = scope["analysis"]["process_dirs"][0]
    if not core.endswith(SOURCE_SUFFIX):
        raise ValueError("template is not a pinned Solr core process classpath")
    return Path(core[:-len(SOURCE_SUFFIX)])


def remap(value, old: Path, new: Path):
    if isinstance(value, str):
        prefix = str(old)
        return str(new) + value[len(prefix):] if value.startswith(prefix + "/") else value
    if isinstance(value, list):
        return [remap(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: remap(item, old, new) for key, item in value.items()}
    return value


def classpath_for_case(row: dict, source: Path, scope_template: dict,
                       native_template: dict) -> tuple[dict, list[str]]:
    old = template_root(scope_template)
    template_ordered = (native_template["tool_classpath"] +
                        native_template["original_class_dirs"] +
                        native_template["test_classpath"])
    if template_ordered != scope_template["analysis"]["classpath"]:
        raise ValueError("template native and static ordered classpaths differ")
    config = remap(copy.deepcopy(native_template), old, source)
    process_dirs = config["original_class_dirs"]
    test_cp = config["test_classpath"]
    test_module = row["workload"]["test_source_path"].split("/", 2)[1]
    module_test_classes = str(source / "solr/build" /
                              ("solr-" + test_module) / "classes/test")
    if module_test_classes not in test_cp:
        test_cp.insert(0, module_test_classes)
    compiled_test = Path(module_test_classes) / (row["workload"]["test_class"].replace(".", "/") + ".class")
    target_module = row["target"]["source_path"].split("/", 2)[1]
    compiled_target = (source / "solr/build" / ("solr-" + target_module) /
                       "classes/java" /
                       (selected_target(row)["class"].replace(".", "/") + ".class"))
    for path in [*map(Path, config["tool_classpath"]), *map(Path, process_dirs),
                 *map(Path, test_cp), compiled_test, compiled_target]:
        if not path.exists():
            raise FileNotFoundError(path)
    ordered = config["tool_classpath"] + process_dirs + test_cp
    expected = remap(scope_template["analysis"]["classpath"], old, source)
    if module_test_classes not in expected:
        expected.insert(len(config["tool_classpath"]) + len(process_dirs), module_test_classes)
    if ordered != expected:
        raise ValueError("case native and static ordered classpaths differ")
    return config, ordered


def prepare_scope(args: argparse.Namespace) -> None:
    row = case_row(args.case_id, args.inventory)
    source = args.source.resolve()
    proof = attest_source(row, source, args.protocol_receipt)
    scope_template = read_json(args.template / "scope-input.json")
    native_template = read_json(args.template / "native-config.json")
    native, ordered = classpath_for_case(row, source, scope_template, native_template)
    if not args.planner_jar.is_file() or not args.planner_deps.is_file():
        raise FileNotFoundError("planner jar or dependencies missing")
    scope = remap(copy.deepcopy(scope_template), template_root(scope_template), source)
    scope["case_id"] = args.case_id
    scope["target"] = selected_target(row)
    scope["analysis"]["classpath"] = ordered
    args.out.mkdir(parents=True, exist_ok=True)
    emit_json(args.out / "scope-input.json", scope)
    metadata = {"case_id": args.case_id, "junit": row["workload"]["selected_selector"],
                "target": scope["target"], "source": proof,
                "ordered_classpath_entries": len(ordered),
                "planner_jar_sha256": digest(args.planner_jar),
                "planner_deps_sha256": digest(args.planner_deps),
                "weaver_jar_sha256": digest(Path(native["tool_classpath"][0])),
                "runtime_jar_sha256": digest(Path(native["graph_jar"])),
                "template_scope_sha256": digest(args.template / "scope-input.json"),
                "template_native_sha256": digest(args.template / "native-config.json")}
    emit_json(args.out / "case-preparation.json", metadata)
    planner_cp = str(args.planner_jar.resolve()) + ":" + args.planner_deps.read_text().strip()
    command = ["timeout", "--signal=TERM", "--kill-after=30s", "900s",
               "java", "-Xmx6g", "-cp", planner_cp,
               "edu.uva.liftlab.mallory.scope.ScopePlanner",
               str(args.out / "scope-input.json"), str(args.out / "scope-output")]
    script = ("#!/usr/bin/env bash\nset -euo pipefail\n" +
              " ".join(shlex.quote(arg) for arg in command) + "\n")
    write_once(args.out / "run_scope.sh", script)
    (args.out / "run_scope.sh").chmod(0o755)
    print(json.dumps({"case_id": args.case_id, "phase": "scope_prepared",
                      "junit": metadata["junit"], "out": str(args.out)}, sort_keys=True))


def prepare_campaign(args: argparse.Namespace) -> None:
    row = case_row(args.case_id, args.inventory)
    source = args.source.resolve()
    proof = attest_source(row, source, args.protocol_receipt)
    scope_template = read_json(args.template / "scope-input.json")
    native_template = read_json(args.template / "native-config.json")
    native, ordered = classpath_for_case(row, source, scope_template, native_template)
    scope = read_json(args.out / "scope-input.json")
    if (scope["case_id"] != args.case_id or
            scope["analysis"]["classpath"] != ordered or
            scope["target"] != selected_target(row)):
        raise ValueError("scope input differs from current pinned case/toolchain")
    analysis = read_json(args.out / "scope-output/analysis.json")
    manifest_path = args.out / "scope-output/weave_manifest.json"
    scope_map = args.out / "scope-output/static_scope_map.jsonl"
    manifest = read_json(manifest_path)
    if analysis["caseId"] != args.case_id or manifest["caseId"] != args.case_id:
        raise ValueError("scope output belongs to a different case")
    if analysis["sootDependencyClasspathSha256"] != manifest["sootDependencyClasspathSha256"]:
        raise ValueError("scope analysis/manifest classpath fingerprint differs")
    target_sites = {(site["kind"], site["siteId"])
                    for site in manifest["targets"]}
    expected_sites = {("BRANCH", analysis["targetSiteId"]),
                      ("THROW", analysis["throwSiteId"])}
    if target_sites != expected_sites or not manifest["doors"]:
        raise ValueError("generated scope lacks target pair or typed fault doors")
    if not scope_map.is_file():
        raise FileNotFoundError(scope_map)
    native["case_id"] = args.case_id
    native["junit"] = {"class": row["workload"]["test_class"],
                       "method": row["workload"]["test_method"]}
    native["target"] = {"check_site_id": analysis["targetSiteId"],
                        "throw_site_id": analysis["throwSiteId"],
                        "exception_class": row["target"]["target_exception"]}
    native["weave_manifest"] = str(manifest_path)
    native["static_scope_map"] = str(scope_map)
    test_home = source / "/".join(row["workload"]["test_source_path"].split("/")[:2])
    native["cwd"] = str(test_home)
    jvm_args = [arg for arg in native["runner"]["jvm_args"]
                if not arg.startswith("-Dtests.src.home=")]
    jvm_args.append("-Dtests.src.home=" + str(test_home))
    native["runner"]["jvm_args"] = jvm_args
    native["budget"] = {"fault_trials": args.trials, "seconds": args.seconds,
                        "max_faults_per_trial": args.max_faults}
    args.project.mkdir(parents=True, exist_ok=True)
    emit_json(args.project / "config.json", native)
    emit_json(args.project / "scope-input.json", scope)
    receipt = {"case_id": args.case_id, "source": proof,
               "junit": row["workload"]["selected_selector"],
               "target_check_site_id": analysis["targetSiteId"],
               "target_throw_site_id": analysis["throwSiteId"],
               "generated_typed_fault_doors": len(manifest["doors"]),
               "generated_coverage_sites": len(manifest["coverage"]),
               "generated_regions": len(manifest["regions"]),
               "soot_classpath_sha256": manifest["sootDependencyClasspathSha256"],
               "weave_manifest_sha256": digest(manifest_path),
               "static_scope_map_sha256": digest(scope_map),
               "budget": native["budget"]}
    emit_json(args.project / "preparation-receipt.json", receipt)
    if not args.core_pythonpath.is_dir():
        raise FileNotFoundError(args.core_pythonpath)
    command = ["python3", "-m", "Mallory.core.graphchecker_fuzzer",
               "--config", str(args.project / "config.json"),
               "--out", str(args.project / "native-campaign")]
    script = ("#!/usr/bin/env bash\nset -euo pipefail\n" +
              "export PYTHONPATH=" + shlex.quote(str(args.core_pythonpath)) + "\n" +
              "export JAVA_TOOL_OPTIONS=-Xmx20g\n" +
              " ".join(shlex.quote(arg) for arg in command) + "\n")
    write_once(args.project / "run_campaign.sh", script)
    (args.project / "run_campaign.sh").chmod(0o755)
    print(json.dumps({"case_id": args.case_id, "phase": "campaign_prepared",
                      "generated_doors": len(manifest["doors"]),
                      "project": str(args.project)}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("scope", "campaign"))
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path,
                        help="pinned Solr protocol build scope-input/native-config directory")
    parser.add_argument("--out", required=True, type=Path,
                        help="case-specific static scope workspace")
    parser.add_argument("--project", type=Path,
                        help="durable case evidence root (campaign phase)")
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--protocol-receipt", type=Path, default=SOURCE_RECEIPT)
    parser.add_argument("--planner-jar", type=Path)
    parser.add_argument("--planner-deps", type=Path)
    parser.add_argument("--core-pythonpath", type=Path)
    parser.add_argument("--trials", type=int, default=64)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--max-faults", type=int, default=4)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.template = args.template.resolve()
    if args.phase == "scope":
        if args.planner_jar is None or args.planner_deps is None:
            parser.error("scope phase needs --planner-jar and --planner-deps")
        prepare_scope(args)
    else:
        if args.project is None or args.core_pythonpath is None:
            parser.error("campaign phase needs --project and --core-pythonpath")
        if min(args.trials, args.seconds, args.max_faults) <= 0:
            parser.error("fault budget values must be positive")
        args.project = args.project.resolve()
        prepare_campaign(args)


if __name__ == "__main__":
    main()
