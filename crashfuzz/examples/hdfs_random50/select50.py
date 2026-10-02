"""Extend the frozen ten HDFS checks with forty further random YES sites."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import runpy


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
selection_code = runpy.run_path(str(TEN / "select.py"))
SEED = selection_code["SEED"]
SOURCE = selection_code["SOURCE"]
agent_method = selection_code["agent_method"]


def main() -> None:
    raw = SOURCE.read_bytes()
    yes = [row for line in raw.splitlines()
           if (row := json.loads(line)).get("verdict") == "YES"]
    if len(yes) != 532:
        raise RuntimeError("expected 532 HDFS YES candidates")
    first = json.loads((TEN / "selected10.json").read_text())
    if first["source_sha256"] != hashlib.sha256(raw).hexdigest():
        raise RuntimeError("classifier decisions changed since first ten")
    first_ids = [site["site_id"] for site in first["sites"]]
    rng = random.Random(SEED)
    replay = rng.sample(yes, 10)
    if [row["siteId"] for row in replay] != first_ids:
        raise RuntimeError("frozen first-ten draw does not reproduce")
    remaining = [row for row in yes if row["siteId"] not in set(first_ids)]
    additional = rng.sample(remaining, 40)
    sites = [dict(site) for site in first["sites"]]
    for draw, row in enumerate(additional, 11):
        method = agent_method(row["method"])
        sites.append({
            "draw": draw, "site_id": row["siteId"],
            "class": row["class"], "method": row["method"],
            "agent_method": method, "line": row["line"],
            "site_kind": row["siteKind"], "exception": row["exception"],
            "target_throw": method + "#L" + str(row["line"]),
            "truncated": row["truncated"],
            "evidence_total": row["evidenceTotal"],
            "read_fields": row["readFields"],
            "writer_methods": sorted({
                agent_method(item["writerMethod"])
                for item in row["evidence"]
                if item.get("writerMethod", "").startswith(
                    "<org.apache.hadoop.")
            }),
        })
    result = {
        "system": "hdfs", "version": "3.4.3", "source": str(SOURCE),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "population": 532, "seed": SEED,
        "sampling": "first 10: Random(seed).sample(YES, 10); next 40: same RNG.sample(remaining YES, 40)",
        "sites": sites,
    }
    (HERE / "selected50.json").write_text(json.dumps(result, indent=2) + "\n")
    print("selected", len(sites), "unique sites; frozen first ten preserved")
    for site in sites[10:]:
        print("{:02d} {:5s} {}:{}".format(
            site["draw"], site["site_kind"], site["class"], site["line"]))


if __name__ == "__main__":
    main()
