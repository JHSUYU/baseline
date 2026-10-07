#!/usr/bin/env python3
"""Independently reconstruct HDFS-43 V2 target and actor evidence, read-only."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

CASE = Path(__file__).resolve().parents[1]
CAMP = CASE / "campaign"
TEST = "org.apache.hadoop.hdfs.server.namenode.TestFileTruncate#testTruncateTwiceTogether"
SITE = "FSDirTruncateOp.truncate:113-117"
FILE = "/testTruncateTwiceTogether/file"
SELECTOR = ("marker", "api", "endpoint", "sourceRole", "path", "blockId",
            "requestedLength", "ordinal", "exception")


def require(condition: bool, message: str, problems: list[str]) -> None:
    if not condition:
        problems.append(message)


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def trace(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    if [r.get("seq") for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError(f"noncontiguous trace: {path}")
    return rows


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def point_id(r: dict) -> str:
    return "|".join(str(r.get(k)) for k in SELECTOR[:-1])


def family_id(r: dict) -> str:
    return "|".join(str(r.get(k)) for k in
                    ("marker", "api", "endpoint", "sourceRole", "path", "blockId"))


def role_map(rows: list[dict]) -> dict[str, str]:
    return {r["role"]: r["sourceUuid"] for r in rows
            if r.get("event") == "DN_ROLE_MAP"}


def nn_port(rows: list[dict]) -> int:
    endpoints = [r for r in rows if r.get("event") == "NN_ENDPOINT_MAP"
                 and r.get("endpoint") == "nn0"]
    if len(endpoints) != 1:
        return -1
    port = endpoints[0].get("remotePort")
    return port if isinstance(port, int) and port > 0 else -1


def guard(r: dict) -> bool:
    return (r.get("event") == "TARGET_GUARD" and r.get("site") == SITE
            and r.get("path") == FILE and isinstance(r.get("blockId"), int)
            and r["blockId"] >= 0
            and r.get("state") == "UNDER_RECOVERY"
            and r.get("phase") == "secondTruncate")


def relation(f: dict, t: dict, mapping: dict[str, str],
             rows: list[dict]) -> str | None:
    if f.get("seq", 0) >= t["seq"] or f.get("endpoint") != "nn0":
        return None
    if f.get("api") == "truncate":
        if (f.get("sourceRole") != "client" or f.get("sourceUuid") or
                f.get("path") != t["path"]):
            return None
        bound = [entry for entry in rows
                 if entry.get("event") == "TRUNCATE_FILE_BLOCK"
                 and entry["seq"] < t["seq"]
                 and entry.get("rpcKey") == f.get("rpcKey")
                 and entry.get("path") == t["path"]
                 and entry.get("requestedLength") == f.get("requestedLength")
                 and entry.get("blockId") in
                 (t["blockId"], t["truncateBlockId"])]
        if len(bound) != 1:
            return None
        if f.get("requestedLength") == t["requestedLength"]:
            return "same_rpc_block" if f.get("rpcKey") == t["rpcKey"] else None
        if (f.get("requestedLength") == t["inProgressLength"] and
                f.get("phase") == "firstTruncate"):
            return "same_file_block_precursor"
    if f.get("api") == "blockReceivedAndDeleted":
        role = f.get("sourceRole")
        if (role in mapping and f.get("sourceUuid") == mapping[role]
                and f.get("blockId") in (t["blockId"], t["truncateBlockId"])):
            return "same_block_report"
    return None


def coverage(path: Path) -> tuple[set[str], str]:
    compressed = path / "coverage.tsv.gz"
    plain = gzip.decompress(compressed.read_bytes()) if compressed.is_file() else (
        path / "coverage.tsv").read_bytes()
    lines = [line for line in plain.decode().splitlines() if line]
    if len(lines) != len(set(lines)):
        raise ValueError(f"duplicate coverage IDs in {path}")
    for line in lines:
        kind, identifier = line.split("\t", 1)
        if (kind not in ("METHOD", "BRANCH_UNIT", "PROBE") or
                not identifier.startswith(("org/apache/hadoop/hdfs/",
                                           "org/apache/hadoop/ipc/")) or
                "hdfs43actor" in identifier or "TestFileTruncate" in identifier):
            raise ValueError(f"nonproduction coverage ID: {line}")
    return set(lines), sha(plain)


def run(limit: int = 0) -> dict:
    problems: list[str] = []
    state_bytes = (CAMP / "checkpoint.json").read_bytes()
    state = json.loads(state_bytes)
    require(state.get("case_id") == "HDFS-43" and state.get("test") == TEST,
            "checkpoint case/test mismatch", problems)
    receipt = CASE / "system-test/build-probe.json"
    require(state.get("source_build_sha256") == sha(receipt.read_bytes()),
            "instrumentation receipt differs", problems)
    healthy = CASE / "healthy/actor-seed"
    healthy_manifest = read(healthy / "manifest.json")
    healthy_trace = trace(healthy / "trace/runtime_trace.jsonl")
    healthy_target = [r for r in healthy_trace if guard(r)]
    require(healthy_manifest.get("test") == TEST and healthy_manifest.get("exit") == 0
            and len(healthy_target) == 1, "original healthy target differs", problems)
    if healthy_target:
        require(all(healthy_target[0].get(key) == value for key, value in
                    state["healthy_target"].items()),
                "healthy target actor differs from checkpoint", problems)
    mapping = role_map(healthy_trace)
    healthy_port = nn_port(healthy_trace)
    require(set(mapping) == {"dn0", "dn1", "dn2"} and
            len(set(mapping.values())) == 3, "healthy DN role map differs", problems)
    require(healthy_port > 0, "healthy NN physical endpoint missing", problems)
    if healthy_target:
        require(any(r.get("event") == "IO_OBSERVED" and r.get("api") == "truncate"
                    and r.get("endpoint") == "nn0"
                    and r.get("remotePort") == healthy_port
                    and r.get("requestedLength") == healthy_target[0]["requestedLength"]
                    and r.get("rpcKey") == healthy_target[0]["rpcKey"]
                    for r in healthy_trace), "healthy client/server RPC key differs", problems)
    union, _ = coverage(healthy)
    io_union = {point_id(r) for r in healthy_trace if r.get("event") == "IO_OBSERVED"}
    family_union = {family_id(r) for r in healthy_trace if r.get("event") == "IO_OBSERVED"}
    completed = state.get("completed", [])
    end = min(limit, len(completed)) if limit else len(completed)
    summaries = []
    for n, checkpoint_row in enumerate(completed[:end], 1):
        label = f"trial-{n:03d}"
        out = CAMP / label
        row = read(out / "trial-result.json")
        require(row == checkpoint_row, f"{label}: checkpoint/row mismatch", problems)
        plan = (CAMP / "plans" / (label + ".tsv")).read_text()
        expected_plan = "".join("\t".join(str(p[k]) for k in SELECTOR) + "\n"
                                for p in row["sequence"])
        require(plan == expected_plan, f"{label}: selector plan mismatch", problems)
        manifest = read(out / "manifest.json")
        require(manifest.get("test") == TEST and manifest.get("exit") == row["junit_exit"],
                f"{label}: original JUnit identity/exit mismatch", problems)
        require((out / "jacoco.exec").is_file() and
                (out / "jacoco.exec").stat().st_size > 0,
                f"{label}: raw JaCoCo exec missing", problems)
        rows = trace(out / "trace/runtime_trace.jsonl")
        mapping = role_map(rows)
        port = nn_port(rows)
        mapped = set(mapping) == {"dn0", "dn1", "dn2"} and len(set(mapping.values())) == 3
        matched = [r for r in rows if r.get("event") == "FAULT_MATCHED"]
        applied = [r for r in rows if r.get("event") == "FAULT_APPLIED"]
        for event in matched:
            at = event["seq"] - 1
            preceding = rows[at - 1] if at >= 1 else {}
            following = rows[at + 1] if at + 1 < len(rows) else {}
            require(preceding.get("event") == "IO_OBSERVED" and
                    following.get("event") == "FAULT_APPLIED" and
                    all(preceding.get(k) == event.get(k) == following.get(k)
                        for k in SELECTOR[:-1]),
                    f"{label}: observed/matched/applied adjacency differs", problems)
        selectors_match = ([tuple(p.get(k) for k in SELECTOR) for p in applied] ==
                           [tuple(p[k] for k in SELECTOR) for p in row["sequence"]]
                           and len(matched) == len(row["sequence"]))
        physical = port > 0 and all(p.get("remotePort") == port and
                       ((p.get("sourceRole") == "client" and not p.get("sourceUuid"))
                       if p.get("api") == "truncate" else
                       (p.get("sourceRole") in mapping and
                        p.get("sourceUuid") == mapping[p["sourceRole"]]))
                       for p in applied)
        strict = mapped and physical and selectors_match
        last = max((p["seq"] for p in applied), default=-1)
        post = [r for r in rows if guard(r) and r["seq"] > last >= 0]
        target = next((t for t in post if all(relation(p, t, mapping, rows)
                                              for p in applied)), None)
        valid = strict and target is not None
        relations = [relation(p, target, mapping, rows) for p in applied] if target else []
        exceptions = [r for r in rows if r.get("event") == "TARGET_EXCEPTION" and
                      target is not None and r["seq"] > target["seq"] and
                      all(r.get(k) == target.get(k) for k in
                          ("path", "blockId", "rpcKey", "ordinal"))]
        expected = (valid and target.get("equal") is False and len(exceptions) == 1
                    and exceptions[0].get("type") ==
                    "org.apache.hadoop.hdfs.protocol.AlreadyBeingCreatedException"
                    and "is being truncated" in exceptions[0].get("message", ""))
        IDs, coverage_hash = coverage(out)
        new_cov = IDs - union if valid else set()
        observed = [r for r in rows if r.get("event") == "IO_OBSERVED"
                    and r.get("marker") == "RPC_RESPONSE_WAIT"]
        new_io = {point_id(r) for r in observed} - io_union if valid else set()
        new_family = {family_id(r) for r in observed} - family_union if valid else set()
        expected_fields = {
            "strict_injection": strict, "role_map_confirmed": mapped,
            "name_node_port": port, "name_node_port_confirmed": port > 0,
            "physical_source_confirmed": physical, "last_applied_seq": last,
            "target_after_fault_same_actor": valid,
            "post_fault_target_guard": target,
            "fault_target_relationships": relations,
            "post_fault_target_exception_count": len(exceptions),
            "expected_original_guard_response": expected,
            "coverage_ids": len(IDs), "coverage_tsv_sha256": coverage_hash,
            "new_coverage_ids": sorted(new_cov),
            "new_coverage_count": len(new_cov),
            "new_io_point_ids": sorted(new_io),
            "new_io_family_ids": sorted(new_family),
            "bug_mark": "candidate" if valid and not expected else "none",
        }
        for key, value in expected_fields.items():
            require(row.get(key) == value, f"{label}: {key} differs", problems)
        union.update(new_cov)
        io_union.update(new_io)
        family_union.update(new_family)
        summaries.append({"trial": n, "strict": strict, "effective": valid,
                          "expected_guard": expected,
                          "new_coverage": len(new_cov),
                          "new_io_families": len(new_family)})
    ledger = list(csv.DictReader((CAMP / "trial-ledger.csv").open()))
    require(len(ledger) >= end, "ledger shorter than checkpoint", problems)
    for n, row in enumerate(ledger[:end], 1):
        expected = completed[n - 1]
        for key in ("trial", "id", "status", "requested_faults", "matched_faults",
                    "applied_faults", "strict_injection", "target_after_fault_same_actor",
                    "post_fault_target_exception_count", "junit_exit", "elapsed_seconds",
                    "new_coverage_count", "bug_mark", "sequence_id"):
            require(row.get(key) == str(expected.get(key, "")),
                    f"ledger {n}: {key} differs", problems)
    all_effective = [r for r in completed if r["target_after_fault_same_actor"]]
    gate_reached = len(all_effective) >= 80
    novelty = (any(r["new_coverage_ids"] or r["new_io_family_ids"]
                   for r in all_effective[72:80]) if gate_reached else None)
    if state.get("extended"):
        require(gate_reached and novelty is True,
                "128-trial extension lacks novelty in effective trials 73-80", problems)
    if (state.get("stop_reason") == "effective_budget_reached" and
            not state.get("extended") and gate_reached):
        require(novelty is False,
                "80-trial stop ignored extension novelty", problems)
    return {"case_id": "HDFS-43", "checkpoint_sha256": sha(state_bytes),
            "audited_trials": end, "completed_at_snapshot": len(completed),
            "strict": sum(r["strict"] for r in summaries),
            "effective": sum(r["effective"] for r in summaries),
            "expected_guard": sum(r["expected_guard"] for r in summaries),
            "extension_gate_reached": gate_reached,
            "extension_gate_novelty": novelty,
            "extension_applied": bool(state.get("extended")),
            "errors": problems, "integrity_passed": not problems}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    report = run(args.limit)
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["integrity_passed"] else 1)
