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


@dataclass
class EventTimeReachability:
    """Backward proof windows for one exact target event.

    A window is bounded by the next event on the same occurrence and JVM
    thread. Crossing a graph edge consumes its exact producer/consumer IDs;
    an occurrence alone never joins two unrelated events.
    """

    target: dict[str, Any]
    cutoffs: dict[tuple[str, int, bool], int]
    paths: dict[tuple[str, int, bool], tuple[Edge, ...]]

    def witness(self, event: dict[str, Any], *, require_edge: bool = False
                ) -> tuple[Edge, ...] | None:
        address, seq, thread = event_address(event), event_seq(event), event.get("thread_id")
        if (address is None or seq < 0 or seq >= event_seq(self.target) or
                not isinstance(thread, int) or isinstance(thread, bool)):
            return None
        for crossed in ((True,) if require_edge else (False, True)):
            key = (address, thread, crossed)
            if seq <= self.cutoffs.get(key, -1):
                return self.paths[key]
        return None


class OccurrenceGraph:
    def __init__(self, events: tuple[dict[str, Any], ...], *,
                 reject_coarse_roots: bool = False):
        self.events = events
        self.reject_coarse_roots = reject_coarse_roots
        self.occurrences: set[str] = set()
        self.edges: set[Edge] = set()
        self.candidate_edges: set[Edge] = set()
        self.gaps: dict[str, int] = defaultdict(int)
        self._events_by_id: dict[str, dict[str, Any]] = {}
        self._time_cache: dict[tuple[str, bool], EventTimeReachability] = {}
        self._build()

    def _build(self) -> None:
        ids: dict[str, dict[str, Any]] = {}
        duplicate_ids: set[str] = set()
        region_by_occurrence: dict[str, list[dict[str, Any]]] = defaultdict(list)
        scoped_roots: dict[str, list[dict[str, Any]]] = defaultdict(list)
        handoff_by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in self.events:
            address = event_address(event)
            if address:
                self.occurrences.add(address)
            if event.get("type") == "REGION_ENTER" and isinstance(event.get("occurrence"), str):
                region_by_occurrence[event["occurrence"]].append(event)
            if (self._is_scoped_root(event) and event.get("type") != "REGION_ENTER"):
                scoped_roots[str(event["occurrence"])].append(event)
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
        self._events_by_id = ids

        # Explicit parent identity is stronger than temporal order. parent_id
        # must resolve to a unique event in this trace.
        for event in self.events:
            if (event.get("type") != "REGION_ENTER" or
                    not event.get("parent_id") or event.get("parent_id") == "root"):
                continue
            def same_actor_before(candidate: dict[str, Any]) -> bool:
                return (candidate.get("node") == event.get("node") and
                        candidate.get("epoch") == event.get("epoch") and
                        event_seq(candidate) < event_seq(event) and
                        (not self.reject_coarse_roots or
                         candidate.get("thread_id") is not None and
                         candidate.get("thread_id") == event.get("thread_id")))

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
            if parent is None and self._is_scoped_root_id(event, event.get("parent_id")):
                # The Java probe binds a root region to the bounded root
                # segment of the same JVM thread. The latest event in that
                # segment establishes local program order; an actor-wide
                # legacy root is never eligible for this continuation.
                matches = [candidate for candidate in scoped_roots.get(
                    str(event["parent_id"]), [])
                    if same_actor_before(candidate) and
                    candidate.get("thread_id") == event.get("thread_id") and
                    candidate.get("thread_id") is not None]
                parent = max(matches, key=event_seq) if matches else None
            if parent is None:
                self.gaps["unmatched_parent"] += 1
            else:
                evidence = ("scoped_root_same_thread" if self._is_scoped_root(parent)
                            else "unique_parent_id_or_handoff_token")
                self._add(parent, event, "region_parent", evidence)

        self._add_nested_program_order(ids)
        self._pair("SEND", "RECV", "rpc", ("transport", "correlation", "port"),
                   ("attempt", "half"), exclusive_consumers=True)
        self._pair("TASK_SUBMIT", "TASK_CLAIM", "task", ("correlation",),
                   ("attempt",), exclusive_consumers=True)
        self._pair("TASK_COMPLETE", "TASK_JOIN", "task_result",
                   ("node", "epoch", "correlation"), exclusive_consumers=True)
        # Probe object IDs and sampled versions are JVM-local. Matching o1
        # across nodes or restart epochs would fabricate a state relation.
        self._pair("STATE_WRITE", "STATE_READ", "state",
                   ("node", "epoch", "object", "key", "version"))

    def _add_nested_program_order(self, ids: dict[str, dict[str, Any]]) -> None:
        """Bridge an event in a live parent region to a direct child entry.

        The parent-entry edge alone cannot carry an event that happens later
        in the parent. Use the last event on that exact occurrence and JVM
        thread before the child enters. Validate the entire thread's region
        stack before publishing any edge, so a later malformed exit cannot
        leave an earlier, apparently valid, bridge in the graph.
        """
        groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
        invalid_groups: set[tuple[str, str, int]] = set()
        invalid_region_addresses: set[str] = set()
        enter_counts: dict[str, int] = defaultdict(int)
        for event in self.events:
            address = event_address(event)
            if event.get("type") == "REGION_ENTER" and address is not None:
                enter_counts[address] += 1
            thread = event.get("thread_id")
            if not isinstance(thread, int) or isinstance(thread, bool):
                if event.get("type") in {"REGION_ENTER", "REGION_EXIT"} and address:
                    invalid_region_addresses.add(address)
                continue
            node, epoch = event.get("node"), event.get("epoch")
            if not isinstance(node, str) or epoch is None:
                continue
            group = (str(event["node"]), str(event["epoch"]), thread)
            if address is None:
                if event.get("type") in {"REGION_ENTER", "REGION_EXIT"}:
                    invalid_groups.add(group)
                continue
            seq = event.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
                invalid_groups.add(group)
                continue
            event_id = event.get("id")
            if not isinstance(event_id, str) or ids.get(event_id) is not event:
                invalid_groups.add(group)
                continue
            groups[group].append(event)

        for group, rows in groups.items():
            if group in invalid_groups:
                continue
            rows.sort(key=event_seq)
            if any(event_seq(left) == event_seq(right)
                   for left, right in zip(rows, rows[1:])):
                self.gaps["program_order_ambiguous_sequence"] += 1
                continue
            # Each frame holds its enter, latest local event, and a child exit
            # awaiting the first continuation in this frame. The latter is a
            # real same-thread handoff, not an inferred shared-state edge.
            stack: list[list[dict[str, Any]]] = []
            pending_edges: list[tuple[dict[str, Any], dict[str, Any]]] = []
            balanced = True
            for event in rows:
                kind = event.get("type")
                address = event_address(event)
                if stack and len(stack[-1]) == 3:
                    parent_enter, _, child_exit = stack[-1]
                    resumes_parent = (address == event_address(parent_enter) and
                                      event.get("region") == parent_enter.get("region"))
                    enters_sibling = (kind == "REGION_ENTER" and
                                      event.get("parent_id") ==
                                      parent_enter.get("occurrence"))
                    if resumes_parent or enters_sibling:
                        pending_edges.append((child_exit, event))
                        stack[-1].pop()
                if kind == "REGION_EXIT":
                    if (not stack or event_address(stack[-1][0]) != address or
                            event.get("region") != stack[-1][0].get("region")):
                        self.gaps["program_order_unbalanced_region"] += 1
                        balanced = False
                        break
                    stack.pop()
                    if stack:
                        # A nested exit precedes the parent's next operation.
                        # Publish only after the entire thread proves balanced.
                        stack[-1].append(event)
                elif kind == "REGION_ENTER":
                    if stack and event.get("parent_id") != stack[-1][0].get("occurrence"):
                        self.gaps["program_order_unbalanced_region"] += 1
                        balanced = False
                        break
                    if stack and enter_counts[address] == 1:
                        parent_enter, producer = stack[-1]
                        parent_address = event_address(parent_enter)
                        producer_id = producer.get("id")
                        consumer_id = event.get("id")
                        if (parent_address != address and
                                enter_counts[parent_address] == 1 and
                                parent_address not in invalid_region_addresses and
                                address not in invalid_region_addresses and
                                isinstance(parent_enter.get("region"), str) and
                                parent_enter["region"] and
                                isinstance(event.get("region"), str) and event["region"] and
                                producer is not parent_enter and
                                producer.get("region") == parent_enter["region"] and
                                isinstance(producer_id, str) and ids.get(producer_id) is producer and
                                isinstance(consumer_id, str) and ids.get(consumer_id) is event):
                            pending_edges.append((producer, event))
                    stack.append([event, event])
                elif stack and address == event_address(stack[-1][0]):
                    parent_enter = stack[-1][0]
                    if event.get("region") == parent_enter.get("region"):
                        stack[-1][1] = event
            if balanced and stack:
                self.gaps["program_order_unbalanced_region"] += 1
                balanced = False
            if balanced:
                for producer, consumer in pending_edges:
                    self._add(producer, consumer, "program_order",
                              ("same_thread_nested_return" if
                               producer.get("type") == "REGION_EXIT" else
                               "same_thread_direct_nested_region"))

    def _add(self, producer: dict[str, Any], consumer: dict[str, Any], kind: str,
             evidence: str, *, certainty: str = "observed") -> None:
        if self.reject_coarse_roots:
            for endpoint in (producer, consumer):
                if self._is_coarse_root(endpoint):
                    self.gaps["coarse_root_edge_rejected"] += 1
                    return
                if self._is_legacy_unscoped(endpoint):
                    self.gaps["unscoped_token_edge_rejected"] += 1
                    return
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

    @classmethod
    def _is_coarse_root(cls, event: dict[str, Any]) -> bool:
        occurrence = event.get("occurrence")
        base = f"unscoped:{event.get('node')}:{event.get('epoch')}:root"
        return (event.get("context") in (None, "root") and
                isinstance(occurrence, str) and
                (occurrence == base or occurrence.startswith(base + ":")) and
                not cls._is_scoped_unscoped(event))

    @classmethod
    def _is_legacy_unscoped(cls, event: dict[str, Any]) -> bool:
        occurrence = event.get("occurrence")
        prefix = f"unscoped:{event.get('node')}:{event.get('epoch')}:"
        return (isinstance(occurrence, str) and occurrence.startswith(prefix) and
                not cls._is_scoped_unscoped(event))

    @staticmethod
    def _is_scoped_unscoped(event: dict[str, Any]) -> bool:
        context = event.get("context")
        thread_id = event.get("thread_id")
        occurrence = event.get("occurrence")
        if (not isinstance(context, str) or not context or
                not isinstance(thread_id, int) or isinstance(thread_id, bool) or
                not isinstance(occurrence, str)):
            return False
        prefix = (f"unscoped:{event.get('node')}:{event.get('epoch')}:"
                  f"{context}:thread:{thread_id}:segment:")
        return occurrence.startswith(prefix) and occurrence[len(prefix):].isdigit()

    @staticmethod
    def _is_scoped_root_id(event: dict[str, Any], occurrence: Any) -> bool:
        thread_id = event.get("thread_id")
        if (event.get("context") != "root" or not isinstance(thread_id, int)
                or isinstance(thread_id, bool)):
            return False
        prefix = (f"unscoped:{event.get('node')}:{event.get('epoch')}:root:"
                  f"thread:{thread_id}:segment:")
        return (isinstance(occurrence, str) and occurrence.startswith(prefix)
                and occurrence[len(prefix):].isdigit())

    @classmethod
    def _is_scoped_root(cls, event: dict[str, Any]) -> bool:
        return cls._is_scoped_root_id(event, event.get("occurrence")) and cls._is_scoped_unscoped(event)

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

    def backward_event_reachability(self, target: dict[str, Any], *,
                                    include_candidates: bool = False
                                    ) -> EventTimeReachability:
        """Prove paths ending before one TARGET_CHECK, using event IDs and order.

        A direct same-occurrence/same-thread door has an empty-edge witness.
        Audit callers require at least one edge for an observed graph path.
        Older traces lacking numeric thread IDs cannot provide this proof.
        """
        target_id = target.get("id")
        if not isinstance(target_id, str) or self._events_by_id.get(target_id) is not target:
            return EventTimeReachability(target, {}, {})
        cache_key = (target_id, include_candidates)
        cached = self._time_cache.get(cache_key)
        if cached is not None:
            return cached
        address, seq, thread = event_address(target), event_seq(target), target.get("thread_id")
        if (address is None or seq < 0 or not isinstance(thread, int) or
                isinstance(thread, bool)):
            result = EventTimeReachability(target, {}, {})
            self._time_cache[cache_key] = result
            return result
        incoming: dict[str, list[Edge]] = defaultdict(list)
        for edge in self.edges | (self.candidate_edges if include_candidates else set()):
            incoming[edge.target].append(edge)
        for edges in incoming.values():
            edges.sort(key=lambda edge: (edge.consumer_event, edge.producer_event))
        first = (address, thread, False)
        cutoffs = {first: seq}
        paths: dict[tuple[str, int, bool], tuple[Edge, ...]] = {first: ()}
        pending = [(first, seq)]
        while pending:
            current, cutoff = pending.pop()
            if cutoffs[current] != cutoff:
                continue
            for edge in incoming.get(current[0], ()):
                producer = self._events_by_id.get(edge.producer_event)
                consumer = self._events_by_id.get(edge.consumer_event)
                if producer is None or consumer is None:
                    continue
                p_seq, c_seq = event_seq(producer), event_seq(consumer)
                p_thread, c_thread = producer.get("thread_id"), consumer.get("thread_id")
                if (p_seq < 0 or c_seq < 0 or p_seq >= c_seq or c_seq > cutoff or
                        not isinstance(p_thread, int) or isinstance(p_thread, bool) or
                        c_thread != current[1] or event_address(producer) != edge.source or
                        event_address(consumer) != edge.target):
                    continue
                previous = (edge.source, p_thread, True)
                if p_seq > cutoffs.get(previous, -1):
                    cutoffs[previous] = p_seq
                    paths[previous] = (edge,) + paths[current]
                    pending.append((previous, p_seq))
        result = EventTimeReachability(target, cutoffs, paths)
        self._time_cache[cache_key] = result
        return result

    def event_path(self, door: dict[str, Any], target: dict[str, Any], *,
                   include_candidates: bool = False,
                   require_edge: bool = True) -> tuple[Edge, ...] | None:
        """Return a time-respecting witness, or None when no proof exists."""
        door_id = door.get("id")
        if not isinstance(door_id, str) or self._events_by_id.get(door_id) is not door:
            return None
        return self.backward_event_reachability(
            target, include_candidates=include_candidates).witness(
                door, require_edge=require_edge)

    def summary(self) -> dict[str, Any]:
        return {"occurrences": len(self.occurrences), "edges": len(self.edges),
                "candidate_edges": len(self.candidate_edges),
                "edges_by_kind": {kind: sum(e.kind == kind for e in self.edges)
                                  for kind in sorted({e.kind for e in self.edges})},
                "candidate_edges_by_kind": {kind: sum(e.kind == kind for e in self.candidate_edges)
                                            for kind in sorted({e.kind for e in self.candidate_edges})},
                "gaps": dict(sorted(self.gaps.items()))}
