#!/usr/bin/env python3
"""Read and validate the actor V2 trace contract without trusting summary fields."""

from collections import Counter
import json
from pathlib import Path
import re


CASES = ("SOLR-10", "SOLR-39", "SOLR-40")


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


def io_identity(event: dict) -> tuple[str, str, str, str] | None:
    p = event["parts"]
    if event["kind"] != "IO_OBSERVED" or len(p) < 4:
        return None
    if not p[2].startswith("caller=") or not p[3].startswith("actor="):
        return None
    return p[0], p[1], p[2], p[3]


def io_behavior_key(event: dict) -> str | None:
    identity = io_identity(event)
    if identity is None:
        return None
    operation, path, caller, actor = identity
    path = re.sub(r"(?<=/)qn?r?-\d+", "q*-*", path)
    path = re.sub(r"127\.0\.0\.1:\d+_solr", "<node>", path)
    path = re.sub(r"(?<=/election/)[^/]+", "<election>", path)
    path = re.sub(r"core_node\d+", "core_node*", path)
    return "|".join((caller, actor, operation, path))


def io_family(event: dict) -> str | None:
    """Stable actor/operation/resource family, excluding ephemeral names and ordinals."""
    identity = io_identity(event)
    if identity is None:
        return None
    operation, path, _, actor = identity
    if not (actor.startswith("actor=jetty:node") or actor == "actor=alias-writer"):
        return None
    if path == "/aliases.json":
        resource = "aliases"
    elif path.startswith("/collections/myalias") and path.endswith("/state.json"):
        resource = "alias-collection-state"
    elif path.startswith("/collections/myalias") and path.endswith("/collectionprops.json"):
        resource = "alias-collection-props"
    elif path.startswith("/collections/myalias"):
        resource = "alias-collection-control"
    elif path.startswith("/overseer"):
        resource = "overseer-control"
    elif path == "/live_nodes":
        resource = "live-nodes"
    else:
        return None
    return "|".join((actor, operation, resource))


def actor_registrations(trace: list[dict]) -> dict[str, dict[str, str]]:
    roles = {}
    clients = {}
    for event in trace:
        f = fields(event)
        if event["kind"] == "JETTY_ROLE_BOUND":
            roles[f["node"]] = f["role"]
        elif event["kind"] == "ACTOR_REGISTERED":
            clients[f["client_id"]] = f
    for client in clients.values():
        client["role"] = roles.get(client["node"], "<unbound>")
    return clients


def target_counts(trace: list[dict]) -> dict[str, int]:
    return {case: sum(e["kind"] == "TARGET_CHECK" and len(e["parts"]) > 1 and
                      e["parts"][1] == case for e in trace) for case in CASES}


def runtime_actor(event: dict) -> tuple[str, str, str, str] | None:
    """The live receiver/manager pair, not just a reusable Jetty slot label."""
    f = fields(event)
    keys = ("actor", "node", "client_id", "manager_id")
    if not all(f.get(key) for key in keys):
        return None
    return tuple(f[key] for key in keys)


def actor_relation(io_event: dict, target_event: dict) -> str | None:
    """Join a guard to its real I/O actor or an alias write of that exact key.

    The cross-node case is source-backed: AliasesManager writes the `collection`
    map to /aliases.json, and each node's AliasesManager reads/watches that same
    znode. It is a relevant shared-state relation, not a claim that a write
    completed or that a particular watch callback fired after this fault.
    """
    source, destination = runtime_actor(io_event), runtime_actor(target_event)
    if source is None or destination is None:
        return None
    if source[1:] == destination[1:]:
        return "same_live_client_manager"
    parts = io_event["parts"]
    alias_index = 1 if target_event["kind"] == "TARGET_EXCEPTION" else 2
    if (len(parts) >= 2 and parts[:2] == ["SET_DATA", "/aliases.json"] and
            len(target_event["parts"]) > alias_index and
            target_event["parts"][alias_index] in fields(io_event).get("payload_aliases", "").split(",") and
            source[0] == "alias-writer" and destination[0].startswith("jetty:node")):
        return "alias_payload_shared_znode"
    return None


def target_after_any_actor(trace: list[dict], final_fault: int) -> tuple[dict[str, bool], dict[str, bool]]:
    """Diagnostic only: a guard may run on a different client after the fault."""
    reached = {case: False for case in CASES}
    exception = {case: False for case in CASES}
    for event in trace:
        if event["seq"] <= final_fault:
            continue
        p = event["parts"]
        if event["kind"] == "TARGET_CHECK" and len(p) >= 2 and p[1] in reached:
            reached[p[1]] = True
        if event["kind"] == "TARGET_EXCEPTION" and p and p[0] in exception:
            exception[p[0]] = True
    return reached, exception


def target_after(trace: list[dict], final_fault: int) -> tuple[dict[str, bool], dict[str, bool]]:
    """Count a guard only with a verified case-specific runtime I/O relation."""
    reached = {case: False for case in CASES}
    exception = {case: False for case in CASES}
    faults = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS" and
              e["seq"] <= final_fault]
    for event in trace:
        if event["seq"] <= final_fault:
            continue
        if not any(actor_relation(fault, event) for fault in faults):
            continue
        p = event["parts"]
        if event["kind"] == "TARGET_CHECK" and len(p) >= 2 and p[1] in reached:
            reached[p[1]] = True
        if event["kind"] == "TARGET_EXCEPTION" and p and p[0] in exception:
            exception[p[0]] = True
    return reached, exception


def target_relations(trace: list[dict], final_fault: int) -> dict[str, list[str]]:
    """Keep the specific actor join supporting each effective case receipt."""
    result = {case: set() for case in CASES}
    faults = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS" and
              e["seq"] <= final_fault]
    for event in trace:
        if (event["seq"] <= final_fault or event["kind"] != "TARGET_CHECK" or
                len(event["parts"]) < 2 or event["parts"][1] not in result):
            continue
        for fault in faults:
            relation = actor_relation(fault, event)
            if relation:
                result[event["parts"][1]].add(relation)
    return {case: sorted(value) for case, value in result.items()}


def strict_sequence(plan: list[str], trace: list[dict]) -> bool:
    matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
    applied = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
    if len(matched) != len(plan) or len(applied) != len(plan):
        return False
    registrations = actor_registrations(trace)
    for index, selector in enumerate(plan):
        spec = selector.split("|")
        if len(spec) not in (5, 7):
            return False
        match, fault = matched[index], applied[index]
        if match["seq"] + 1 != fault["seq"] or match["parts"] != fault["parts"]:
            return False
        p, f = fault["parts"], fields(fault)
        if len(p) < 4 or p[:2] != spec[:2] or p[2] != "ordinal=" + spec[2]:
            return False
        if f.get("caller") != spec[3].split("=", 1)[1] or f.get("actor") != spec[4].split("=", 1)[1]:
            return False
        if f.get("fault_id") != f"F{index}" or f.get("plan_index") != str(index):
            return False
        previous = f"F{index-1}" if index else "<none>"
        if f.get("previous_fault_id") != previous:
            return False
        client = registrations.get(f.get("client_id"))
        if (client is None or client["node"] != f.get("node") or
                f.get("manager_id") != client["manager_id"] or
                f.get("physical_actor") != "jetty:" + client["role"] or
                (f.get("actor") == "alias-writer" and p[:2] != ["SET_DATA", "/aliases.json"]) or
                (f.get("actor") != "alias-writer" and
                 f.get("actor") != "jetty:" + client["role"])):
            return False
        identity = (p[0], p[1], spec[3], spec[4])
        observed = [e for e in trace if e["seq"] < match["seq"] and io_identity(e) == identity]
        if int(f.get("global_hit_ordinal", -1)) != len(observed):
            return False
        if len(spec) == 7:
            if (not spec[2].startswith("@") or spec[5] != "after=" + previous or
                    spec[6] != "seed_global=" + f.get("seed_global", "")):
                return False
            relative = sum(e["seq"] > applied[index-1]["seq"] for e in observed)
            if int(f.get("relative_count", -1)) != relative:
                return False
        elif spec[2].startswith("@"):
            return False
    return True


def checked_target_identity(trace: list[dict]) -> bool:
    registrations = actor_registrations(trace)
    for event in trace:
        if event["kind"] != "TARGET_CHECK":
            continue
        f = fields(event)
        client = registrations.get(f.get("client_id"))
        if (client is None or client["manager_id"] != f.get("manager_id") or
                client["node"] != f.get("node") or f.get("actor") != "jetty:" + client["role"]):
            return False
    return True
