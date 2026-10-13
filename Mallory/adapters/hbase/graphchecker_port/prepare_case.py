#!/usr/bin/env python3
"""Prepare one HBase GraphChecker campaign from the final case inventory.

The inventory supplies the target and original JUnit. Soot alone selects the
regions, coverage sites and I/O doors. This script does not supply door lists.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path


PLANNER = "edu.uva.liftlab.mallory.scope.ScopePlanner"


def read_case(inventory: Path, case_id: str) -> dict[str, str]:
    with inventory.open(newline="", encoding="utf-8") as stream:
        rows = [row for row in csv.DictReader(stream, delimiter="\t")
                if row["case_id"] == case_id]
    if len(rows) != 1 or rows[0]["system"] != "hbase":
        raise ValueError(f"expected one HBase inventory row for {case_id}")
    row = rows[0]
    required = ("target_class", "target_method", "target_line",
                "target_exception", "junit_class", "junit_method")
    if any(not row.get(key) for key in required):
        raise ValueError(f"incomplete HBase inventory row for {case_id}")
    if row["eligibility_state"] != "ready_for_healthy_seed":
        raise ValueError(f"{case_id} is not eligible: {row['eligibility_state']}")
    return row


def class_present(clazz: str, entries: list[str]) -> bool:
    relative = clazz.replace(".", "/") + ".class"
    for entry in entries:
        path = Path(entry)
        if path.is_dir() and (path / relative).is_file():
            return True
        if path.is_file() and path.suffix == ".jar":
            import zipfile
            with zipfile.ZipFile(path) as jar:
                if relative in jar.namelist():
                    return True
    return False


def exact_cp_digest(entries: list[str]) -> str:
    return hashlib.sha256(os.pathsep.join(entries).encode("utf-8")).hexdigest()


def target_input(row: dict[str, str], template: dict,
                 check_line: int | None = None) -> dict:
    analysis = template["analysis"]
    if not isinstance(analysis.get("process_dirs"), list) or not isinstance(
            analysis.get("classpath"), list):
        raise ValueError("scope template requires process_dirs and ordered classpath")
    if not class_present(row["target_class"], analysis["process_dirs"]):
        raise ValueError(f"target bytecode absent from process_dirs: {row['target_class']}")
    method = row["target_method"].split("(", 1)[0]
    if not method:
        raise ValueError("target method name is empty")
    target = {
        "class": row["target_class"],
        "method": method,
        "line": int(row["target_line"]),
        "kind": "THROW",
        "exception": row["target_exception"],
    }
    if check_line is not None:
        target["check_line"] = check_line
    return {
        "case_id": row["case_id"],
        "target": target,
        "analysis": analysis,
    }


def campaign_config(row: dict[str, str], scope_input: dict,
                    scope_dir: Path, template: dict) -> dict:
    analysis = json.loads((scope_dir / "analysis.json").read_text(encoding="utf-8"))
    manifest = json.loads((scope_dir / "weave_manifest.json").read_text(
        encoding="utf-8"))
    check_id = analysis.get("targetSiteId")
    throw_id = analysis.get("throwSiteId")
    targets = {site["siteId"]: site for site in manifest["targets"]}
    branches = [site for site in manifest["targets"] if site["kind"] == "BRANCH"]
    if len(branches) != 1:
        raise ValueError("expected exactly one controlling branch; supply --check-line")
    if not check_id or not throw_id or check_id == throw_id:
        raise ValueError("planner did not resolve a separate controlling check and throw")
    check = targets.get(check_id, {})
    if check.get("kind") != "BRANCH":
        raise ValueError("planner's check site is not an exact branch")
    throw = targets.get(throw_id, {})
    if (throw.get("kind") != "THROW" or
            throw.get("exceptionClass") != row["target_exception"]):
        raise ValueError("planner's throw does not match the inventory exception")
    method = row["target_method"].split("(", 1)[0]
    expected_class = row["target_class"]
    for name, site in (("check", check), ("throw", throw)):
        if (site.get("clazz") != expected_class or site.get("method") != method):
            raise ValueError(f"planner's {name} is not in the inventory class/method")
    if check.get("descriptor") != throw.get("descriptor"):
        raise ValueError("planner's check and throw are not in the same method")
    if throw.get("line") != int(row["target_line"]):
        raise ValueError("planner's throw is not at the inventory source line")
    check_line = scope_input["target"].get("check_line")
    if check_line is not None and check.get("line") != check_line:
        raise ValueError("planner's check is not at the selected guard line")
    ordered_cp = scope_input["analysis"]["classpath"]
    if (analysis.get("sootDependencyClasspathSha256") != exact_cp_digest(ordered_cp) or
            manifest.get("sootDependencyClasspathSha256") != exact_cp_digest(ordered_cp)):
        raise ValueError("planner output does not match the ordered Soot classpath")
    test_entries = template["test_classpath"] + template["original_class_dirs"]
    if not class_present(row["junit_class"], test_entries):
        raise ValueError(f"original JUnit bytecode unavailable: {row['junit_class']}")
    config = dict(template)
    config.update({
        "case_id": row["case_id"],
        "junit": {"class": row["junit_class"], "method": row["junit_method"]},
        "target": {"check_site_id": check_id,
                   "throw_site_id": throw_id,
                   "exception_class": row["target_exception"]},
        "weave_manifest": str((scope_dir / "weave_manifest.json").resolve()),
        "static_scope_map": str((scope_dir / "static_scope_map.jsonl").resolve()),
        "soot_dependency_classpath": ordered_cp,
    })
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--scope-template", type=Path, required=True)
    parser.add_argument("--campaign-template", type=Path, required=True)
    parser.add_argument("--planner-classpath", type=Path, required=True,
                        help="file containing the planner jar and its dependencies")
    parser.add_argument("--check-line", type=int,
                        help="source line of controlling branch if the throw has several")
    parser.add_argument("--java", default="java")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    row = read_case(args.inventory, args.case_id)
    scope_template = json.loads(args.scope_template.read_text(encoding="utf-8"))
    campaign_template = json.loads(args.campaign_template.read_text(encoding="utf-8"))
    scope_input = target_input(row, scope_template, args.check_line)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scope_dir = output / "scope"
    scope_path = output / "scope-input.json"
    scope_path.write_text(json.dumps(scope_input, indent=2) + "\n", encoding="utf-8")
    planner_cp = args.planner_classpath.read_text(encoding="utf-8").strip()
    if not planner_cp:
        raise ValueError("empty planner classpath")
    with (output / "planner.log").open("w", encoding="utf-8") as log:
        subprocess.run([args.java, "-Xmx8g", "-cp", planner_cp, PLANNER,
                        str(scope_path), str(scope_dir)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    config = campaign_config(row, scope_input, scope_dir, campaign_template)
    (output / "case.json").write_text(json.dumps(config, indent=2) + "\n",
                                      encoding="utf-8")
    print(output / "case.json")


if __name__ == "__main__":
    main()
