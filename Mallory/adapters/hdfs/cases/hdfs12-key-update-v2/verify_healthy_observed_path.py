#!/usr/bin/env python3
"""Verify the exact HDFS-12 heartbeat-to-key-lookup healthy witness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import audit_timeline as timeline
from Mallory.core.graph import OccurrenceGraph


def one(rows: list[dict], **fields: object) -> dict:
    matches = [row for row in rows if all(row.get(key) == value for key, value in fields.items())]
    if len(matches) != 1:
        raise ValueError(f"expected one event for {fields}, found {len(matches)}")
    return matches[0]


def verify(rows: list[dict], admitted: dict) -> dict:
    if admitted.get("status") != "healthy_admitted":
        raise ValueError("case-local healthy audit did not admit the seed")
    by_id = {row["id"]: row for row in rows}
    command = by_id[admitted["command_id"]]
    add = by_id[admitted["add_id"]]
    lookup = by_id[admitted["lookup_id"]]
    target = by_id[admitted["target_id"]]
    if (command.get("type"), command.get("phase"), add.get("phase"),
            lookup.get("phase"), target.get("type")) != (
            "HDFS12_KEY", "nn_command_key", "dn_add_keys", "dn_lookup", "TARGET_CHECK"):
        raise ValueError("selected event types differ from the exact key path")
    if target.get("site") != timeline.CHECK:
        raise ValueError("wrong exact target site")
    if any(row.get("type") in ("TARGET_THROW", "FAULT_APPLIED") for row in rows):
        raise ValueError("healthy trace contains a target throw or applied fault")
    node, epoch, request = admitted["node"], admitted["epoch"], command["request"]
    if not (timeline.identity(command) and "/nn" in command["node"]
            and timeline.identity(add) and node.endswith("/dn0")
            and all((row.get("node"), row.get("epoch")) == (node, epoch)
                    for row in (add, lookup, target))
            and command.get("bpid") == add.get("bpid") == lookup.get("bpid")
            and command.get("key_id") == add.get("key_id") == lookup.get("key_id")
            and lookup.get("token_id") == admitted.get("token_id")):
        raise ValueError("named actor, epoch, block pool, key, or token differs")

    request_recv = one(rows, type="RECV", transport="hadoop-ipc",
                       correlation=request, port="request", node=command["node"])
    request_send = one(rows, type="SEND", transport="hadoop-ipc",
                       correlation=request, port="request", node=node)
    response_send = one(rows, type="SEND", transport="hadoop-ipc",
                        correlation=request, port="response", node=command["node"])
    response_recv = one(rows, type="RECV", transport="hadoop-ipc",
                        correlation=request, port="response", node=node)
    submits = [row for row in rows if row.get("type") == "TASK_SUBMIT"
               and row.get("node") == node and row.get("epoch") == epoch
               and timeline.before(response_recv, row) and timeline.before(row, add)]
    if len(submits) != 1:
        raise ValueError("response did not lead to a unique DN task submit")
    submit = submits[0]
    claim = one(rows, type="TASK_CLAIM", node=node,
                correlation=submit.get("correlation"))
    attempts = [row for row in timeline.key_rows(rows, "dn_heartbeat_attempt")
                if row.get("node") == node and row.get("epoch") == epoch
                and row.get("thread_id") == request_send.get("thread_id")
                and timeline.before(row, request_send)]
    if not attempts:
        raise ValueError("no named heartbeat attempt before the request")
    attempt = max(attempts, key=lambda row: row["ts"])
    doors = [row for row in rows if row.get("type") == "DOOR_OBSERVED"
             and row.get("site") == timeline.DOOR and row.get("node") == node
             and row.get("epoch") == epoch
             and row.get("thread_id") == attempt.get("thread_id")
             and row.get("occurrence") == request_send.get("occurrence")
             and timeline.before(attempt, row) and timeline.before(row, request_send)]
    if len(doors) != 1:
        raise ValueError("heartbeat attempt lacks one exact named I/O door")
    door = doors[0]
    writes = [row for row in rows if row.get("type") == "HDFS12_KEY_STATE"
              and row.get("phase") == "write" and row.get("node") == node
              and row.get("key_id") == add.get("key_id")
              and timeline.before(add, row) and timeline.before(row, lookup)]
    reads = [row for row in rows if row.get("type") == "HDFS12_KEY_STATE"
             and row.get("phase") == "read" and row.get("node") == node
             and row.get("key_id") == add.get("key_id")
             and timeline.before(lookup, row) and timeline.before(row, target)]
    if len(writes) != 1 or len(reads) != 1:
        raise ValueError("selected add/lookup lacks one observed map write/read")
    write, read = writes[0], reads[0]
    graph = OccurrenceGraph(rows, reject_coarse_roots=True)
    key_edges = timeline.exact_key_read_from(graph, rows)
    if not any(edge["write_id"] == write["id"] and edge["read_id"] == read["id"]
               for edge in key_edges):
        raise ValueError("exact synchronized map read-from edge is absent")
    ordered = (attempt, door, request_send, request_recv, command,
               response_send, response_recv, submit, claim, add,
               write, lookup, read, target)
    if not all(timeline.before(a, b) for a, b in zip(ordered, ordered[1:])):
        raise ValueError("heartbeat, RPC, task, key, target event order differs")
    path = timeline.graph_path(graph, door, target)
    if not path or [edge["kind"] for edge in path] != [
            "rpc", "rpc", "region_parent", "task", "region_parent", "key_read_from"]:
        raise ValueError("exact root-free door-to-target path differs")
    return {"status": "healthy_observed_path_verified",
            "node": node, "epoch": epoch, "request": request,
            "bpid": lookup["bpid"], "key_id": lookup["key_id"],
            "state_token": read["state_token"],
            "event_ids": {name: row["id"] for name, row in zip(
                ("attempt", "door", "request_send", "request_recv", "command",
                 "response_send", "response_recv", "task_submit", "task_claim",
                 "add_keys", "map_write", "lookup", "map_read", "target"), ordered)},
            "door_to_target_path": path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--healthy-audit", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        audit = json.loads(args.healthy_audit.read_text())
        if audit.get("events_sha256") != timeline.sha(args.events):
            raise ValueError("event trace SHA differs from case-local healthy audit")
        result = verify(timeline.read_events(args.events), audit)
        result.update({"schema_version": 1, "case_id": "HDFS-12",
                       "events_sha256": timeline.sha(args.events),
                       "healthy_audit_sha256": timeline.sha(args.healthy_audit),
                       "auditor_sha256": timeline.sha(Path(timeline.__file__)),
                       "config_sha256": timeline.sha(timeline.HERE / "HDFS-12-healthy-only.json")})
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"status": result["status"], "out": str(args.out)}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print(f"HDFS-12 observed-path verification rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
