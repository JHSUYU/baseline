"""Occurrence graph with only uniquely matched runtime edges."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .events import event_address, event_seq


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str
    evidence: str
    producer_event: str
    consumer_event: str
    certainty: str = "observed"


class OccurrenceGraph:
    def __init__(self, events: tuple[dict[str, Any], ...]):
        self.events = events
        self.occurrences: set[str] = set()
        self.edges: set[Edge] = set()
        self.candidate_edges: set[Edge] = set()
        self.gaps: dict[str, int] = defaultdict(int)
        self._build()

    def _build(self) -> None:
        ids: dict[str, dict[str, Any]] = {}
        duplicate_ids: set[str] = set()
        region_by_occurrence: dict[str, list[dict[str, Any]]] = defaultdict(list)
        handoff_by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in self.events:
            address = event_address(event)
            if address:
                self.occurrences.add(address)
            if event.get("type") == "REGION_ENTER" and isinstance(event.get("occurrence"), str):
                region_by_occurrence[event["occurrence"]].append(event)
            if event.get("type") in {"TASK_CLAIM", "RECV"} and event.get("correlation"):
                handoff_by_token[str(event["correlation"])].append(event)
            event_id = event.get("id")
            if isinstance(event_id, str) and event_id:
                if event_id in ids or event_id in duplicate_ids:
                    self.gaps["duplicate_event_id"] += 1
                    ids.pop(event_id, None)
                    duplicate_ids.add(event_id)
                else:
                    ids[event_id] = event

        # Explicit parent identity is stronger than temporal order. parent_id
        # must resolve to a unique event in this trace.
        for event in self.events:
            if (event.get("type") != "REGION_ENTER" or
                    not event.get("parent_id") or event.get("parent_id") == "root"):
                continue
            def same_actor_before(candidate: dict[str, Any]) -> bool:
                return (candidate.get("node") == event.get("node") and
                        candidate.get("epoch") == event.get("epoch") and
                        event_seq(candidate) < event_seq(event))

            parent = ids.get(str(event["parent_id"]))
            if parent is not None and not same_actor_before(parent):
                parent = None
            if parent is None:
                matches = region_by_occurrence.get(str(event["parent_id"]), [])
                matches = [candidate for candidate in matches if same_actor_before(candidate)]
                parent = matches[0] if len(matches) == 1 else None
            if parent is None:
                matches = handoff_by_token.get(str(event["parent_id"]), [])
                # The same RPC token can name both request and response. A
                # region may only inherit from a handoff into *its own* actor
                # before it starts, never a later reply on another node.
                matches = [candidate for candidate in matches if same_actor_before(candidate)]
                if len(matches) > 1:
                    requests = [candidate for candidate in matches
                                if candidate.get("type") == "RECV" and
                                "request" in str(candidate.get("port", "")).lower()]
                    matches = requests if len(requests) == 1 else matches
                parent = matches[0] if len(matches) == 1 else None
            if parent is None:
                self.gaps["unmatched_parent"] += 1
            else:
                self._add(parent, event, "region_parent", "unique_parent_id_or_handoff_token")

        self._pair("SEND", "RECV", "rpc", ("transport", "correlation", "port"),
                   ("attempt", "half"), exclusive_consumers=True)
        self._pair("TASK_SUBMIT", "TASK_CLAIM", "task", ("correlation",),
                   ("attempt",), exclusive_consumers=True)
        self._pair("STATE_WRITE", "STATE_READ", "state", ("object", "key", "version"))

    def _add(self, producer: dict[str, Any], consumer: dict[str, Any], kind: str,
             evidence: str, *, certainty: str = "observed") -> None:
        source, target = event_address(producer), event_address(consumer)
        if source is None or target is None:
            self.gaps[f"{kind}_missing_occurrence"] += 1
            return
        if source == target:
            return
        producer_id, consumer_id = producer.get("id"), consumer.get("id")
        if not isinstance(producer_id, str) or not isinstance(consumer_id, str):
            self.gaps[f"{kind}_missing_event_id"] += 1
            return
        edge = Edge(source, target, kind, evidence, producer_id, consumer_id, certainty)
        (self.edges if certainty == "observed" else self.candidate_edges).add(edge)

    def _pair(self, producer_type: str, consumer_type: str, kind: str,
              fields: tuple[str, ...], optional: tuple[str, ...] = (),
              exclusive_consumers: bool = False) -> None:
        producers: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        consumers: list[dict[str, Any]] = []
        consumers_by_key: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for event in self.events:
            if event.get("type") == producer_type:
                key = self._key(event, fields)
                if key is None:
                    self.gaps[f"{kind}_producer_missing_identity"] += 1
                else:
                    producers[key].append(event)
            elif event.get("type") == consumer_type:
                consumers.append(event)
                key = self._key(event, fields)
                if key is not None:
                    consumers_by_key[key].append(event)

        # Index the full identity once. A claim/receive used to rescan every
        # other consumer to prove exclusivity, making busy cluster traces
        # quadratic. The fallback preserves Python equality for unusual
        # unhashable optional values in a trace.
        producer_groups: dict[tuple[tuple[str, ...], tuple[Any, ...]],
                              list[dict[str, Any]]] = defaultdict(list)
        consumer_groups: dict[tuple[tuple[str, ...], tuple[Any, ...]],
                              list[dict[str, Any]]] = defaultdict(list)
        fallback_keys: set[tuple[str, ...]] = set()
        for required_key, rows in producers.items():
            for row in rows:
                identity = (required_key, tuple(row.get(field) for field in optional))
                try:
                    producer_groups[identity].append(row)
                except TypeError:
                    fallback_keys.add(required_key)
        for required_key, rows in consumers_by_key.items():
            for row in rows:
                identity = (required_key, tuple(row.get(field) for field in optional))
                try:
                    consumer_groups[identity].append(row)
                except TypeError:
                    fallback_keys.add(required_key)
        for event in consumers:
            key = self._key(event, fields)
            if key is None:
                self.gaps[f"{kind}_consumer_missing_identity"] += 1
                continue
            if key in fallback_keys:
                matches = [producer for producer in producers.get(key, [])
                           if all(producer.get(field) == event.get(field)
                                  for field in optional)]
                peers = [other for other in consumers_by_key[key]
                         if all(other.get(field) == event.get(field)
                                for field in optional)] if exclusive_consumers else []
            else:
                identity = (key, tuple(event.get(field) for field in optional))
                matches = producer_groups.get(identity, [])
                peers = consumer_groups.get(identity, []) if exclusive_consumers else []
            if exclusive_consumers:
                if len(peers) != 1:
                    self.gaps[f"{kind}_ambiguous_consumer"] += 1
                    continue
            if len(matches) != 1:
                self.gaps[f"{kind}_{'unmatched' if not matches else 'ambiguous'}"] += 1
                continue
            observed_optional = tuple(field for field in optional if event.get(field) is not None)
            certainty = ("candidate" if kind == "state" and
                         (event.get("version_confidence") != "exact" or
                          matches[0].get("version_confidence") != "exact") else "observed")
            self._add(matches[0], event, kind,
                      ("sampled_version:" if certainty == "candidate" else "unique:") +
                      ",".join(fields + observed_optional), certainty=certainty)

    @staticmethod
    def _key(event: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...] | None:
        values = [event.get(field) for field in fields]
        # For state, object/key/version are all mandatory. For messaging the
        # runtime must supply every configured correlation dimension, even if
        # it uses an explicit sentinel for a one-way transport.
        if any(value is None or value == "" for value in values):
            return None
        return tuple(str(value) for value in values)

    def backward_closure(self, anchor: str, *, include_candidates: bool = True) -> set[str]:
        if anchor not in self.occurrences:
            return set()
        parents: dict[str, set[str]] = defaultdict(set)
        for edge in self.edges | (self.candidate_edges if include_candidates else set()):
            parents[edge.target].add(edge.source)
        closure = {anchor}
        pending = [anchor]
        while pending:
            for parent in parents[pending.pop()]:
                if parent not in closure:
                    closure.add(parent)
                    pending.append(parent)
        return closure

    def summary(self) -> dict[str, Any]:
        return {"occurrences": len(self.occurrences), "edges": len(self.edges),
                "candidate_edges": len(self.candidate_edges),
                "edges_by_kind": {kind: sum(e.kind == kind for e in self.edges)
                                  for kind in sorted({e.kind for e in self.edges})},
                "candidate_edges_by_kind": {kind: sum(e.kind == kind for e in self.candidate_edges)
                                            for kind in sorted({e.kind for e in self.candidate_edges})},
                "gaps": dict(sorted(self.gaps.items()))}
