"""Mallory's adaptive fault schedule: Q-learning over where to fail next.

Mallory (Meng et al., CCS 2023) treats fault scheduling as reinforcement
learning. A state is an abstract observation of the system when a fault could
be injected; an action is the fault; the reward is how much new causal behavior
the run then showed. Here a state is where a fault marker is about to be
evaluated in GraphChecker's graph (its node and thread, region, the message
exchange or root it serves and its call path) with the last abstract events of
its thread's timeline, an action is which failure at
which code site (``FaultPoint.action``), and the reward grows with the run's new
happens-before edges. Values start optimistic, so every action is tried at
least once in each state before a learned value can rank it below another;
epsilon-greedy keeps a share of random choices.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

TIMELINE_DEPTH = 2


def reward(new_edges: int) -> float:
    """New happens-before edges, saturating: one new edge is worth much, the 50th little."""
    return 1.0 - math.exp(-new_edges / 10.0)


@dataclass
class QPolicy:
    alpha: float = 0.5          # learning rate
    gamma: float = 0.5          # discount of the state the fault leads to
    epsilon: float = 0.1        # share of random choices
    optimistic: float = 1.0     # the value of an action never tried in a state
    seed: int = 0
    values: dict[str, dict[str, float]] = field(default_factory=dict)
    tries: dict[str, dict[str, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.random = random.Random(self.seed)

    def value(self, state: str, action: str) -> float:
        return self.values.get(state, {}).get(action, self.optimistic)

    def best(self, state: str) -> float:
        """The state's best action value; an action not yet tried there counts as optimistic."""
        return max([self.optimistic, *self.values.get(state, {}).values()])

    def choose(self, candidates: list, state_of, action_of, tried_count) -> int:
        """Index of the candidate to run next.

        ``state_of``/``action_of`` map a candidate to its state and action;
        ``tried_count`` to how often its exact plan's action ran in that state,
        which breaks ties toward the less explored.
        """
        if not candidates:
            raise ValueError("no candidate fault plan")
        if self.random.random() < self.epsilon:
            return self.random.randrange(len(candidates))
        return max(range(len(candidates)), key=lambda index: (
            self.value(state_of(candidates[index]), action_of(candidates[index])),
            -tried_count(candidates[index]), -index))

    def update(self, state: str, action: str, gained: float, next_state: str | None) -> float:
        future = self.best(next_state) if next_state is not None else 0.0
        old = self.value(state, action)
        new = old + self.alpha * (gained + self.gamma * future - old)
        self.values.setdefault(state, {})[action] = new
        counts = self.tries.setdefault(state, {})
        counts[action] = counts.get(action, 0) + 1
        return new

    def to_json(self) -> dict:
        return {"values": self.values, "tries": self.tries}

    def load(self, data: dict) -> None:
        self.values = data.get("values", {})
        self.tries = data.get("tries", {})


def state_key(point, timeline: tuple[str, ...]) -> str:
    """Where a fault point stands in GraphChecker's graph, with its thread's last abstract events."""
    return f"{point.line} | {point.region} | {point.context} | " + " > ".join(timeline)
