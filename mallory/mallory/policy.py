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

import hashlib
import math
import random
from dataclasses import dataclass, field

TIMELINE_DEPTH = 2


def reward(new_edges: int, noise: int = 0) -> float:
    """New happens-before edges beyond the workload's own noise, saturating.

    ``noise`` is how many edges a second fault-free run added to the first:
    a run adding no more than that shows nothing a fault caused.
    """
    return 1.0 - math.exp(-max(0, new_edges - noise) / 10.0)


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
        self.draws = 0

    def value(self, state: str, action: str) -> float:
        return self.values.get(state, {}).get(action, self.optimistic)

    def best(self, state: str) -> float:
        """The state's best action value; an action not yet tried there counts as optimistic."""
        return max([self.optimistic, *self.values.get(state, {}).values()])

    def choose(self, candidates: list, state_of, action_of, tried_count,
               identity_of=repr) -> int:
        """Index of the candidate to run next.

        ``state_of``/``action_of`` map a candidate to its state and action;
        ``tried_count`` to how often its exact plan's action ran in that state,
        which breaks ties toward the less explored. The rest of a tie, and an
        epsilon choice, is drawn by hashing the seed with the candidate's
        ``identity_of`` (its plan): random, yet the same draw however the runs
        happened to list their fault points, so a campaign repeats itself.
        """
        if not candidates:
            raise ValueError("no candidate fault plan")
        self.draws += 1

        def draw(index: int, salt: str) -> str:
            text = f"{self.seed}|{salt}|{identity_of(candidates[index])}"
            return hashlib.sha256(text.encode()).hexdigest()

        if self.random.random() < self.epsilon:
            return min(range(len(candidates)), key=lambda index: draw(index, f"epsilon{self.draws}"))
        keys = [(self.value(state_of(candidate), action_of(candidate)), -tried_count(candidate))
                for candidate in candidates]
        best = max(keys)
        return min((index for index, key in enumerate(keys) if key == best),
                   key=lambda index: draw(index, "tie"))

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
