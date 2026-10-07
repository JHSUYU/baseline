#!/usr/bin/env python3
"""Validate Solr-05 fault and guard identity directly from per-JVM raw trace."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import re

CASES = ("SOLR-05",)
CONTEXT = ("collection", "shard", "replica", "core")
ACTOR = ("actor", "node", "client_id", "reader_id", *CONTEXT)
RELATIVE_ACTOR = "actor=jetty:host_of_replica"
UPSTREAM_ACTOR = "actor=overseer_writer_for_replica"


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            result.append({"seq": int(parts[0]), "kind": parts[2], "parts": parts[3:]})
    return result


def fields(event: dict) -> dict[str, str]:
    return dict(part.split("=", 1) for part in event["parts"] if "=" in part)


def context_identity(event: dict) -> tuple[str, ...] | None:
    f = fields(event)
    keys = ("node", "client_id", "reader_id", *CONTEXT)
    if any(not f.get(key) or f[key] == "<none>" for key in keys):
        return None
    return tuple(f[key] for key in keys)


def runtime_actor(event: dict) -> tuple[str, ...] | None:
    f = fields(event)
    if not re.fullmatch(r"jetty:node[1-9][0-9]*", f.get("actor", "")):
        return None
    context = context_identity(event)
    if context is None:
        return None
    return (f["actor"], *context)


def target_link(event: dict) -> tuple[str, ...] | None:
    """Join an Overseer write to the intended replica's later register guard."""
    f = fields(event)
    node = f.get("target_node") if event["kind"] in (
        "UPSTREAM_IO_OBSERVED", "IO_MATCHED", "IO_APPLIED_CONNECTION_LOSS") else f.get("node")
    if not node or node == "<none>" or any(
            not f.get(key) or f[key] == "<none>" for key in CONTEXT):
        return None
    return (node, *(f[key] for key in CONTEXT))


def io_identity(event: dict) -> tuple[str, ...] | None:
    p = event["parts"]
    if event["kind"] != "UPSTREAM_IO_OBSERVED" or len(p) < 4 or \
            not p[2].startswith("caller=") or p[0] not in (
                "STATE_SET_DATA_PRE", "STATE_SET_DATA_POST"):
        return None
    f = fields(event)
    if runtime_actor(event) is None or not f.get("writer_id") or not f.get("target_node"):
        return None
    return (p[0], p[1], p[2], UPSTREAM_ACTOR,
            *(key + "=" + f[key] for key in CONTEXT))


def io_behavior_key(event: dict) -> str | None:
    key = io_identity(event)
    if key is None:
        return None
    operation, path, caller, actor, collection, shard, _, _ = key
    path = re.sub(r"(?<=/)qn?r?-\d+", "q*-*", path)
    path = re.sub(r"127\.0\.0\.1:\d+_solr", "<node>", path)
    path = re.sub(r"core_node\d+", "core_node*", path)
    return "|".join((operation, path, caller, actor, collection, shard))


def io_family(event: dict) -> str | None:
    key = io_identity(event)
    if key is None:
        return None
    operation, path, _, actor, collection, shard, _, _ = key
    if path.endswith("/state.json"):
        resource = "collection-state"
    elif "/terms/" in path:
        resource = "collection-terms"
    elif "/leader_elect/" in path or "/leaders/" in path:
        resource = "collection-leadership"
    elif path.startswith("/collections/"):
        resource = "collection-control"
    elif path.startswith("/live_nodes"):
        resource = "live-nodes"
    elif path.startswith("/overseer"):
        resource = "overseer-control"
    else:
        return None
    return "|".join((actor, collection, shard, operation, resource))


def actor_registrations(trace: list[dict]) -> dict[str, dict[str, str]]:
    roles_by_node = {}
    nodes_by_role = {}
    clients = {}
    for event in trace:
        f = fields(event)
        if event["kind"] == "JETTY_ROLE_BOUND":
            role, node = f.get("role"), f.get("node")
            if not role or not node or (node in roles_by_node and roles_by_node[node] != role) or (
                    role in nodes_by_role and nodes_by_role[role] != node):
                raise ValueError("Ambiguous Jetty role mapping")
            roles_by_node[node] = role
            nodes_by_role[role] = node
        elif event["kind"] == "ACTOR_REGISTERED":
            client = f.get("client_id")
            if not client or not f.get("reader_id") or not f.get("node"):
                raise ValueError("Incomplete client registration")
            if client in clients and clients[client] != f:
                raise ValueError("Client identity hash collision or changed registration")
            clients[client] = f
    for client in clients.values():
        client["role"] = roles_by_node.get(client["node"], "<unbound>")
    return clients


def target_counts(trace: list[dict]) -> dict[str, int]:
    return {case: sum(e["kind"] == "TARGET_CHECK" and len(e["parts"]) > 1 and
                      e["parts"][1] == case for e in trace) for case in CASES}


def target_after_any_actor(trace: list[dict], final_fault: int) -> tuple[dict[str, bool], dict[str, bool]]:
    reached = {case: False for case in CASES}
    exception = {case: False for case in CASES}
    for event in trace:
        if event["seq"] <= final_fault:
            continue
        p = event["parts"]
        if event["kind"] == "TARGET_CHECK" and len(p) > 1 and p[1] in reached:
            reached[p[1]] = True
        elif event["kind"] == "TARGET_EXCEPTION" and p and p[0] in exception:
            exception[p[0]] = True
    return reached, exception


def target_after(trace: list[dict], final_fault: int) -> tuple[dict[str, bool], dict[str, bool]]:
    """Join an exact Overseer write to its intended replica and host guard."""
    reached = {case: False for case in CASES}
    exception = {case: False for case in CASES}
    applied = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS" and
               e["seq"] <= final_fault]
    actors = {target_link(event) for event in applied}
    actors.discard(None)
    last_fault = "F" + str(len(applied) - 1)
    for event in trace:
        if event["seq"] <= final_fault or target_link(event) not in actors or \
                fields(event).get("last_fault") != last_fault:
            continue
        p = event["parts"]
        if event["kind"] == "TARGET_CHECK" and len(p) > 1 and p[1] in reached:
            reached[p[1]] = True
        elif event["kind"] == "TARGET_EXCEPTION" and p and p[0] in exception:
            exception[p[0]] = True
    return reached, exception


def checked_target_identity(trace: list[dict]) -> bool:
    """Independently reconstruct each thread's register context and reader binding."""
    try:
        registered = actor_registrations(trace)
    except ValueError:
        return False
    active = defaultdict(list)
    semantic_hosts = {}
    for event in trace:
        kind = event["kind"]
        if kind not in ("REGISTER_ENTER", "REGISTER_EXIT", "IO_OBSERVED",
                        "IO_MATCHED", "IO_APPLIED_CONNECTION_LOSS",
                        "TARGET_CHECK", "TARGET_EXCEPTION"):
            continue
        if kind in ("IO_MATCHED", "IO_APPLIED_CONNECTION_LOSS") and \
                event["parts"][0].startswith("STATE_SET_DATA_"):
            continue
        f = fields(event)
        thread = f.get("thread")
        if not thread:
            return False
        identity = context_identity(event)
        if kind == "REGISTER_ENTER":
            if identity is None:
                return False
            client = registered.get(f.get("client_id"))
            if client is None or client["node"] != f.get("node") or \
                    client["reader_id"] != f.get("reader_id"):
                return False
            semantic = tuple(f.get(key) for key in CONTEXT)
            host = tuple(f.get(key) for key in ("node", "client_id", "reader_id"))
            if semantic in semantic_hosts and semantic_hosts[semantic] != host:
                return False
            semantic_hosts[semantic] = host
            active[thread].append(identity)
        elif kind == "REGISTER_EXIT":
            if identity is None or not active[thread] or active[thread].pop() != identity:
                return False
        elif kind in ("TARGET_CHECK", "TARGET_EXCEPTION") or runtime_actor(event) is not None:
            actor = runtime_actor(event)
            client = registered.get(f.get("client_id"))
            if actor is None or client is None or client["node"] != f.get("node") or \
                    client["reader_id"] != f.get("reader_id") or \
                    f.get("actor") != "jetty:" + client["role"] or \
                    not active[thread] or active[thread][-1] != identity:
                return False
    return True


def strict_sequence(plan: list[str], trace: list[dict]) -> bool:
    matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
    applied = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
    if len(matched) != len(plan) or len(applied) != len(plan):
        return False
    try:
        registered = actor_registrations(trace)
    except ValueError:
        return False
    for index, selector in enumerate(plan):
        spec = selector.split("|")
        if len(spec) not in (9, 11):
            return False
        match, fault = matched[index], applied[index]
        if match["seq"] + 1 != fault["seq"] or match["parts"] != fault["parts"]:
            return False
        p, f = fault["parts"], fields(fault)
        if len(p) < 4 or p[:2] != spec[:2] or p[2] != "ordinal=" + spec[2]:
            return False
        if (spec[4] != UPSTREAM_ACTOR or
                ["caller=" + f.get("caller", ""), UPSTREAM_ACTOR,
                 *(key + "=" + f.get(key, "") for key in CONTEXT)] != spec[3:9]):
            return False
        if f.get("fault_id") != f"F{index}" or f.get("plan_index") != str(index):
            return False
        previous = f"F{index-1}" if index else "<none>"
        if f.get("previous_fault_id") != previous:
            return False
        client = registered.get(f.get("client_id"))
        if client is None or client["node"] != f.get("node") or \
                client["reader_id"] != f.get("reader_id") or \
                f.get("actor") != "jetty:" + client["role"] or runtime_actor(fault) is None or \
                not f.get("writer_id") or target_link(fault) is None:
            return False
        target = [e for e in trace if e["kind"] == "JETTY_ROLE_BOUND" and
                  fields(e).get("node") == f.get("target_node")]
        if len(target) != 1 or f.get("target_actor") != "jetty:" + fields(target[0])["role"]:
            return False
        semantic = tuple(f.get(key) for key in CONTEXT)
        pending = [e for e in trace if e["kind"] == "UPSTREAM_UPDATE_PENDING" and
                   e["seq"] < fault["seq"] and
                   tuple(fields(e).get(key) for key in CONTEXT) == semantic]
        if not pending or {fields(e).get("writer_id") for e in pending} != {f["writer_id"]} or \
                any(fields(e).get("target_node") != f.get("target_node") for e in pending):
            return False
        observed_event = next((e for e in trace if e["seq"] == match["seq"] - 1), None)
        if observed_event is None or io_identity(observed_event) is None or \
                target_link(observed_event) != target_link(fault):
            return False
        identity = (spec[0], spec[1], *spec[3:9])
        observed = [e for e in trace if e["seq"] < match["seq"] and io_identity(e) == identity]
        if int(f.get("global_hit_ordinal", -1)) != len(observed):
            return False
        if len(spec) == 11:
            if not spec[2].startswith("@") or spec[9] != "after=" + previous or \
                    spec[10] != "seed_global=" + f.get("seed_global", ""):
                return False
            relative = sum(e["seq"] > applied[index-1]["seq"] for e in observed)
            if int(f.get("relative_count", -1)) != relative:
                return False
        elif spec[2].startswith("@"):
            return False
    return True
