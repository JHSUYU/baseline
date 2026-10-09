"""Create immutable, disjoint 102-case shards for local tmux schedulers."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HOSTS = ("node0", "node1", "node2")
SYSTEM_OWNER = {"hdfs": "node0", "hbase": "node1", "solr": "node2",
                "zookeeper": "node2"}
COMMAND = ["python3", "-m", "Mallory.core.campaign", "--config",
           "Mallory/cases/{case_id}.json", "--out", "data/mallory/cases/{case_id}"]


def stable_shards(selection: dict) -> dict[str, list[dict]]:
    checks = selection["checks"]
    if len(checks) != 102 or len({row["case_id"] for row in checks}) != 102:
        raise ValueError("selection must contain 102 distinct original checks")
    shards = {host: [] for host in HOSTS}
    ordered = sorted(checks, key=lambda row: (row["system"], row["case_id"]))
    for row in ordered:
        system = row["system"].lower()
        if system not in SYSTEM_OWNER:
            raise ValueError(f"unassigned system: {system}")
        shards[SYSTEM_OWNER[system]].append({"case_id": row["case_id"],
                                             "system": row["system"]})
    return shards


def write_immutable(path: Path, document: dict) -> None:
    encoded = json.dumps(document, sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise RuntimeError(f"existing shard ownership differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def generate(selection_path: Path, out: Path) -> dict:
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    shards = stable_shards(selection)
    selection_hash = hashlib.sha256(selection_path.read_bytes()).hexdigest()
    owner = {case["case_id"]: host for host, rows in shards.items() for case in rows}
    index = {"schema_version": 2, "selection_sha256": selection_hash,
             "shard_algorithm": "system_owner_v2",
             "system_owner": SYSTEM_OWNER,
             "hosts": list(HOSTS), "owner": owner,
             "counts": {host: len(rows) for host, rows in shards.items()}}
    write_immutable(out / "ownership.json", index)
    for host, rows in shards.items():
        write_immutable(out / f"{host}.json", {
            "schema_version": 2, "cohort": "original_102", "selection_sha256": selection_hash,
            "cases": rows, "default_command": COMMAND,
            "default_completion_file": "data/mallory/cases/{case_id}/result.json",
        })
        write_immutable(out / f"{host}-hosts.json", {
            "hosts": [{"name": host, "kind": "local", "slots": 1}]
        })
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=Path("data/crashfuzz/selection102.json"))
    parser.add_argument("--out", type=Path, default=Path("Mallory/dispatch/shards"))
    args = parser.parse_args()
    print(json.dumps(generate(args.selection, args.out)["counts"], sort_keys=True))
