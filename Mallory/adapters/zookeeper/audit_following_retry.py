#!/usr/bin/env python3
"""Verify that a ZooKeeper FOLLOWING retry handoff is uniquely observed."""

from collections import defaultdict
import re

from Mallory.core.events import event_address
from Mallory.core.graph import OccurrenceGraph


SITE = "zookeeper.peer.following.retry"
TOKEN = re.compile(r"^zk-following-retry:(\d+):(\d+):(\d+):(\d+):(\d+)$")


def verified_retry_edges(events: tuple[dict, ...]) -> list[dict]:
    """Return only exact same-peer/thread/epoch handoffs; reject ambiguous claims."""
    submits: dict[str, list[dict]] = defaultdict(list)
    claims: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event.get("site") != SITE:
            continue
        if event.get("type") == "TASK_SUBMIT":
            submits[str(event.get("correlation"))].append(event)
        elif event.get("type") == "TASK_CLAIM":
            claims[str(event.get("correlation"))].append(event)
    graph = OccurrenceGraph(events)
    edges = []
    for token, consumers in claims.items():
        producers = submits.get(token, [])
        if len(producers) != 1 or len(consumers) != 1:
            raise ValueError("FOLLOWING retry token lacks a unique submit and claim")
        match = TOKEN.fullmatch(token)
        if match is None:
            raise ValueError("malformed FOLLOWING retry token")
        sid, epoch, thread_id, peer_identity, sequence = map(int, match.groups())
        if thread_id <= 0 or peer_identity < 0 or sequence <= 0:
            raise ValueError("FOLLOWING retry token lacks concrete identity")
        submit, claim = producers[0], consumers[0]
        expected_node = f"zk{sid}"
        expected_occurrence = f"{expected_node}:{epoch}:{SITE.removesuffix('.retry')}"
        for event in (submit, claim):
            occurrence = event.get("occurrence")
            if (event.get("node") != expected_node or event.get("epoch") != epoch or
                    not isinstance(occurrence, str) or
                    not occurrence.startswith(expected_occurrence + ":")):
                raise ValueError("FOLLOWING retry actor or lifecycle epoch changed")
        if (not submit.get("thread") or submit["thread"] != claim.get("thread") or
                submit.get("seq", -1) >= claim.get("seq", -1)):
            raise ValueError("FOLLOWING retry is not an ordered same-thread handoff")
        source, target = event_address(submit), event_address(claim)
        matched = [edge for edge in graph.edges if
                   edge.kind == "task" and edge.source == source and edge.target == target and
                   edge.producer_event == submit.get("id") and
                   edge.consumer_event == claim.get("id")]
        if len(matched) != 1:
            raise ValueError("FOLLOWING retry has no unique observed graph edge")
        edges.append({"token": token, "producer_event": submit["id"],
                      "consumer_event": claim["id"], "node": expected_node,
                      "epoch": epoch, "thread": submit["thread"],
                      "thread_id_from_source_token": thread_id,
                      "peer_identity_from_source_token": peer_identity,
                      "source": source, "target": target})
    return edges


def verified_retry_target_paths(events: tuple[dict, ...], check_sites: set[str]) -> list[dict]:
    """Prove a fault's exact FOLLOWING retry reaches a later nested target.

    The task edge is observed by the generic graph. The remaining continuation
    is the exact Java thread's ordered exit, entry, claim, nested region entry,
    and target check. An actor-wide root or another peer's check never qualifies.
    """
    by_id = {event.get("id"): event for event in events}
    exits = [event for event in events if event.get("type") == "REGION_EXIT"
             and event.get("site") == SITE.removesuffix(".retry")]
    enters = [event for event in events if event.get("type") == "REGION_ENTER"
              and event.get("site") == SITE.removesuffix(".retry")]
    target_methods = {site.split("@", 1)[0] for site in check_sites}
    target_enters = [event for event in events if event.get("type") == "REGION_ENTER"
                     and event.get("site") in target_methods]
    checks = [event for event in events if event.get("type") == "TARGET_CHECK"
              and event.get("site") in check_sites]
    faults = [event for event in events if event.get("type") == "FAULT_APPLIED"]
    paths = []
    for edge in verified_retry_edges(events):
        submit = by_id[edge["producer_event"]]
        claim = by_id[edge["consumer_event"]]
        old_occurrence, new_occurrence = submit["occurrence"], claim["occurrence"]
        if old_occurrence == new_occurrence:
            continue
        actor = (edge["node"], edge["epoch"], edge["thread"])
        def same_actor(event):
            return (event.get("node"), event.get("epoch"), event.get("thread")) == actor
        old_exits = [event for event in exits if same_actor(event)
                     and event.get("occurrence") == old_occurrence
                     and submit["seq"] < event["seq"] < claim["seq"]]
        old_enters = [event for event in enters if same_actor(event)
                      and event.get("occurrence") == old_occurrence
                      and event["seq"] < submit["seq"]]
        new_enters = [event for event in enters if same_actor(event)
                      and event.get("occurrence") == new_occurrence
                      and submit["seq"] < event["seq"] < claim["seq"]]
        if len(old_enters) != 1 or len(old_exits) != 1 or len(new_enters) != 1 or not (
                old_exits[0]["seq"] < new_enters[0]["seq"]):
            continue
        for fault in faults:
            if not (same_actor(fault) and fault.get("occurrence") == old_occurrence
                    and old_enters[0]["seq"] < fault["seq"] < submit["seq"]):
                continue
            for target_enter in target_enters:
                if not (same_actor(target_enter)
                        and target_enter.get("parent_id") == new_occurrence
                        and target_enter["seq"] > claim["seq"]):
                    continue
                for check in checks:
                    if (same_actor(check) and
                            check.get("occurrence") == target_enter.get("occurrence") and
                            check["seq"] > target_enter["seq"]):
                        paths.append({
                            "fault_event": fault["id"],
                            "old_enter_event": old_enters[0]["id"],
                            "submit_event": submit["id"],
                            "old_exit_event": old_exits[0]["id"],
                            "new_enter_event": new_enters[0]["id"],
                            "claim_event": claim["id"],
                            "target_enter_event": target_enter["id"],
                            "target_check_event": check["id"],
                            "node": edge["node"], "epoch": edge["epoch"],
                            "thread": edge["thread"], "token": edge["token"],
                            "evidence_type": "observed_task_edge_and_same_thread_retry_continuation",
                        })
    return paths
