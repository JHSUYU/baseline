#!/usr/bin/env python3
"""Two unchanged JUnit healthy seeds for the shared HDFS actor-aware overlay.

Run only after a host slot is released. The receipt deliberately rejects any
case whose target or candidate I/O cannot be bound to a startup actor.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
GROUPS = {
    "startup": ("HDFS-22", ("HDFS-22", "HDFS-23", "HDFS-25", "HDFS-34", "HDFS-35")),
    "upgrade": ("HDFS-24", ("HDFS-24", "HDFS-27")),
    "rollback": ("HDFS-26", ("HDFS-26", "HDFS-37")),
}


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def selector(row: dict) -> tuple:
    return tuple(row.get(field) for field in
                 ("marker", "siteId", "sourceKey", "hitOrdinal"))


def storage_volume(path: str | None) -> str:
    if not path or not path.startswith("dfs/data"):
        return "unbound"
    return path.split("/", 2)[0] + "/" + path.split("/", 2)[1]


def inspect(seed: Path, cases: tuple[str, ...]) -> dict:
    manifest = json.loads((seed / "manifest.json").read_text())
    trace = rows(seed / "runtime_trace.jsonl")
    targets = [r for r in trace if r["event"] == "TARGET_CHECK" and r.get("caseId") in cases]
    actors = [r for r in trace if r["event"] == "ACTOR_REGISTERED"]
    entries = [r for r in trace if r["event"] == "ACTOR_ENTER"]
    io = [r for r in trace if r["event"] == "FAULT_POINT_OBSERVED"]
    bound = [r for r in io if r.get("actorKey") != "unbound"
             and r.get("sourceKey") != "unbound"]
    rpc = [r for r in bound if "RPC:" in r["marker"] and r.get("peerRole") == "NN0"]
    file_io = [r for r in bound if "FILE:" in r["marker"]
               and r.get("storageKey") != "unbound"]
    actor_by_object: dict[int, str] = {}
    object_by_actor: dict[str, int] = {}
    for r in actors:
        actor, obj = r["actorKey"], r["dnObjectId"]
        if actor in object_by_actor and object_by_actor[actor] != obj:
            raise ValueError(f"actor collision: {actor}")
        if obj in actor_by_object and actor_by_object[obj] != actor:
            raise ValueError(f"DataNode object collision: {obj}")
        actor_by_object[obj] = actor
        object_by_actor[actor] = obj
    by_case = {case: [r for r in targets if r["caseId"] == case] for case in cases}
    eligible = {case: [r for r in bound if any(
        t["seq"] > r["seq"] and t.get("actorKey") == r.get("actorKey")
        and ("RPC:" in r["marker"] or
             (storage_volume(t.get("storageKey")) != "unbound" and
              storage_volume(t.get("storageKey")) == storage_volume(r.get("storageKey"))))
        for t in events)] for case, events in by_case.items()}
    issues = []
    if manifest["returncode"] != 0:
        issues.append("original JUnit did not pass")
    if not actors or not entries:
        issues.append("no DataNode registration or BPServiceActor adoption")
    if not rpc:
        issues.append("no actual RPC endpoint matched its actor NameNode")
    if not file_io:
        issues.append("no bound storage file I/O")
    for case, events in by_case.items():
        if not events:
            issues.append(f"{case} exact target not reached")
        elif any(e.get("actorKey") == "unbound" or e.get("storageKey") == "unbound"
                 for e in events):
            issues.append(f"{case} target lacks actor/storage identity")
        if not eligible[case]:
            issues.append(f"{case} no earlier I/O on the same actor/storage")
    if any(r.get("actorKey") == "unbound" for r in bound):
        issues.append("bound I/O has unbound actor")
    return {
        "manifest": str(seed / "manifest.json"),
        "trace_sha256": hashlib.sha256((seed / "runtime_trace.jsonl").read_bytes()).hexdigest(),
        "elapsed_seconds": manifest["elapsed_seconds"],
        "started_at_utc": manifest.get("started_at_utc"),
        "finished_at_utc": manifest.get("finished_at_utc"),
        "instrumentation_digest_sha256": manifest.get("instrumentation_digest_sha256"),
        "junit_exit": manifest["returncode"],
        "actors_registered": len(actors), "actor_entries": len(entries),
        "bound_rpc": len(rpc), "bound_file_io": len(file_io),
        "targets": {case: len(events) for case, events in by_case.items()},
        "eligible_io": {case: len(events) for case, events in eligible.items()},
        "selectors_by_case": {case: [list(selector(r)) for r in events]
                              for case, events in eligible.items()},
        "target_actors": {case: sorted({e["actorKey"] for e in events})
                          for case, events in by_case.items()},
        "selectors": [list(selector(r)) for r in bound],
        "issues": issues,
    }


def calibrate(group: str, output: Path, timeout: int, max_seeds: int = 2) -> dict:
    case, cases = GROUPS[group]
    output.mkdir(parents=True, exist_ok=True)
    seeds = []
    for suffix in ("a", "b")[:max_seeds]:
        seed = output / f"healthy-{suffix}"
        if not (seed / "manifest.json").is_file():
            with (output / f"runner-{suffix}.log").open("w") as log:
                subprocess.run([sys.executable, str(HERE / "run_original.py"), "--case", case,
                                "--output", str(seed), "--timeout", str(timeout)],
                               stdout=log, stderr=subprocess.STDOUT, check=False)
        if not (seed / "manifest.json").is_file():
            raise RuntimeError(f"missing healthy manifest for {suffix}")
        seeds.append(inspect(seed, cases))
    if max_seeds == 1:
        receipt = {
            "schema": "hdfs-storage-actor-v2-healthy-calibration-1",
            "group": group, "case_ids": list(cases),
            "test": json.loads((output / "healthy-a/manifest.json").read_text())["test"],
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "seeds": seeds, "status": "awaiting_second_seed",
            "pass": False, "issues": [f"healthy-a: {issue}" for issue in seeds[0]["issues"]],
        }
        temp = output / "healthy_receipt.json.tmp"
        temp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        temp.replace(output / "healthy_receipt.json")
        return receipt
    stable = sorted(set(map(tuple, seeds[0]["selectors"]))
                    & set(map(tuple, seeds[1]["selectors"])))
    issues = [f"healthy-{i}: {issue}" for i, seed in zip("ab", seeds)
              for issue in seed["issues"]]
    if not stable:
        issues.append("no stable exact actor-aware I/O selectors in two seeds")
    if (not seeds[0]["instrumentation_digest_sha256"] or
            seeds[0]["instrumentation_digest_sha256"] != seeds[1]["instrumentation_digest_sha256"]):
        issues.append("instrumentation digest differs across healthy seeds")
    stable_by_case = {}
    for case_id in cases:
        common = sorted(set(map(tuple, seeds[0]["selectors_by_case"][case_id]))
                        & set(map(tuple, seeds[1]["selectors_by_case"][case_id])))
        stable_by_case[case_id] = [list(item) for item in common]
        if not common:
            issues.append(f"{case_id} has no stable same-actor upstream selector")
        if seeds[0]["target_actors"][case_id] != seeds[1]["target_actors"][case_id]:
            issues.append(f"{case_id} target actor sequence differs across healthy seeds")
    receipt = {
        "schema": "hdfs-storage-actor-v2-healthy-calibration-1",
        "group": group, "case_ids": list(cases),
        "test": json.loads((output / "healthy-a/manifest.json").read_text())["test"],
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "seeds": seeds,
        "stable_selectors": [list(item) for item in stable],
        "stable_selector_count": len(stable),
        "stable_selectors_by_case": stable_by_case,
        "status": "pass" if not issues else "failed",
        "pass": not issues, "issues": issues,
    }
    temp = output / "healthy_receipt.json.tmp"
    temp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temp.replace(output / "healthy_receipt.json")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=GROUPS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--max-seeds", type=int, choices=(1, 2), default=2,
                        help="Use 1 to pause after seed a; rerun with 2 to reuse a and run b")
    args = parser.parse_args()
    receipt = calibrate(args.group, args.output.resolve(), args.timeout, args.max_seeds)
    print(json.dumps({k: receipt[k] for k in
                      ("group", "status", "pass", "issues")}, indent=2))
    if receipt["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
