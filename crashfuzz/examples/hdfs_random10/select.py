"""Freeze an unbiased, reproducible sample of HDFS YES check sites."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import re


HERE = Path(__file__).resolve().parent
SOURCE = (HERE.parents[3] / "GraphChecker/tools/coordination_classifier/out"
          / "hdfs.decisions.jsonl")
SEED = 20261001
COUNT = 10
METHOD = re.compile(r"^<([^:]+): ([^ ]+) ([^(]+)\(([^)]*)\)>$")


def descriptor_type(name: str) -> str:
    depth = 0
    while name.endswith("[]"):
        depth += 1
        name = name[:-2]
    primitive = {"void": "V", "boolean": "Z", "byte": "B", "char": "C",
                 "short": "S", "int": "I", "long": "J", "float": "F",
                 "double": "D"}
    return "[" * depth + primitive.get(
        name, "L" + name.replace(".", "/") + ";")


def agent_method(signature: str) -> str:
    match = METHOD.fullmatch(signature)
    if match is None:
        raise ValueError("cannot parse method signature: " + signature)
    owner, result, name, parameters = match.groups()
    args = [] if not parameters else parameters.split(",")
    return (owner.replace(".", "/") + "#" + name + "("
            + "".join(descriptor_type(arg) for arg in args) + ")"
            + descriptor_type(result))


def main() -> None:
    raw = SOURCE.read_bytes()
    yes = [row for line in raw.splitlines()
           if (row := json.loads(line)).get("verdict") == "YES"]
    if len(yes) != 532:
        raise RuntimeError("expected 532 pinned HDFS YES sites, found "
                           + str(len(yes)))
    chosen = random.Random(SEED).sample(yes, COUNT)
    rows = []
    for position, row in enumerate(chosen, 1):
        method = agent_method(row["method"])
        rows.append({
            "draw": position,
            "site_id": row["siteId"],
            "class": row["class"],
            "method": row["method"],
            "agent_method": method,
            "line": row["line"],
            "site_kind": row["siteKind"],
            "exception": row["exception"],
            "target_throw": method + "#L" + str(row["line"]),
            "truncated": row["truncated"],
            "evidence_total": row["evidenceTotal"],
            "read_fields": row["readFields"],
            "writer_methods": sorted({
                agent_method(e["writerMethod"])
                for e in row["evidence"]
                if e.get("writerMethod", "").startswith(
                    "<org.apache.hadoop.")
            }),
        })
    result = {
        "system": "hdfs", "version": "3.4.3", "source": str(SOURCE),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "sampling": "random.Random(seed).sample(all YES rows, 10)",
        "seed": SEED, "population": len(yes), "sites": rows,
    }
    destination = HERE / "selected10.json"
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print("selected", len(rows), "of", len(yes), "HDFS YES sites")
    for row in rows:
        print("{:02d} {}:{} {}".format(row["draw"], row["class"],
                                        row["line"], row["site_kind"]))


if __name__ == "__main__":
    main()
