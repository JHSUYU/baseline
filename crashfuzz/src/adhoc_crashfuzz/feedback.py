"""Campaign-wide target-closure novelty and fault-sequence selection."""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Dict, FrozenSet, Iterable, List, Optional, Set

from .graph import Closure
from .model import FaultSequence, PointKey


@dataclass(frozen=True)
class Delta:
    nodes: FrozenSet[str]
    edges: FrozenSet[str]
    branches: FrozenSet[str]

    @property
    def gained(self) -> bool:
        return bool(self.nodes or self.edges or self.branches)


@dataclass
class Coverage:
    nodes: Set[str] = field(default_factory=set)
    edges: Set[str] = field(default_factory=set)
    branches: Set[str] = field(default_factory=set)

    def observe(self, closure: Closure) -> Delta:
        delta = Delta(frozenset(closure.node_features - self.nodes),
                      frozenset(closure.edge_features - self.edges),
                      frozenset(closure.branch_features - self.branches))
        self.nodes.update(closure.node_features)
        self.edges.update(closure.edge_features)
        self.branches.update(closure.branch_features)
        return delta


@dataclass(frozen=True)
class Candidate:
    sequence: FaultSequence
    parent_run: str
    closure_point: bool = False
    recovery_point: bool = False
    new_point: bool = False
    parent_new_edges: int = 0
    parent_new_nodes: int = 0
    parent_seconds: float = 1.0

    def score(self) -> float:
        depth = len(self.sequence.actions)
        return (100.0 * self.closure_point
                + 45.0 * self.recovery_point
                + 20.0 * self.new_point
                + 12.0 * min(self.parent_new_edges, 8)
                + 4.0 * min(self.parent_new_nodes, 8)
                + 5.0 * min(depth, 6)
                + 10.0 / max(self.parent_seconds, 0.1))


class Queue:
    """A bounded, reproducible priority queue with an exploration quota."""

    def __init__(self, seed: int = 0, explore_probability: float = 0.15):
        if not 0 <= explore_probability <= 1:
            raise ValueError("explore_probability must be in [0,1]")
        self._rng = random.Random(seed)
        self._explore_probability = explore_probability
        self._pending: Dict[str, Candidate] = {}
        self._tested: Set[str] = set()

    def add(self, candidate: Candidate) -> bool:
        key = candidate.sequence.fingerprint()
        if key in self._pending or key in self._tested:
            return False
        self._pending[key] = candidate
        return True

    def pop(self) -> Optional[Candidate]:
        if not self._pending:
            return None
        candidates = list(self._pending.values())
        if self._rng.random() < self._explore_probability:
            candidate = self._rng.choice(candidates)
        else:
            best = max(c.score() for c in candidates)
            candidate = self._rng.choice([c for c in candidates
                                          if c.score() == best])
        key = candidate.sequence.fingerprint()
        del self._pending[key]
        self._tested.add(key)
        return candidate

    def __len__(self) -> int:
        return len(self._pending)
