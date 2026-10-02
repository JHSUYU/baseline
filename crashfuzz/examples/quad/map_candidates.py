"""Map classifier YES throws to direct bytecode guards on pinned releases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from adhoc_crashfuzz.bytecode_checks import javap_class, map_direct_throw
from adhoc_crashfuzz.signatures import agent_method


ROOT = Path(__file__).resolve().parents[3]
DECISIONS = ROOT.parent / "GraphChecker/tools/coordination_classifier/out"
DEPS = Path.home() / ".baseline-deps"
SPECS = {
    "hbase": (DEPS / "hbase-2.6.6", "lib/*", "org.apache.hadoop.hbase."),
    "solr": (DEPS / "solr-8.11.4",
             "server/solr-webapp/webapp/WEB-INF/lib/*:dist/*",
             "org.apache.solr."),
    "zookeeper": (DEPS / "apache-zookeeper-3.8.7-bin", "lib/*",
                  "org.apache.zookeeper."),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("system", choices=SPECS)
    args = parser.parse_args()
    dist, classpath_suffix, prefix = SPECS[args.system]
    classpath = ":".join(str(dist / item)
                         for item in classpath_suffix.split(":"))
    decisions = DECISIONS / (args.system + ".decisions.jsonl")
    output = Path(__file__).resolve().parent.parent / {
        "hbase": "hbase_266", "solr": "solr_8114",
        "zookeeper": "zookeeper_387"}[args.system] / "out_mapping"
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with decisions.open() as source:
        for line in source:
            row = json.loads(line)
            if (row["verdict"] == "YES"
                    and row["siteKind"] in ("throw", "assert")
                    and row["class"].startswith(prefix)):
                rows.append(row)
    cache: dict[str, str | None] = {}
    selected = []
    failures = {"no_compiled_class": 0, "ambiguous_or_indirect": 0,
                "bad_signature": 0}
    for index, row in enumerate(rows, 1):
        classname = row["class"]
        if classname not in cache:
            try:
                cache[classname] = javap_class(classpath, classname)
            except Exception:
                cache[classname] = None
        compiled = cache[classname]
        if compiled is None:
            failures["no_compiled_class"] += 1
            continue
        try:
            method = agent_method(row["method"])
        except ValueError:
            failures["bad_signature"] += 1
            continue
        mapped = map_direct_throw(method, int(row["line"]), compiled)
        if mapped is None:
            failures["ambiguous_or_indirect"] += 1
            continue
        writers = set()
        for item in row["evidence"]:
            signature = item.get("writerMethod", "")
            if signature.startswith("<" + prefix):
                try:
                    writers.add(agent_method(signature))
                except ValueError:
                    continue
        selected.append({
            "site_id": row["siteId"], "class": classname,
            "method": row["method"], "agent_method": method,
            "source_line": row["line"], "site_kind": row["siteKind"],
            "exception": row["exception"],
            "target_guard": mapped["guard"],
            "target_throw": mapped["throw"],
            "guard_offset": mapped["guard_offset"],
            "throw_offset": mapped["throw_offset"],
            "writer_methods": sorted(writers),
            "evidence_total": row["evidenceTotal"],
            "interaction_tags": row["interactionTags"],
        })
        if index % 50 == 0:
            print(args.system, "mapped", index, "/", len(rows), flush=True)
    result = {
        "system": args.system, "distribution": str(dist),
        "classpath": classpath,
        "decisions_sha256": hashlib.sha256(decisions.read_bytes()).hexdigest(),
        "explicit_yes": len(rows), "direct_mapped": len(selected),
        "failures": failures, "sites": selected,
    }
    (output / "mapped.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n")
    methods = {item["agent_method"].split("(", 1)[0] for item in selected}
    classes = {item["class"].replace(".", "/") for item in selected}
    (output / "discovery.properties").write_text("\n".join([
        "include.classes=" + ",".join(sorted(classes)),
        "method.rules=" + ",".join(sorted(methods)),
        "trace.fields=false", "trace.branches=false",
        "target.guard=", "target.throw=", "target.entry=", "",
    ]))
    base = dict(line.split("=", 1) for line in
                (output.parent / "agent.properties").read_text().splitlines()
                if "=" in line and not line.startswith("#"))
    base_classes = set(base.get("include.classes", "").split(","))
    base_methods = set(base.get("method.rules", "").split(","))
    classes.update(base_classes - {""})
    methods.update(base_methods - {""})
    branch_discovery = {
        "include.classes": ",".join(sorted(classes)),
        "method.rules": ",".join(sorted(methods)),
        "point.entries": base.get("point.entries", ""),
        "trace.fields": "false", "trace.branches": "true",
        "coverage.blocks": "true", "coverage.branches": "true",
        "coverage.include.prefixes": prefix.replace(".", "/"),
        "target.guard": "", "target.throw": "", "target.entry": "",
    }
    for key, value in base.items():
        if key.startswith("adapter."):
            branch_discovery[key] = value
    (output / "branch-discovery.properties").write_text(
        "\n".join(key + "=" + value for key, value in
                  branch_discovery.items()) + "\n")
    print(json.dumps({"system": args.system, "mapped": len(selected),
                      "classes": len(cache), "failures": failures}))


if __name__ == "__main__":
    main()
