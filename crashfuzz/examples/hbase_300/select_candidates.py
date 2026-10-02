"""Map the old HBase YES sites to 3.0.0 and select exercised targets.

This selection uses exact class, method signature, site kind, and exception
type. Groups with changed multiplicity are excluded because line-order pairing
could silently attach the wrong throw. A discovery trace supplies method-entry
coverage before the final twenty are frozen.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OLD = ROOT / "GraphChecker/tools/coordination_classifier/out/hbase.decisions.jsonl"
NEW = HERE / "out_scan/hbase-3.0.0.decisions.jsonl"
OUT = HERE / "out_selection"
METHOD = re.compile(r"^<([^:]+): ([^ ]+) ([^(]+)\(([^)]*)\)>$")


def descriptor_type(name: str) -> str:
    dimensions = len(name) - len(name.rstrip("[]"))
    if dimensions % 2:
        raise ValueError("bad array type: " + name)
    depth = dimensions // 2
    base = name[:len(name) - 2 * depth] if depth else name
    primitive = {"void": "V", "boolean": "Z", "byte": "B", "char": "C",
                 "short": "S", "int": "I", "long": "J", "float": "F", "double": "D"}
    return "[" * depth + primitive.get(base, "L" + base.replace(".", "/") + ";")


def agent_method(signature: str) -> str:
    match = METHOD.fullmatch(signature)
    if not match:
        raise ValueError("cannot parse Soot method " + signature)
    owner, result, name, arguments = match.groups()
    params = [] if not arguments else arguments.split(",")
    return (owner.replace(".", "/") + "#" + name + "("
            + "".join(descriptor_type(p) for p in params) + ")"
            + descriptor_type(result))


def rows(path: Path) -> list[dict]:
    return [row for line in path.open(encoding="utf-8")
            if (row := json.loads(line)).get("verdict") == "YES"]


def key(row: dict) -> tuple:
    return (row["class"], row["method"], row["siteKind"], row["exception"])


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def pair_candidates() -> tuple[list[dict], dict]:
    former, current = defaultdict(list), defaultdict(list)
    for row in rows(OLD):
        former[key(row)].append(row)
    for row in rows(NEW):
        current[key(row)].append(row)
    paired = []
    counts = {"old_yes": sum(map(len, former.values())),
              "new_yes": sum(map(len, current.values())),
              "ambiguous_groups": 0}
    for signature in sorted(former.keys() & current.keys()):
        left, right = former[signature], current[signature]
        if len(left) != len(right):
            counts["ambiguous_groups"] += 1
            continue
        for old, new in zip(sorted(left, key=lambda r: (r["line"], r["unitIndex"])),
                            sorted(right, key=lambda r: (r["line"], r["unitIndex"]))):
            if new["siteKind"] not in ("throw", "assert"):
                continue
            method = agent_method(new["method"])
            paired.append({
                "old_site_id": old["siteId"], "old_line": old["line"],
                "site_id": new["siteId"], "line": new["line"],
                "class": new["class"], "method": new["method"],
                "agent_method": method,
                "target_site": method + "#L" + str(new["line"]),
                "site_kind": new["siteKind"], "exception": new["exception"],
                "evidence_total": new["evidenceTotal"],
                "truncated": new["truncated"],
                "read_fields": new["readFields"],
                "evidence_kinds": sorted({e["kind"] for e in new["evidence"]}),
                "writer_methods": sorted({
                    agent_method(e["writerMethod"])
                    for e in new["evidence"]
                    if e.get("writerMethod", "").startswith(
                        "<org.apache.hadoop.hbase.")
                }),
            })
    counts["paired_explicit_sites"] = len(paired)
    return paired, counts


def discovery_properties(paired: list[dict]) -> str:
    baseline = {}
    for line in (HERE / "agent.properties").read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            baseline[k] = v
    methods = {row["agent_method"].split("(", 1)[0] for row in paired}
    methods.update(baseline["method.rules"].split(","))
    classes = {row["class"].replace(".", "/") for row in paired}
    classes.update(baseline["include.classes"].split(","))
    return "\n".join([
        "include.classes=" + ",".join(sorted(classes)),
        "method.rules=" + ",".join(sorted(methods)),
        "io.rules=" + baseline.get("io.rules", ""),
        "trace.fields=false", "trace.branches=false",
        "adapter.hbase248.rpc=true", "",
    ])


def select(paired: list[dict], traces: Path) -> tuple[list[dict], dict]:
    if str(ROOT / "baseline/crashfuzz/src") not in sys.path:
        sys.path.insert(0, str(ROOT / "baseline/crashfuzz/src"))
    from adhoc_crashfuzz.graph import read_events

    events = read_events(traces)
    summary_path = traces.parents[2] / "summary.json"
    if summary_path.is_file():
        workload_end_ms = json.loads(summary_path.read_text())["workload_end_ms"]
    else:
        workload_end_ms = int((traces.parent / "hbase-client.exit").stat().st_mtime * 1000)
    nodes_by_method = defaultdict(set)
    for event in events:
        if event.wall_ms > workload_end_ms:
            continue
        if event.kind == "METHOD_ENTER" and event.node in (
                "hm1", "hm2", "rs1", "rs2", "rs3"):
            nodes_by_method[event.site].add(event.node)
    entered = set(nodes_by_method)
    reached = [{**row, "seed_nodes": sorted(nodes_by_method[row["agent_method"]])}
               for row in paired if row["site_kind"] == "throw"
               and row["agent_method"] in entered]
    def package_tier(row: dict) -> int:
        if row["exception"] in ("java.lang.OutOfMemoryError",
                                "java.util.NoSuchElementException"):
            return 4
        suffix = row["class"].removeprefix("org.apache.hadoop.hbase.")
        if suffix.startswith(("master.", "regionserver.", "zookeeper.",
                              "replication.", "security.", "procedure2.")):
            return 0
        if suffix.startswith("client."):
            return 1
        if suffix.startswith("io.hfile."):
            return 2
        return 3

    reached.sort(key=lambda row: (
        package_tier(row), row["truncated"], row["evidence_total"],
        len(row["read_fields"]), row["class"], row["line"]))
    chosen = []
    class_count = defaultdict(int)
    method_count = defaultdict(int)
    sites_seen = set()
    for class_limit in (7, 20):
        for row in reached:
            if row in chosen or len(chosen) == 20:
                continue
            if row["target_site"] in sites_seen:
                continue
            if class_count[row["class"]] >= class_limit:
                continue
            if method_count[row["agent_method"]] >= 2:
                continue
            chosen.append(row)
            sites_seen.add(row["target_site"])
            class_count[row["class"]] += 1
            method_count[row["agent_method"]] += 1
        if len(chosen) == 20:
            break
    return chosen, {"method_entries": len(entered), "covered_candidates": len(reached),
                    "selected": len(chosen), "trace_dir": str(traces)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-dir", type=Path)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    paired, counts = pair_candidates()
    (OUT / "mapped.json").write_text(json.dumps({
        "old_sha256": digest(OLD), "new_sha256": digest(NEW),
        "source_revision": "da418afa6973bf4222231c1d233410d8c18ac7ec",
        "counts": counts, "sites": paired}, indent=2) + "\n")
    (OUT / "agent_discovery.properties").write_text(discovery_properties(paired))
    if args.trace_dir:
        chosen, coverage = select(paired, args.trace_dir.resolve())
        (OUT / "selected20.json").write_text(json.dumps({
            "mapping": counts, "coverage": coverage, "sites": chosen}, indent=2) + "\n")
        print(json.dumps(coverage, sort_keys=True))
        if len(chosen) != 20:
            raise SystemExit("workload covered fewer than 20 compatible candidates")
    else:
        print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
