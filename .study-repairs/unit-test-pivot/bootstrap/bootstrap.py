#!/usr/bin/env python3
"""Audit the 102 selected checks and issue isolated original-JUnit starters.

This is intentionally a source/test inventory. A starter is not a healthy trace,
an executable instrumented adapter, or evidence that the target branch executes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
PIVOT = HERE.parent
BASELINE = PIVOT.parent.parent
SOURCES = {
    "hbase": Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6"),
    "hdfs": Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"),
    "solr": Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4"),
    "zookeeper": Path("/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7"),
}
MAP_NAMES = {s: s.upper() + "-TEST-MAP.json" for s in SOURCES}
IO_HINTS = {
    "hbase": "Inspect original-test HBase RPC, ZooKeeper and filesystem fault markers in the healthy trace; select exact observed identities.",
    "hdfs": "Inspect original-test HDFS RPC, data-transfer and filesystem fault markers in the healthy trace; select exact observed identities.",
    "solr": "Inspect original-test Solr HTTP, ZooKeeper and index/filesystem fault markers in the healthy trace; select exact observed identities.",
    "zookeeper": "Inspect original-test client TCP, quorum peer and persistence fault markers in the healthy trace; select exact observed identities.",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def test_identity(system: str, row: dict) -> tuple[str | None, str | None, str | None]:
    if system == "hbase":
        identity = row.get("test_class_method")
        if not identity:
            return None, None, None
        simple, method = identity.rsplit(".", 1)
        return simple, method, row.get("test_source")
    if system == "hdfs":
        return row.get("test_class"), row.get("test_method"), row.get("test_source")
    if system == "solr":
        identity = row.get("test")
        if not identity:
            return None, None, None
        simple, method = identity.rsplit(".", 1)
        return simple, method, row.get("test_path")
    test = row.get("cluster_test") or {}
    return test.get("class"), test.get("method"), test.get("path")


def mapping_rows(system: str) -> list[dict]:
    data = read_json(PIVOT / MAP_NAMES[system])
    return data.get("cases", data.get("rows", []))


def source_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def method_declaration(path: Path, method: str) -> tuple[bool, int | None, str | None]:
    # JUnit parameters are represented by the method declaration, not an
    # invented single-parameter test selector. JUnit 3 test* methods are valid.
    name = method.split("(", 1)[0]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    pattern = re.compile(r"\b(?:public|protected)\s+(?:static\s+)?(?:\S+\s+)*" + re.escape(name) + r"\s*\(")
    for index, line in enumerate(lines):
        if pattern.search(line):
            window = "\n".join(lines[max(0, index - 12):index])
            annotation = bool(re.search(r"@(?:Test|ParameterizedTest|Repeat)\b", window))
            junit3 = name.startswith("test")
            return annotation or junit3, index + 1, "annotation" if annotation else "junit3_name" if junit3 else None
    return False, None, None


def command(system: str, test_class: str, method: str, test_file: Path) -> list[str]:
    method = method.split("(", 1)[0]
    simple = test_class.rsplit(".", 1)[-1]
    if system == "solr":
        module = "solrj" if "/solr/solrj/" in str(test_file) else "core"
        return ["ant", "-f", f"solr/{module}/build.xml", "test", f"-Dtestcase={simple}", f"-Dtests.method={method}"]
    if system == "hbase":
        module = test_file.relative_to(SOURCES[system]).parts[0]
        return ["mvn", "-pl", module, "-am", "test", f"-Dtest={simple}#{method}", "-Dsurefire.failIfNoSpecifiedTests=false"]
    if system == "hdfs":
        parts = test_file.relative_to(SOURCES[system]).parts
        module = "/".join(parts[:2])
        return ["mvn", "-pl", module, "-am", "test", f"-Dtest={simple}#{method}", "-DfailIfNoTests=false"]
    return ["mvn", "-pl", "zookeeper-server", "-am", "test", f"-Dtest={simple}#{method}", "-DfailIfNoTests=false"]


def evidence_for_absence(system: str, row: dict) -> str | None:
    if system == "hbase" and row.get("no_cluster_test") is True:
        return row.get("reason")
    if system == "hdfs" and row.get("target_reach_status") == "no_cluster_test":
        return row.get("cluster_evidence", {}).get("test_relation") or row.get("skip_reason")
    if system == "zookeeper" and row.get("no_cluster_test_reason"):
        return row["no_cluster_test_reason"]
    return None


def build_catalog() -> list[dict]:
    checks = read_json(PIVOT / "selection102.json")["checks"]
    maps = {}
    for system in SOURCES:
        rows = mapping_rows(system)
        if len(rows) != len({row["case_id"] for row in rows}):
            raise ValueError(f"duplicate {system} map case")
        maps.update({row["case_id"]: row for row in rows})
    selected = {check["case_id"] for check in checks}
    if len(checks) != 102 or len(selected) != 102 or set(maps) != selected:
        raise ValueError("selection102 and system test maps do not match exactly")
    result = []
    for check in checks:
        case_id, system = check["case_id"], check["system"]
        row, root = maps[case_id], SOURCES[system]
        target_file = source_path(root, check["source_path"])
        if not inside(target_file, root) or not target_file.is_file():
            raise ValueError(f"{case_id}: selected target source absent/outside root: {target_file}")
        cluster_class, method, test_source = test_identity(system, row)
        absence = evidence_for_absence(system, row)
        entry = {
            "case_id": case_id,
            "system": system,
            "selection": {"site_id": check["site_id"], "source_path": str(target_file),
                          "source_line": check["source_line"], "function": check["function"],
                          "target_guard": check.get("target_guard"),
                          "target_throw": check.get("target_throw"),
                          "target_exception": check.get("target_exception")},
            "mapping_source": str(PIVOT / MAP_NAMES[system]),
            "source_root": str(root),
            "runtime_target_reach_verified": False,
        }
        if not all((cluster_class, method, test_source)):
            if not absence:
                raise ValueError(f"{case_id}: no original cluster test and no source evidence")
            entry.update(status="no_cluster_test", no_cluster_test_evidence=absence,
                         cluster_test=None)
        else:
            test_file = source_path(root, test_source)
            if not inside(test_file, root) or not test_file.is_file():
                raise ValueError(f"{case_id}: test source absent/outside root: {test_file}")
            valid, line, declaration_kind = method_declaration(test_file, method)
            if not valid:
                raise ValueError(f"{case_id}: original JUnit declaration absent: {test_file}#{method}")
            package = re.search(r"(?m)^package\s+([\w.]+)\s*;", test_file.read_text(errors="replace"))
            if not package:
                raise ValueError(f"{case_id}: test package missing")
            fqcn = package.group(1) + "." + test_file.stem
            if cluster_class.rsplit(".", 1)[-1] != test_file.stem:
                raise ValueError(f"{case_id}: class/source name mismatch")
            if system == "hdfs" and cluster_class != fqcn:
                raise ValueError(f"{case_id}: full class name mismatch")
            case_root = HERE / "cases" / case_id
            if not inside(case_root, HERE):
                raise ValueError(f"{case_id}: case root escapes bootstrap")
            entry.update(
                status="original_cluster_junit_source_verified",
                cluster_test={"class": fqcn, "method": method.split("(", 1)[0],
                              "mapped_invocation": method, "source_path": str(test_file),
                              "declaration_line": line, "declaration_kind": declaration_kind,
                              "cluster_evidence": row.get("cluster_evidence") or row.get("fixture") or row.get("test_kind"),
                              "command": command(system, fqcn, method, test_file)},
                starter={
                    "workspaces": {"system_test": str(case_root / "system-test"),
                                   "temp": str(case_root / "temp"),
                                   "healthy": str(case_root / "healthy"),
                                   "campaign": str(case_root / "campaign")},
                    "system_test_cwd": str(case_root / "system-test"),
                    "system_test_command": command(system, fqcn, method, test_file),
                    "io_scope_hint": IO_HINTS[system],
                    "io_scope": {"marker_prefixes": [], "site_ids": []},
                    "budget": {"max_trials": 48, "max_faults": 4},
                    "extension_budget": {"max_trials": 96, "max_faults": 6},
                    "checkpoints": {"state": str(case_root / "campaign" / "state.json"),
                                    "result": str(case_root / "campaign" / "result.json"),
                                    "healthy_trace": str(case_root / "healthy" / "runtime_trace.jsonl")},
                    "required_before_campaign": ["Populate isolated system_test workspace from source_root",
                                                 "Run original cluster JUnit without faults",
                                                 "Attach instrumentation and record healthy runtime_trace.jsonl",
                                                 "Verify selected target site and I/O markers in healthy trace",
                                                 "Supply a per-case adapter that reruns the same JUnit with fault options"],
                },
            )
            # Source mapping and original JUnit declaration establish the
            # workload, but not target execution or a successful test run.
            if method != method.split("(", 1)[0]:
                entry["starter"]["runner_caveat"] = "Parameterized JUnit method: command runs all declared parameter values; verify the mapped invocation in the trace."
        result.append(entry)
    return result


def validate_catalog(entries: list[dict]) -> Counter:
    ids = [x["case_id"] for x in entries]
    if len(ids) != len(set(ids)) or len(ids) != 102:
        raise ValueError("catalog must contain 102 unique cases")
    for entry in entries:
        if entry["status"] == "no_cluster_test":
            if not entry.get("no_cluster_test_evidence") or entry.get("cluster_test"):
                raise ValueError(f"{entry['case_id']}: invalid no_cluster_test entry")
            continue
        starter = entry["starter"]
        paths = [Path(p) for p in starter["workspaces"].values()]
        if len(set(paths)) != len(paths):
            raise ValueError(f"{entry['case_id']}: duplicate workspace")
        case_root = HERE / "cases" / entry["case_id"]
        if any(not inside(p, case_root) for p in paths):
            raise ValueError(f"{entry['case_id']}: workspace escapes case root")
        if any(inside(p, SOURCES[entry["system"]]) for p in paths):
            raise ValueError(f"{entry['case_id']}: writable workspace overlaps source root")
        if Path(starter["system_test_cwd"]) != Path(starter["workspaces"]["system_test"]):
            raise ValueError(f"{entry['case_id']}: test command is not isolated")
    return Counter(x["status"] for x in entries)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("audit", help="validate all 102 source mappings and print counts")
    sub.add_parser("build", help="write catalog/ID.json for all 102 cases")
    next_parser = sub.add_parser("next", help="issue next mapped case not yet in issued/")
    next_parser.add_argument("--system", choices=sorted(SOURCES))
    next_parser.add_argument("--case", help="issue one selected case ID")
    next_parser.add_argument("--include-active", action="store_true",
                             help="also issue cases with existing trials or excluded checklist status")
    sub.add_parser("validate", help="check catalog consistency, paths and isolation")
    args = parser.parse_args()
    try:
        entries = build_catalog()
        counts = validate_catalog(entries)
        if args.action == "validate":
            catalog_files = {path.stem: path for path in (HERE / "catalog").glob("*.json")}
            if set(catalog_files) != {entry["case_id"] for entry in entries}:
                raise ValueError("stored catalog IDs do not match the selected 102")
            for entry in entries:
                if read_json(catalog_files[entry["case_id"]]) != entry:
                    raise ValueError(f"{entry['case_id']}: stored catalog differs from verified source mapping")
        if args.action in ("audit", "validate"):
            print(json.dumps({"selection_count": len(entries), "status_counts": counts}, indent=2))
            return 0
        if args.action == "build":
            for entry in entries:
                write_json(HERE / "catalog" / (entry["case_id"] + ".json"), entry)
            print(json.dumps({"written": len(entries), "status_counts": counts}, indent=2))
            return 0
        candidates = [x for x in entries if x["status"] == "original_cluster_junit_source_verified"]
        if not args.include_active:
            checklist = {row["case_id"]: row for row in read_json(PIVOT / "checklist102.json")["rows"]}
            candidates = [x for x in candidates if
                          checklist[x["case_id"]].get("status") not in
                          ("no_cluster_test", "quality_complete", "running",
                           "fuzzing", "candidate_review", "confirmed_bug") and
                          not (checklist[x["case_id"]].get("fault_trials") or 0)]
        if args.system:
            candidates = [x for x in candidates if x["system"] == args.system]
        if args.case:
            candidates = [x for x in candidates if x["case_id"] == args.case]
        elif not args.system:
            candidates.sort(key=lambda x: x["case_id"])
        (HERE / "issued").mkdir(parents=True, exist_ok=True)
        candidate = None
        issue = None
        for proposed in candidates:
            proposed_path = HERE / "issued" / (proposed["case_id"] + ".json")
            try:
                with proposed_path.open("x", encoding="utf-8") as stream:
                    json.dump(proposed, stream, indent=2, ensure_ascii=False)
                    stream.write("\n")
                candidate, issue = proposed, proposed_path
                break
            except FileExistsError:
                continue
        if candidate is None or issue is None:
            print("No unissued mapped case matches selection", file=sys.stderr)
            return 2
        print(json.dumps({"case_id": candidate["case_id"], "starter": str(issue),
                          "test_command": candidate["starter"]["system_test_command"],
                          "campaign_ready": False}, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"bootstrap: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
