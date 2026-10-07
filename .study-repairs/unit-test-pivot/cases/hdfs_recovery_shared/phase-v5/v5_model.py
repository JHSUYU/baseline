#!/usr/bin/env python3
"""Pure identity, budget, and queue rules for the recovery-owner V5 campaign."""

from __future__ import annotations

from collections import Counter
import hashlib
import json

CASES = ("HDFS-28", "HDFS-29", "HDFS-30")
SITES = {
    "HDFS-28": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>#u12",
    "HDFS-29": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u12",
    "HDFS-30": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u23",
}
PARENT_KEYS = ("marker", "siteId", "sourceKey", "originSourceKey",
               "occurrenceAddress", "hitOrdinal", "requestApi", "faultType")
MATCH_KEYS = ("marker", "siteId", "sourceKey", "occurrenceAddress",
              "hitOrdinal", "requestApi", "faultType")
PRODUCER = "FAULT:HDFS_RPC:RECOVERY_COMMAND"


def root(event: dict) -> str:
    return event.get("occurrenceAddress", "").split("/rpc:", 1)[0].split("/server:", 1)[0]


def origin(event: dict) -> str:
    return event.get("originSourceKey", event.get("sourceKey", ""))


def owner(event: dict) -> tuple:
    """A command token keeps a dropped command apart from its later retry."""
    return (event.get("clusterEpisode"), origin(event), event.get("bpid"),
            event.get("blockId"), event.get("recoveryId"), root(event),
            event.get("commandToken"))


def valid_owner(event: dict) -> bool:
    episode, source, bpid, block, recovery, address, command = owner(event)
    return (isinstance(episode, int) and episode > 0
            and source not in ("", "unregistered", "unknown-origin")
            and bool(bpid) and isinstance(block, int) and block >= 0
            and isinstance(recovery, int) and recovery >= 0 and bool(address)
            and isinstance(command, str) and (command.startswith("command:")
                                               or command.startswith("direct:")))


def same_owner(a: dict, b: dict) -> bool:
    return valid_owner(a) and valid_owner(b) and owner(a) == owner(b)


def legacy_parent_key(point: dict) -> tuple:
    # V4 added filePhase after some strict parents had already been saved.
    return tuple(point.get(field, "") for field in PARENT_KEYS)


def observed(event: dict, selected: dict) -> bool:
    if event.get("event") != "FAULT_POINT_OBSERVED":
        return False
    for field in PARENT_KEYS[:-1]:
        value = origin(event) if field == "originSourceKey" else event.get(field, "")
        if value != selected.get(field, ""):
            return False
    phase = selected.get("filePhase", "")
    return not (phase and event.get("filePhase") and event["filePhase"] != phase)


def legacy_same_owner(a: dict, b: dict) -> bool:
    # V4 has no BP/episode on I/O; the parent raw trace supplies the root.
    return (origin(a) == b.get("sourceKey")
            and a.get("blockId") == b.get("blockId") and root(a) == b.get("occurrenceAddress")
            and origin(a) not in ("", "unregistered", "unknown-origin"))


def sequence_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()[:20]


def selector(event: dict, kind: str) -> dict:
    result = {key: event[key] for key in ("marker", "siteId", "sourceKey",
                                          "occurrenceAddress", "hitOrdinal")}
    result.update(originSourceKey=origin(event), requestApi=event.get("requestApi", ""),
                  filePhase=event.get("filePhase", ""), faultType=kind,
                  clusterEpisode=event["clusterEpisode"])
    return result


def event_matches(event: dict, selected: dict, index: int, expected_episode: int) -> bool:
    return (event.get("planIndex") == index
            and origin(event) == selected.get("originSourceKey", selected["sourceKey"])
            and event.get("filePhase", "") == selected.get("filePhase", "")
            and event.get("clusterEpisode") == selected.get("clusterEpisode", expected_episode)
            and all(event.get(key) == selected.get(key) for key in MATCH_KEYS))


def registered(trace: list[dict], event: dict) -> bool:
    return any(row.get("event") == "DN_REGISTER"
               and row.get("sourceKey") == event.get("sourceKey")
               and row.get("clusterEpisode") == event.get("clusterEpisode")
               and row.get("seq", -1) < event.get("seq", -1) for row in trace)


def identity_verified(trace: list[dict], event: dict) -> bool:
    if not valid_owner(event) or not registered(trace, event):
        return False
    if event.get("marker") == PRODUCER:
        # The receive hook executes before RECOVERY_BEGIN. Its raw command
        # carries BP, block, recovery ID and registered coordinator identity.
        return True
    preceding = any(row.get("event") == "RECOVERY_BEGIN"
                    and row.get("seq", -1) < event.get("seq", -1)
                    and same_owner(row, event) for row in trace)
    if not preceding:
        return False
    if not event.get("marker", "").startswith("FAULT:HDFS_FILE:"):
        return True
    phase = event.get("filePhase")
    if phase not in ("initReplicaRecovery", "updateReplicaUnderRecovery"):
        return False
    if phase == "updateReplicaUnderRecovery" and event.get("sourceKey") != origin(event):
        return False
    return any(row.get("event") == "SERVER_RECOVERY_BEGIN"
               and row.get("seq", -1) < event.get("seq", -1)
               and row.get("sourceKey") == event.get("sourceKey")
               and row.get("originSourceKey") == origin(event)
               and all(row.get(key) == event.get(key) for key in
                       ("clusterEpisode", "bpid", "blockId", "recoveryId",
                        "commandToken"))
               for row in trace)


def later_target(trace: list[dict], event: dict, case: str) -> list[dict]:
    return [row for row in trace if row.get("event") == "TARGET_CHECK"
            and row.get("caseId") == case and row.get("siteId") == SITES[case]
            and row.get("seq", -1) > event.get("seq", -1) and same_owner(event, row)]


def eligible_io(trace: list[dict], event: dict, cases: tuple[str, ...]) -> list[str]:
    if event.get("event") != "FAULT_POINT_OBSERVED" or not event.get("marker", "").startswith("FAULT:"):
        return []
    if not identity_verified(trace, event):
        return []
    return [case for case in cases if later_target(trace, event, case)]


def active_cases(state: dict) -> tuple[str, ...]:
    return tuple(case for case in CASES if state["cases"][case]["status"] == "active")


def select_index(state: dict) -> int:
    """Three of four turns favor parent-proven second faults; one explores."""
    active = set(active_cases(state))
    eligible = [(i, item) for i, item in enumerate(state["queue"])
                if len(item["sequence"]) <= max(state["cases"][case]["max_faults"] for case in active)
                and (item.get("lane") != "hdfs28_producer" or "HDFS-28" in active)
                and item["id"] not in state["strict_ids"]]
    if not eligible:
        raise RuntimeError("no eligible queued sequence")
    if state["v5_attempts"] % 4 != 3:
        second = [(i, item) for i, item in eligible
                  if len(item["sequence"]) >= 2
                  and active.intersection(item.get("pre_target_cases", []))]
        if second:
            eligible = second
    counts = Counter(item["sequence"][-1]["faultType"]
                     for item in state["completed_v5"])
    return min(eligible, key=lambda pair: (
        0 if pair[1].get("lane") == "hdfs28_producer" and "HDFS-28" in active else 1,
        counts[pair[1]["sequence"][-1]["faultType"]],
        -pair[1].get("priority", 0), pair[1].get("created", 0), pair[1]["id"]))[0]


def update_case_budget(case_state: dict, recent_effective: list[dict], case: str) -> None:
    if case_state["status"] != "active":
        return
    novelty = any(t["coverage_gain"][case]["branch_counts"] > 0
                  or bool(t["new_io_families"][case]) for t in recent_effective[-8:])
    if case_state["effective"] >= case_state["effective_goal"]:
        if case_state["effective_goal"] == 80 and len(recent_effective) >= 8 and novelty:
            case_state.update(effective_goal=128, max_faults=10,
                              attempt_cap=512, extension_reason="last_8_effective_novelty")
        else:
            case_state["status"] = "quality_budget_met_pending_audit"
    elif case_state["attempts"] >= case_state["attempt_cap"]:
        case_state["status"] = "budget_recheck_pending"
