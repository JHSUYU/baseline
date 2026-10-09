#!/usr/bin/env python3
"""Fail-closed HDFS-12 named healthy and R1/H1/R2/H2 timeline audit."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(BASE))
from Mallory.core.graph import OccurrenceGraph

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "HDFS-12-healthy-only.json").read_text())
CHECK = CONFIG["target"]["check_sites"][0]
THROW = CONFIG["target"]["throw_site"]
DOOR_SPEC = json.loads((HERE / "HDFS-12.sites.json").read_text())["doors"][0]
DOOR = (f"{DOOR_SPEC['clazz']}#{DOOR_SPEC['method']}"
        f"{DOOR_SPEC['descriptor']}@{DOOR_SPEC['line']}:door:1")
TEST_CLASS = "org.apache.hadoop.hdfs.TestEncryptedTransfer"
TEST_NAME = "testLongLivedClient[0]"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_events(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if not rows or any(row.get("type") == "TRACE_TRUNCATED" for row in rows):
        raise ValueError("missing or truncated event trace")
    if len({row.get("id") for row in rows}) != len(rows):
        raise ValueError("duplicate event IDs")
    return rows


def junit_method(path: Path, require_pass: bool) -> dict:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if len(cases) != 1:
        raise ValueError(f"indexed selector executed {len(cases)} tests, expected one")
    case = cases[0]
    # Surefire appends the per-trial mallory suffix to the Java class name.
    # Accept only that exact generated shape, with one indexed method.
    class_name = case.get("classname", "")
    expected = re.escape(TEST_CLASS) + r"(?:\(mallory_[0-9]{4}_[0-9a-f]{32}\))?"
    if not re.fullmatch(expected, class_name) or case.get("name") != TEST_NAME:
        raise ValueError(f"unexpected JUnit method {case.get('classname')}#{case.get('name')}")
    faults = [element.tag for element in case if element.tag in ("failure", "error", "skipped")]
    if require_pass and faults:
        raise ValueError(f"healthy JUnit did not pass: {faults}")
    return {"class": TEST_CLASS, "name": TEST_NAME, "outcomes": faults}


def before(a: dict, b: dict) -> bool:
    return isinstance(a.get("ts"), int) and isinstance(b.get("ts"), int) and a["ts"] < b["ts"]


def key_rows(rows: list[dict], phase: str) -> list[dict]:
    return [row for row in rows if row.get("type") == "HDFS12_KEY"
            and row.get("phase") == phase]


def identity(row: dict) -> bool:
    return (isinstance(row.get("node"), str) and row["node"].startswith("hdfs-cluster-")
            and row.get("node") != "unknown" and isinstance(row.get("epoch"), int)
            and row["epoch"] >= 0)


def token_lookup(rows: list[dict], nonthrowing: bool) -> list[tuple[dict, dict]]:
    result = []
    for lookup in key_rows(rows, "dn_lookup"):
        if not (identity(lookup) and "/dn" in lookup["node"]
                and lookup.get("bpid") and lookup.get("bpid") == lookup.get("owner_bpid")
                and isinstance(lookup.get("key_id"), int)
                and isinstance(lookup.get("token_id"), str)
                and len(lookup["token_id"]) == 64
                and lookup.get("request") not in (None, "", "root", "lost")
                and isinstance(lookup.get("expiry_ms"), int)
                and isinstance(lookup.get("wall_time_ms"), int)
                and lookup["expiry_ms"] > lookup["wall_time_ms"]):
            continue
        following = [row for row in rows if row.get("type") == "TARGET_CHECK"
                     and row.get("site") == CHECK and before(lookup, row)
                     and (row.get("node"), row.get("epoch"), row.get("thread_id"),
                          row.get("context")) ==
                         (lookup.get("node"), lookup.get("epoch"),
                          lookup.get("thread_id"), lookup.get("context"))]
        next_lookup = min((row["ts"] for row in key_rows(rows, "dn_lookup")
                           if row.get("thread_id") == lookup.get("thread_id")
                           and before(lookup, row)), default=None)
        following = [row for row in following if next_lookup is None or row["ts"] < next_lookup]
        if len(following) != 1:
            continue
        target = following[0]
        if target.get("outcome") != ("TAKEN" if nonthrowing else "FALLTHROUGH"):
            continue
        result.append((lookup, target))
    return result


def bound_peer(rows: list[dict], lookup: dict) -> str | None:
    matches = [row.get("peer") for row in key_rows(rows, "dn_bind")
               if row.get("node") == lookup.get("node")
               and row.get("epoch") == lookup.get("epoch")
               and before(row, lookup) and row.get("peer")]
    return matches[-1] if len(set(matches)) == 1 else None


def minted(rows: list[dict], lookup: dict, after: dict | None = None) -> dict | None:
    candidates = [row for row in key_rows(rows, "nn_token_mint")
                  if identity(row) and "/nn" in row["node"]
                  and row.get("bpid") == lookup.get("bpid")
                  and row.get("owner_bpid") == lookup.get("bpid")
                  and row.get("key_id") == lookup.get("key_id")
                  and row.get("token_id") == lookup.get("token_id")
                  and row.get("expiry_ms") == lookup.get("expiry_ms")
                  and row.get("request") not in (None, "", "root", "lost")
                  and before(row, lookup)
                  and (after is None or before(after, row))]
    # createPassword can be called twice with the same identifier in one NN
    # request. Each hook is a real call; group only fully identical token
    # identity, expiry, request, actor and thread, then retain the last event.
    identities = {(row.get("node"), row.get("epoch"), row.get("thread_id"),
                   row.get("request"), row.get("bpid"), row.get("key_id"),
                   row.get("token_id"), row.get("expiry_ms")) for row in candidates}
    return candidates[-1] if len(identities) == 1 else None


def graph_path(graph: OccurrenceGraph, source: dict, target: dict) -> list[dict] | None:
    path = graph.event_path(source, target, require_edge=True)
    if path is None:
        return None
    return [{"source": edge.source, "target": edge.target, "kind": edge.kind} for edge in path]


def exact_key_read_from(graph: OccurrenceGraph, rows: list[dict]) -> list[dict]:
    """Extend this case's graph only for a proven synchronized map read-from.

    The adapter observes the actual returned BlockKey reference while
    retrievePassword holds the same manager monitor used by addKeys. It gives
    each manager and value JVM identity plus a per-key version. A later write,
    removal or identity gap prevents a read-from edge.
    """
    states = [row for row in rows if row.get("type") == "HDFS12_KEY_STATE"]
    added = []
    for read in states:
        if read.get("phase") != "read" or read.get("matched") is not True:
            continue
        if not (identity(read) and isinstance(read.get("manager_id"), int)
                and read["manager_id"] > 0 and isinstance(read.get("key_id"), int)
                and isinstance(read.get("version"), int) and read["version"] > 0
                and isinstance(read.get("value_id"), int) and read["value_id"] > 0
                and isinstance(read.get("state_token"), str) and read.get("bpid")):
            continue
        matches = [write for write in states
                   if write.get("phase") == "write" and write.get("matched") is True
                   and all(write.get(field) == read.get(field) for field in
                           ("node", "epoch", "manager_id", "key_id", "version",
                            "value_id", "state_token", "bpid"))
                   and before(write, read)]
        if len(matches) != 1:
            continue
        write = matches[0]
        if any(other is not write and other is not read
               and other.get("manager_id") == read["manager_id"]
               and other.get("key_id") == read["key_id"]
               and before(write, other) and before(other, read)
               and other.get("phase") in ("write", "remove", "write_gap", "read_gap")
               for other in states):
            continue
        graph._add(write, read, "key_read_from",
                   "same_monitor_manager_key_value_version")
        added.append({"write_id": write["id"], "read_id": read["id"],
                      "state_token": read["state_token"]})
    return added


def healthy(rows: list[dict]) -> dict:
    if any(row.get("type") == "FAULT_APPLIED" for row in rows):
        raise ValueError("healthy trace contains an applied fault")
    if any(row.get("type") == "TARGET_THROW" and row.get("site") == THROW for row in rows):
        raise ValueError("healthy trace contains selected throw")
    graph = OccurrenceGraph(rows, reject_coarse_roots=True)
    key_edges = exact_key_read_from(graph, rows)
    for lookup, target in token_lookup(rows, nonthrowing=True):
        peer = bound_peer(rows, lookup)
        mint = minted(rows, lookup)
        if peer is None or mint is None:
            continue
        adds = [row for row in key_rows(rows, "dn_add_keys")
                if (row.get("node"), row.get("epoch"), row.get("bpid"), row.get("key_id")) ==
                   (lookup["node"], lookup["epoch"], lookup["bpid"], lookup["key_id"])
                and before(row, lookup)]
        commands = [row for row in key_rows(rows, "nn_command_key")
                    if row.get("peer") == peer and row.get("bpid") == lookup["bpid"]
                    and row.get("key_id") == lookup["key_id"] and identity(row)]
        for command in commands:
            for add in adds:
                if not before(command, add):
                    continue
                first = graph_path(graph, command, add)
                second = graph_path(graph, add, target)
                if first and second:
                    return {"status": "healthy_admitted", "node": lookup["node"],
                            "epoch": lookup["epoch"], "peer": peer, "bpid": lookup["bpid"],
                            "key_id": lookup["key_id"], "token_id": lookup["token_id"],
                            "request": lookup["request"], "mint_id": mint["id"],
                            "command_id": command["id"], "add_id": add["id"],
                            "lookup_id": lookup["id"], "target_id": target["id"],
                            "command_to_add_path": first, "add_to_target_path": second,
                            "exact_key_edges": key_edges}
    raise ValueError("no named nonthrowing token lookup with exact mint, addKeys, and strict graph paths")


def matching_door(rows: list[dict], attempt: dict, next_attempt: dict | None) -> tuple[dict, list[dict]]:
    doors = [row for row in rows if row.get("type") == "DOOR_OBSERVED"
             and row.get("site") == DOOR and before(attempt, row)
             and (next_attempt is None or before(row, next_attempt))
             and (row.get("node"), row.get("epoch"), row.get("thread_id")) ==
                 (attempt.get("node"), attempt.get("epoch"), attempt.get("thread_id"))]
    if len(doors) != 1:
        raise ValueError("heartbeat attempt did not resolve to one exact door")
    door = doors[0]
    faults = [row for row in rows if row.get("type") == "FAULT_APPLIED"
              and (row.get("site"), row.get("node"), row.get("epoch"),
                   row.get("door_ordinal"), row.get("hit"), row.get("occurrence")) ==
                  (door.get("site"), door.get("node"), door.get("epoch"),
                   door.get("door_ordinal"), door.get("hit"), door.get("occurrence"))]
    return door, faults


def pilot(rows: list[dict], healthy_receipt: dict) -> dict:
    if healthy_receipt.get("status") != "healthy_admitted":
        raise ValueError("no admitted healthy receipt")
    if healthy_receipt.get("config_sha256") != sha(HERE / "HDFS-12-healthy-only.json"):
        raise ValueError("healthy receipt uses a different pinned config")
    faults_all = [row for row in rows if row.get("type") == "FAULT_APPLIED"]
    if not 1 <= len(faults_all) <= 2 or any(row.get("site") != DOOR for row in faults_all):
        raise ValueError("pilot requires one or two selected heartbeat faults only")
    graph = OccurrenceGraph(rows, reject_coarse_roots=True)
    exact_key_read_from(graph, rows)
    attempts = key_rows(rows, "dn_heartbeat_attempt")
    for lookup, target in token_lookup(rows, nonthrowing=False):
        peer = bound_peer(rows, lookup)
        if peer is None:
            continue
        if not any(row.get("type") == "TARGET_THROW" and row.get("site") == THROW
                   and (row.get("node"), row.get("epoch"), row.get("thread_id")) ==
                       (target.get("node"), target.get("epoch"), target.get("thread_id"))
                   and before(target, row) for row in rows):
            continue
        bpid, key_id = lookup["bpid"], lookup["key_id"]
        rotations = [row for row in key_rows(rows, "nn_rotation_next")
                     if identity(row) and "/nn" in row["node"]
                     and row.get("bpid") == bpid and row.get("key_id") == key_id
                     and before(row, lookup)]
        for r1 in rotations:
            r2s = [row for row in key_rows(rows, "nn_rotation_current")
                   if (row.get("node"), row.get("epoch"), row.get("bpid"), row.get("key_id")) ==
                      (r1["node"], r1["epoch"], bpid, key_id)
                   and before(r1, row) and before(row, lookup)]
            for r2 in r2s:
                mint = minted(rows, lookup, after=r2)
                if mint is None:
                    continue
                pending = [row for row in key_rows(rows, "nn_pending_true")
                           if row.get("node") == r1["node"] and row.get("epoch") == r1["epoch"]
                           and row.get("bpid") == bpid and row.get("key_id") == key_id
                           and row.get("peer") == peer and before(r1, row)
                           and before(row, r2)]
                if not pending:
                    continue
                same_actor = [row for row in attempts
                              if row.get("node") == lookup["node"]
                              and row.get("epoch") == lookup["epoch"]
                              and row.get("bpid") == bpid and row.get("peer") == peer
                              and row.get("actor_ref")
                              and before(r1, row)]
                same_actor.sort(key=lambda row: row["ts"])
                for index in range(len(same_actor) - 1):
                    h1, h2 = same_actor[index:index+2]
                    if h1["actor_ref"] != h2["actor_ref"]:
                        continue
                    if not (before(r1, h1) and before(h1, r2) and before(r2, h2)):
                        continue
                    try:
                        door1, faults1 = matching_door(rows, h1, h2)
                        next_attempt = same_actor[index+2] if index+2 < len(same_actor) else None
                        door2, faults2 = matching_door(rows, h2, next_attempt)
                    except ValueError:
                        continue
                    if len(faults1) != 1 or len(faults2) != len(faults_all) - 1:
                        continue
                    if len(faults_all) == 2 and (next_attempt is None
                                                  or next_attempt.get("actor_ref") != h1["actor_ref"]):
                        continue
                    if {row["id"] for row in faults1 + faults2} != {row["id"] for row in faults_all}:
                        continue
                    if any(row.get("node") == lookup["node"]
                           and row.get("epoch") == lookup["epoch"]
                           and row.get("bpid") == bpid and row.get("key_id") == key_id
                           and before(row, lookup) for row in key_rows(rows, "dn_add_keys")):
                        continue
                    path = graph_path(graph, door1, target)
                    return {"status": "strict_pilot_candidate" if path else "timing_only",
                            "fault_count": len(faults_all), "node": lookup["node"],
                            "epoch": lookup["epoch"], "peer": peer, "bpid": bpid,
                            "key_id": key_id, "token_id": lookup["token_id"],
                            "r1_id": r1["id"], "h1_id": h1["id"],
                            "r2_id": r2["id"], "h2_id": h2["id"],
                            "mint_id": mint["id"], "lookup_id": lookup["id"],
                            "target_id": target["id"], "door_ids": [door1["id"], door2["id"]],
                            "fault_ids": [row["id"] for row in faults_all],
                            "strict_fault_to_target_path": path}
    raise ValueError("no exact R1<H1<R2<H2 token/actor timeline with selected lookup")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("healthy", "pilot"))
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--junit-xml", required=True, type=Path)
    parser.add_argument("--healthy-receipt", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        method = junit_method(args.junit_xml, require_pass=args.mode == "healthy")
        rows = read_events(args.events)
        if args.mode == "healthy":
            audit = healthy(rows)
        else:
            if args.healthy_receipt is None:
                raise ValueError("pilot requires --healthy-receipt")
            audit = pilot(rows, json.loads(args.healthy_receipt.read_text()))
        output = {"schema_version": 1, "case_id": "HDFS-12", **audit,
                  "junit_method": method, "events_path": str(args.events.resolve()),
                  "events_sha256": sha(args.events),
                  "junit_path": str(args.junit_xml.resolve()),
                  "junit_sha256": sha(args.junit_xml),
                  "config_sha256": sha(HERE / "HDFS-12-healthy-only.json")}
        args.out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"status": output["status"], "out": str(args.out)}))
        return 0 if output["status"] in ("healthy_admitted", "strict_pilot_candidate") else 2
    except (OSError, ValueError, KeyError, TypeError) as failure:
        print(f"HDFS-12 audit rejected: {failure}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
