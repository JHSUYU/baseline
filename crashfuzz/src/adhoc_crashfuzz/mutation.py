"""CrashFuzz-style one-fault mutations over observed boundary events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .model import FaultAction, FaultSequence, PointKey


@dataclass(frozen=True)
class NodeGroup:
    members: frozenset
    max_down: int

    def __post_init__(self) -> None:
        if self.max_down < 0 or self.max_down >= len(self.members):
            raise ValueError("max_down must leave at least one group member alive")


@dataclass(frozen=True)
class ObservedPoint:
    key: PointKey
    order: int  # controller arrival order in this trial
    epoch: int = 0
    site_occurrence: int = 0  # per node, process epoch, site, and phase


def _validate_groups(nodes: Set[str], groups: Sequence[NodeGroup]) -> None:
    covered: Set[str] = set()
    for group in groups:
        if not group.members <= nodes or covered & group.members:
            raise ValueError("node groups must be disjoint subsets of nodes")
        covered.update(group.members)
    if covered != nodes:
        raise ValueError("every node must belong to exactly one limit group")


def state_after(sequence: FaultSequence, nodes: Set[str],
                groups: Sequence[NodeGroup]) -> Tuple[Set[str], Set[str]]:
    """Validate a sequence and return its live/dead node sets."""
    _validate_groups(nodes, groups)
    live, dead = set(nodes), set()
    for action in sequence.actions:
        node = action.target_node
        if node not in nodes:
            raise ValueError("fault targets unknown node: " + node)
        if action.kind == "CRASH":
            if node not in live or action.trigger.node != node:
                raise ValueError("crash requires a live reporting node")
            group = next(g for g in groups if node in g.members)
            if len(dead & group.members) >= group.max_down:
                raise ValueError("crash exceeds max_down")
            live.remove(node)
            dead.add(node)
        else:
            if node not in dead or action.trigger.node not in live:
                raise ValueError("reboot needs a dead target and live reporter")
            dead.remove(node)
            live.add(node)
    return live, dead


def mutate_one_fault(sequence: FaultSequence,
                     points: Sequence[ObservedPoint],
                     nodes: Iterable[str], groups: Sequence[NodeGroup],
                     max_faults: int, last_injected_order: int = -1,
                     max_candidates: Optional[int] = None) -> List[FaultSequence]:
    """Add one valid event after the last successfully injected fault.

    `points` is the *actual* trial trace, never the planned fault-free trace.
    The controller supplies arrival order; cross-process wall clocks do not.
    """
    node_set = set(nodes)
    if max_faults < 1 or len(sequence.actions) >= max_faults:
        return []
    live, dead = state_after(sequence, node_set, groups)
    produced: List[FaultSequence] = []
    seen: Set[str] = set()
    for point in sorted(points, key=lambda p: p.order):
        if point.order <= last_injected_order or point.key.node not in live:
            continue
        node = point.key.node
        group = next(g for g in groups if node in g.members)
        proposals: List[FaultAction] = []
        if len(dead & group.members) < group.max_down:
            proposals.append(FaultAction("CRASH", point.key, node,
                                         point.site_occurrence))
        proposals.extend(FaultAction("REBOOT", point.key, target,
                                     point.site_occurrence)
                         for target in sorted(dead))
        for action in proposals:
            candidate = sequence.append(action)
            fingerprint = candidate.fingerprint()
            if fingerprint not in seen:
                seen.add(fingerprint)
                produced.append(candidate)
                if max_candidates is not None and len(produced) >= max_candidates:
                    return produced
    return produced
