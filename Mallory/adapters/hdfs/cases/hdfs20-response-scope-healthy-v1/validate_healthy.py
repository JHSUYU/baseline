#!/usr/bin/env python3
"""Require an exact heartbeat RPC response to reach HDFS-20's healthy check."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
CONFIG = HERE / "HDFS-20-response-scope-healthy-v1.json"
HEARTBEAT_DOOR = ("org.apache.hadoop.hdfs.server.datanode.BPServiceActor"
                  "#sendHeartBeat(Z)Lorg/apache/hadoop/hdfs/server/protocol/"
                  "HeartbeatResponse;@563:door:")
RESPONSE_SITE = "org.apache.hadoop.ipc.Client#getRpcResponse"
REQUEST_SITE = "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest"
SERVER_REQUEST_SITE = "org.apache.hadoop.ipc.Server.RpcCall#run"
SERVER_RESPONSE_SITE = "org.apache.hadoop.ipc.Server.Connection#sendResponse"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _named(event: dict, role: str) -> bool:
    node = event.get("node")
    return (isinstance(node, str) and
            re.search(r"/" + role + r"[0-9]+$", node) is not None and
            type(event.get("epoch")) is int and event["epoch"] >= 0 and
            type(event.get("thread_id")) is int)


def _seq(event: dict) -> int:
    value = event.get("seq")
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _same_actor_thread(left: dict, right: dict) -> bool:
    return all(left.get(key) == right.get(key)
               for key in ("node", "epoch", "thread_id"))


def _rpc(event: dict, kind: str, port: str, site: str) -> bool:
    return (event.get("type") == kind and event.get("transport") == "hadoop-ipc"
            and event.get("port") == port and event.get("site") == site and
            isinstance(event.get("correlation"), str) and event["correlation"])


def evaluate(events: tuple[dict, ...], config: dict) -> dict:
    """Find one unique-token, named-actor, root-free-after-anchor witness."""
    sys.path.insert(0, str(config["core_release"]))
    from Mallory.core.events import event_address
    from Mallory.core.graph import OccurrenceGraph

    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    by_id = {e.get("id"): e for e in events if isinstance(e.get("id"), str)}
    rpc_pairs = {(edge.producer_event, edge.consumer_event)
                 for edge in graph.edges if edge.kind == "rpc"
                 and edge.certainty == "observed"}
    target_sites = set(config["target"]["check_sites"])
    # The exact bytecode region is the prefix of either configured check site.
    target_region = next(iter(target_sites)).split("@", 1)[0]
    targets = [e for e in events if e.get("type") == "TARGET_CHECK"
               and e.get("site") in target_sites and e.get("region") == target_region
               and _named(e, "dn")]
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"
             and str(e.get("site", "")).startswith(HEARTBEAT_DOOR) and _named(e, "dn")]
    requests = [e for e in events if _rpc(e, "SEND", "request", REQUEST_SITE)
                and _named(e, "dn")]
    server_receives = [e for e in events if _rpc(e, "RECV", "request", SERVER_REQUEST_SITE)
                       and _named(e, "nn")]
    server_sends = [e for e in events if _rpc(e, "SEND", "response", SERVER_RESPONSE_SITE)
                    and _named(e, "nn")]
    responses = [e for e in events if _rpc(e, "RECV", "response", RESPONSE_SITE)
                 and _named(e, "dn")]
    by_token: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for kind, rows in (("request", requests), ("server_receive", server_receives),
                       ("server_send", server_sends), ("response", responses)):
        for row in rows:
            by_token[row["correlation"]][kind].append(row)
    counts = Counter(target_checks=len(targets), heartbeat_doors=len(doors),
                     named_requests=len(requests), named_server_receives=len(server_receives),
                     named_server_sends=len(server_sends), named_response_receives=len(responses))

    for target in sorted(targets, key=_seq):
        for response in by_token.values():
            for recv in response["response"]:
                if (_seq(recv) >= _seq(target) or
                        not _same_actor_thread(recv, target) or
                        recv.get("context") != recv["correlation"] or
                        target.get("context") != recv["correlation"] or
                        not graph._is_scoped_unscoped(recv)):
                    continue
                counts["exact_named_response_before_target"] += 1
                path = graph.event_path(recv, target, require_edge=True)
                if not path or path[0].producer_event != recv.get("id"):
                    continue
                # The exact response RECV is the sole permitted scoped root
                # endpoint. Every continuation edge after it enters a named
                # region; no actor-wide, legacy, or intermediate root counts.
                valid_path = True
                for index, edge in enumerate(path):
                    producer = by_id.get(edge.producer_event)
                    consumer = by_id.get(edge.consumer_event)
                    if (edge.certainty != "observed" or producer is None or
                            consumer is None or
                            (index == 0 and edge.source != event_address(recv)) or
                            (index > 0 and str(producer.get("occurrence", "")).startswith(
                                "unscoped:")) or
                            str(consumer.get("occurrence", "")).startswith("unscoped:")):
                        valid_path = False
                        break
                if not valid_path:
                    continue
                first_consumer = by_id.get(path[0].consumer_event)
                if (path[0].kind != "region_parent" or first_consumer is None or
                        first_consumer.get("type") != "REGION_ENTER" or
                        first_consumer.get("region") != target_region or
                        not _same_actor_thread(recv, first_consumer)):
                    continue
                counts["root_free_event_time_response_paths"] += 1
                token = recv["correlation"]
                for sent in response["server_send"]:
                    if ((sent.get("id"), recv.get("id")) not in rpc_pairs or
                            not _named(sent, "nn") or _seq(sent) >= _seq(recv)):
                        continue
                    for req in response["request"]:
                        if (not _same_actor_thread(req, recv) or
                                not (_seq(req) < _seq(recv))):
                            continue
                        for accepted in response["server_receive"]:
                            if ((req.get("id"), accepted.get("id")) not in rpc_pairs or
                                    not (_seq(req) < _seq(accepted) < _seq(sent)) or
                                    (accepted.get("node"), accepted.get("epoch")) !=
                                    (sent.get("node"), sent.get("epoch"))):
                                continue
                            matching_doors = [door for door in doors
                                              if _same_actor_thread(door, req)
                                              and _seq(door) < _seq(req)]
                            if not matching_doors:
                                continue
                            door = max(matching_doors, key=_seq)
                            if any(_same_actor_thread(other, req) and
                                   _seq(door) < _seq(other) < _seq(req)
                                   for other in requests):
                                continue
                            return {
                                "status": "pass", "case_id": "HDFS-20",
                                "criterion": "exact_heartbeat_request_and_response_to_named_target",
                                "root_policy": "sole_scoped_response_recv_endpoint; no root intermediary",
                                "token": token,
                                "node": recv["node"], "epoch": recv["epoch"],
                                "thread_id": recv["thread_id"],
                                "nn_node": sent["node"], "nn_epoch": sent["epoch"],
                                "events": {name: {"id": item["id"], "seq": _seq(item)}
                                           for name, item in (("door", door), ("request_send", req),
                                                              ("request_recv", accepted),
                                                              ("response_send", sent),
                                                              ("response_recv", recv),
                                                              ("target_check", target))},
                                "event_time_path": [edge.__dict__ for edge in path],
                                "graph": graph.summary(), "diagnostics": dict(counts),
                            }
    return {"status": "fail", "case_id": "HDFS-20",
            "reason": "no_exact_named_heartbeat_response_event_time_path",
            "root_policy": "sole_scoped_response_recv_endpoint; no root intermediary",
            "graph": graph.summary(), "diagnostics": dict(counts)}


def validate_output(out: Path) -> dict:
    config = json.loads(CONFIG.read_text())
    trial = out / "trials/r0000"
    result = json.loads((trial / "result.json").read_text())
    if (result.get("case_id") != "HDFS-20" or result.get("trial_id") != 0 or
            result.get("plan") != [] or result.get("timed_out") or
            result.get("return_code") != 0 or result.get("trace_error") is not None):
        raise ValueError("healthy trial did not complete fault free")
    junit = result.get("junit_validation", {})
    if (junit.get("status") != "passed" or junit.get("tests") != 1 or
            junit.get("errors") != 0 or junit.get("failures") != 0):
        raise ValueError("selected cluster JUnit did not pass exactly once")
    if sha((trial / "junit-receipt.json").read_bytes()) != result.get("junit_receipt_sha256"):
        raise ValueError("JUnit receipt digest differs from trial result")
    for report in junit.get("reports", []):
        if sha((trial / report["path"]).read_bytes()) != report.get("sha256"):
            raise ValueError("JUnit XML digest differs from receipt")
    feedback = result.get("feedback", {})
    if (feedback.get("status") != "observed" or
            feedback.get("target_reached") is not True or
            feedback.get("target_threw") is not False):
        raise ValueError("healthy exact target was not reached without throwing")
    catalog = result.get("site_catalog_validation", {})
    if (catalog.get("valid") is not True or catalog.get("class_hash_match") is not True or
            catalog.get("observed_target_class_sha256") !=
            config["expected_target_class_sha256"]):
        raise ValueError("loaded target bytecode/site catalog is not the pinned class")
    if sha((trial / "sites.jsonl").read_bytes()) != result.get("site_catalog_sha256"):
        raise ValueError("site catalog digest differs from trial result")
    evidence = result.get("events_evidence", {})
    compressed = (trial / "events.jsonl.gz").read_bytes()
    if sha(compressed) != evidence.get("gzip_sha256"):
        raise ValueError("compressed trace digest differs from trial receipt")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        raw = source.read(128 * 1024 * 1024 + 1)
    if len(raw) > 128 * 1024 * 1024 or sha(raw) != evidence.get("raw_sha256"):
        raise ValueError("raw trace is oversized or differs from trial receipt")
    events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
    proof = evaluate(events, config)
    proof["config_sha256"] = sha(CONFIG.read_bytes())
    proof["trial_result_sha256"] = sha((trial / "result.json").read_bytes())
    proof["events_gzip_sha256"] = sha(compressed)
    return proof


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = validate_output(args.out)
    destination = args.out / "healthy-response-path-gate.json"
    temporary = destination.with_name("." + destination.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)
    print(json.dumps({"status": proof["status"], "gate": str(destination),
                      "diagnostics": proof["diagnostics"]}, sort_keys=True))
    if proof["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
