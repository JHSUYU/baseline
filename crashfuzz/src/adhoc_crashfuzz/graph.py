"""Generic concrete causal graph built from JVM event streams.

Message edges require correlated endpoints. Plain field probes cannot prove
read-from, so their edges are explicitly STATE_CANDIDATE. An adapter that
records a read's observed version can produce an exact STATE edge. No global
timestamp order is assumed between processes.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .model import Event, PointKey, TargetSpec


OccurrenceId = Tuple[str, int, str, str]  # node, epoch, process, span


@dataclass(frozen=True)
class Region:
    identity: OccurrenceId
    site: str
    context: str = ""

    @property
    def node(self) -> str:
        return self.identity[0]

    @property
    def epoch(self) -> int:
        return self.identity[1]


@dataclass(frozen=True)
class Edge:
    kind: str
    producer: OccurrenceId
    consumer: OccurrenceId
    detail: str = ""


@dataclass
class CausalGraph:
    nodes: Dict[OccurrenceId, Region] = field(default_factory=dict)
    edges: Set[Edge] = field(default_factory=set)
    incoming: Dict[OccurrenceId, Set[Edge]] = field(
        default_factory=lambda: defaultdict(set))
    targets: List[Tuple[Event, OccurrenceId]] = field(default_factory=list)
    points: List[Tuple[Event, OccurrenceId]] = field(default_factory=list)
    branches: List[Tuple[Event, OccurrenceId]] = field(default_factory=list)
    blocks: List[Tuple[Event, OccurrenceId]] = field(default_factory=list)
    global_blocks: Set[str] = field(default_factory=set)
    global_branches: Set[str] = field(default_factory=set)
    gaps: List[str] = field(default_factory=list)

    def add_edge(self, edge: Edge) -> None:
        if edge.producer not in self.nodes or edge.consumer not in self.nodes:
            self.gaps.append("edge endpoint missing: " + repr(edge))
            return
        self.edges.add(edge)
        self.incoming[edge.consumer].add(edge)


@dataclass(frozen=True)
class Closure:
    nodes: frozenset
    edges: frozenset
    points: frozenset
    node_features: frozenset
    edge_features: frozenset
    branch_features: frozenset
    block_features: frozenset
    reached: bool
    fatal: bool


def read_events(trace_dir: Path) -> List[Event]:
    """Read complete JSONL records; a killed JVM may leave a partial tail."""
    events: List[Event] = []
    for path in sorted(trace_dir.glob("trace-*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    events.append(Event.from_dict(row, str(path)))
                except (json.JSONDecodeError, KeyError, ValueError) as error:
                    # Only an unterminated final row can be caused by a crash.
                    if not line.endswith("\n"):
                        break
                    raise ValueError("{}:{}: {}".format(
                        path, number, error)) from error
    return events


def _epochs(events: Sequence[Event]) -> Dict[Tuple[str, str], int]:
    first: Dict[Tuple[str, str], int] = {}
    for event in events:
        key = (event.node, event.process)
        time = event.wall_ms if event.wall_ms else 0
        first[key] = min(first.get(key, time), time)
    by_node: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for (node, process), time in first.items():
        by_node[node].append((process, time))
    return {(node, process): index
            for node, instances in by_node.items()
            for index, (process, _) in enumerate(sorted(
                instances, key=lambda item: (item[1], item[0])))}


def build_graph(events: Iterable[Event]) -> CausalGraph:
    records = list(events)
    graph = CausalGraph()
    epochs = _epochs(records)
    grouped: Dict[Tuple[str, str], List[Event]] = defaultdict(list)
    for event in records:
        grouped[(event.node, event.process)].append(event)

    sends: Dict[Tuple[str, str], List[Tuple[Event, OccurrenceId]]] = defaultdict(list)
    receives: Dict[Tuple[str, str], List[Tuple[Event, OccurrenceId]]] = defaultdict(list)

    for (node, process), process_events in grouped.items():
        last_write: Dict[str, OccurrenceId] = {}
        versioned_write: Dict[Tuple[str, str], OccurrenceId] = {}
        process_events.sort(key=lambda event: event.seq)
        for event in process_events:
            if event.kind == "BOOT":
                continue
            if event.kind == "GLOBAL_BLOCK":
                graph.global_blocks.add(event.site)
                continue
            if event.kind == "GLOBAL_BRANCH":
                graph.global_branches.add(event.site + "|" + event.outcome)
                continue
            epoch = event.epoch if event.epoch is not None else epochs[(node, process)]
            span = event.span or "ambient:{}:{}".format(event.thread, event.seq)
            identity = (node, epoch, process, span)
            if event.kind == "METHOD_ENTER":
                graph.nodes[identity] = Region(identity, event.site,
                                               event.context)
            elif identity not in graph.nodes:
                graph.nodes[identity] = Region(identity,
                                               event.site or "<ambient>",
                                               event.context)

            if event.kind == "METHOD_ENTER" and event.parent not in ("", "0"):
                parent = (node, epoch, process, event.parent)
                if parent not in graph.nodes:
                    graph.nodes[parent] = Region(parent, "<parent>")
                graph.add_edge(Edge("CALL", parent, identity))
            elif event.kind == "METHOD_EXIT" and event.parent not in ("", "0"):
                parent = (node, epoch, process, event.parent)
                if parent not in graph.nodes:
                    graph.nodes[parent] = Region(parent, "<parent>")
                graph.add_edge(Edge("RETURN", identity, parent))
            elif event.kind == "FIELD_WRITE" and event.location:
                last_write[event.location] = identity
                if event.state_version:
                    versioned_write[(event.location, event.state_version)] = identity
            elif event.kind == "FIELD_READ" and event.location:
                exact = bool(event.observed_version)
                producer = (versioned_write.get((event.location,
                                                 event.observed_version))
                            if exact else last_write.get(event.location))
                if producer is None:
                    graph.gaps.append("unwritten read {} at {}".format(
                        event.location, identity))
                else:
                    graph.add_edge(Edge("STATE" if exact else "STATE_CANDIDATE",
                                        producer, identity,
                                        event.location.split("@", 1)[0]))
            elif event.kind in ("MESSAGE_SEND", "ASYNC_SEND"):
                if event.correlation:
                    sends[(event.kind.split("_", 1)[0],
                           event.correlation)].append((event, identity))
                else:
                    graph.gaps.append("send without correlation at " + str(identity))
            elif event.kind in ("MESSAGE_RECV", "ASYNC_RECV"):
                if event.correlation:
                    receives[(event.kind.split("_", 1)[0],
                              event.correlation)].append((event, identity))
                else:
                    graph.gaps.append("receive without correlation at " + str(identity))
            elif event.kind == "TARGET":
                graph.targets.append((event, identity))
            elif event.kind == "FAULT_POINT":
                graph.points.append((event, identity))
            elif event.kind == "BRANCH":
                graph.branches.append((event, identity))
            elif event.kind == "BLOCK":
                graph.blocks.append((event, identity))

    for key, consumers in receives.items():
        producers = sends.get(key, [])
        if len(producers) != 1:
            graph.gaps.append("{} producer count {} for {} receiver(s)".format(
                key, len(producers), len(consumers)))
            continue
        producer = producers[0][1]
        for _, consumer in consumers:
            graph.add_edge(Edge(key[0], producer, consumer, key[1]))
    return graph


def _node_feature(region: Region, roles: Mapping[str, str]) -> str:
    role = roles.get(region.node, region.node)
    phase = "restarted" if region.epoch > 0 else "initial"
    return "NODE|{}|{}|{}".format(role, region.site, phase)


def _edge_feature(edge: Edge, graph: CausalGraph,
                  roles: Mapping[str, str]) -> str:
    producer = graph.nodes[edge.producer]
    consumer = graph.nodes[edge.consumer]
    relation = "same-node" if producer.node == consumer.node else "cross-node"
    epoch = "same-epoch" if producer.epoch == consumer.epoch else "cross-epoch"
    return "EDGE|{}|{}|{}|{}|{}|{}|{}".format(
        edge.kind, roles.get(producer.node, producer.node), producer.site,
        roles.get(consumer.node, consumer.node), consumer.site,
        relation, epoch) + ("|" + edge.detail
                           if edge.kind.startswith("STATE") else "")


def target_closure(graph: CausalGraph, target: TargetSpec,
                   roles: Optional[Mapping[str, str]] = None) -> Closure:
    roles = roles or {}
    hits = [(event, identity) for event, identity in graph.targets
            if target.matches(event)
            and (target.epoch is None or identity[1] == target.epoch)]
    anchors = [identity for _, identity in hits]
    if not anchors:
        # A crash may interrupt the target method before its check. Preserve
        # the observed prefix as a partial frontier, without claiming that the
        # target predicate was reached.
        method = target.site.rsplit("#B", 1)[0] if "#B" in target.site else (
            target.site.rsplit("#L", 1)[0] if "#L" in target.site else "")
        if method:
            anchors = [identity for identity, region in graph.nodes.items()
                       if region.site == method
                       and (target.epoch is None
                            or region.epoch == target.epoch)
                       and (not target.node or region.node == target.node)
                       and region.context.startswith(target.context_prefix)
                       and (not target.context
                            or region.context == target.context)]
    pending = deque(anchors)
    members: Set[OccurrenceId] = set(pending)
    edges: Set[Edge] = set()
    while pending:
        consumer = pending.popleft()
        for edge in graph.incoming.get(consumer, ()):
            edges.add(edge)
            if edge.producer not in members:
                members.add(edge.producer)
                pending.append(edge.producer)
    points: Set[PointKey] = {event.point_key() for event, identity in graph.points
                             if identity in members}
    branch_features = {"BRANCH|{}|{}|{}".format(
        roles.get(event.node, event.node), event.site, event.outcome)
        for event, identity in graph.branches if identity in members}
    block_features = {"BLOCK|{}|{}|{}".format(
        roles.get(event.node, event.node), event.site,
        "restarted" if graph.nodes[identity].epoch > 0 else "initial")
        for event, identity in graph.blocks if identity in members}
    node_features = {_node_feature(graph.nodes[member], roles)
                     for member in members}
    # Two replicas with the same role can execute the same target after a
    # failover. Keep target host identity as a separate feedback dimension.
    node_features.update(
        "TARGET_HOST|{}|{}|{}".format(
            roles.get(event.node, event.node), event.node, event.site)
        for event, _ in hits)
    return Closure(
        frozenset(members), frozenset(edges), frozenset(points),
        frozenset(node_features),
        frozenset(_edge_feature(edge, graph, roles) for edge in edges),
        frozenset(branch_features), frozenset(block_features), bool(hits),
        any(event.fatal for event, _ in hits),
    )
