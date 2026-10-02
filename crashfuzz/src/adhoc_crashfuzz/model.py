"""Versioned event, target, and fault-sequence contracts.

The graph builder does not know about HDFS, HBase, Solr, or ZooKeeper. A
transport adapter only has to publish matching MESSAGE_SEND/RECV events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Optional, Tuple


EVENT_KINDS = frozenset({
    "METHOD_ENTER", "METHOD_EXIT", "FIELD_READ", "FIELD_WRITE",
    "MESSAGE_SEND", "MESSAGE_RECV", "ASYNC_SEND", "ASYNC_RECV",
    "BRANCH", "BLOCK", "GLOBAL_BRANCH", "GLOBAL_BLOCK",
    "TARGET", "THROW", "FAULT_POINT", "BOOT",
})
FAULT_KINDS = frozenset({"CRASH", "REBOOT"})


@dataclass(frozen=True)
class PointKey:
    """A replayable boundary, excluding timestamps and process IDs."""

    node: str
    site: str
    context: str
    ordinal: int
    phase: str = "BEFORE"

    def __post_init__(self) -> None:
        if not self.node or not self.site or self.ordinal < 1:
            raise ValueError("fault point requires node, site, ordinal >= 1")
        if self.phase not in ("BEFORE", "AFTER"):
            raise ValueError("fault point phase must be BEFORE or AFTER")

    def to_dict(self) -> dict:
        return {"node": self.node, "site": self.site,
                "context": self.context, "ordinal": self.ordinal,
                "phase": self.phase}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "PointKey":
        return cls(str(row["node"]), str(row["site"]),
                   str(row.get("context", "")), int(row["ordinal"]),
                   str(row.get("phase", "BEFORE")))


@dataclass(frozen=True)
class Event:
    """One event from one JVM. seq is ordered only within a process instance."""

    kind: str
    node: str
    process: str
    seq: int
    thread: str = ""
    span: str = ""
    parent: str = ""
    site: str = ""
    context: str = ""
    ordinal: int = 0
    phase: str = "BEFORE"
    location: str = ""
    state_version: str = ""
    observed_version: str = ""
    correlation: str = ""
    outcome: str = ""
    fatal: bool = False
    wall_ms: int = 0
    epoch: Optional[int] = None
    source: str = ""

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError("unknown event kind: " + self.kind)
        if not self.node or not self.process or self.seq < 0:
            raise ValueError("event requires node, process, and seq >= 0")
        if self.epoch is not None and self.epoch < 0:
            raise ValueError("epoch must be nonnegative")

    @classmethod
    def from_dict(cls, row: Mapping[str, Any], source: str = "") -> "Event":
        version = int(row.get("schema", 1))
        if version != 1:
            raise ValueError("unsupported event schema: " + str(version))
        epoch = row.get("epoch")
        return cls(
            kind=str(row["kind"]), node=str(row["node"]),
            process=str(row["process"]), seq=int(row["seq"]),
            thread=str(row.get("thread", "")),
            span=str(row.get("span", "")),
            parent=str(row.get("parent", "")),
            site=str(row.get("site", "")),
            context=str(row.get("context", "")),
            ordinal=int(row.get("ordinal", 0)),
            phase=str(row.get("phase", "BEFORE")),
            location=str(row.get("location", "")),
            state_version=str(row.get("state_version", "")),
            observed_version=str(row.get("observed_version", "")),
            correlation=str(row.get("correlation", "")),
            outcome=str(row.get("outcome", "")),
            fatal=row.get("fatal", False) is True,
            wall_ms=int(row.get("wall_ms", 0)),
            epoch=None if epoch is None else int(epoch), source=source,
        )

    def point_key(self) -> PointKey:
        if self.kind != "FAULT_POINT":
            raise ValueError("only FAULT_POINT has a replay key")
        return PointKey(self.node, self.site, self.context,
                        self.ordinal, self.phase)


@dataclass(frozen=True)
class TargetSpec:
    site: str
    node: str = ""
    context_prefix: str = ""
    context: str = ""
    epoch: Optional[int] = None

    def matches(self, event: Event) -> bool:
        return (event.kind == "TARGET" and event.site == self.site
                and (not self.node or event.node == self.node)
                and event.context.startswith(self.context_prefix)
                and (not self.context or event.context == self.context))


@dataclass(frozen=True)
class FaultAction:
    kind: str
    trigger: PointKey
    target_node: str
    site_occurrence: int = 0
    trigger_epoch: int = 0

    def __post_init__(self) -> None:
        if (self.kind not in FAULT_KINDS or not self.target_node
                or self.site_occurrence < 0 or self.trigger_epoch < 0):
            raise ValueError("invalid fault action")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "trigger": self.trigger.to_dict(),
                "target_node": self.target_node,
                "site_occurrence": self.site_occurrence,
                "trigger_epoch": self.trigger_epoch}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "FaultAction":
        return cls(str(row["kind"]), PointKey.from_dict(row["trigger"]),
                   str(row["target_node"]),
                   int(row.get("site_occurrence", 0)),
                   int(row.get("trigger_epoch", 0)))


@dataclass(frozen=True)
class FaultSequence:
    actions: Tuple[FaultAction, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"actions": [action.to_dict() for action in self.actions]}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "FaultSequence":
        return cls(tuple(FaultAction.from_dict(a)
                         for a in row.get("actions", [])))

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:20]

    def append(self, action: FaultAction) -> "FaultSequence":
        return FaultSequence(self.actions + (action,))
