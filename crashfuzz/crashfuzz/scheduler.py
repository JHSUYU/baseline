"""The fault-sequence queue: what to try next.

CrashFuzz favors untried I/O sites and new coverage. Before that default
ranking, a fixed table of bounded slots reserves every k-th trial for one
kind of sequence that the default ranking would otherwise starve (multi-node
reply loss, repeated reply loss on one actor, deep sequences, late
occurrences of a callsite, ...). A slot whose kind has no queued sequence
yields to the next one.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .faults import (Point, Sequence, confirmed_fault_nodes, consecutive_reply_streak,
                     exact_temporal_site_key, fault_actors, fault_family,
                     fault_variants_for_io, object_array_response, observed_identity,
                     repeated_nonempty_reply_profile, repeated_reply_loss,
                     reply_fanout_degree, same_actor_followup, sequence_id,
                     temporal_diversity_key, temporal_site_key)

# Trial statuses whose run kept the target and so may seed descendants.
ADMITTED = {"checked", "target_exception_candidate", "partial_target_exception_candidate",
            "baseline_exception_recurrence", "target_exception_unlinked"}

Entry = tuple[int, dict[str, Any]]   # (queue index, queued item)


# --- the queue -------------------------------------------------------------

def enqueue(state: dict[str, Any], sequence: Sequence, priority: int = 0,
            target_proximity: int = 0) -> None:
    """Queue a sequence once; a sequence seen before is never queued again."""
    name = sequence_id(sequence)
    if name in state["seen_sequences"]:
        return
    state["seen_sequences"][name] = True
    state["queue"].append({"id": name, "sequence": sequence, "priority": priority,
                           "created": time.time(), "target_proximity": target_proximity})


def identity_priority(point: Point) -> int:
    """Favor replayable observed actors without weakening exact matching."""
    occurrence = point.get("occurrence", "")
    source = point.get("sourceKey", "")
    score = 0
    if re.search(r"(?:port=|localhost:|127\.0\.0\.1:|qtp)\d+", occurrence):
        score -= 40
    if re.search(r"/Thread-\d+/", occurrence):
        score -= 20
    if any(name in source for name in ("ClientProtocol:", "DatanodeProtocol:",
                                       "BlockingService:", "SolrZkClient:", "ZooKeeper:")):
        score += 30
    if "java.io.FileInputStream:" in source or "java.io.FileOutputStream:" in source:
        score += 15
    if source.endswith(" close()>") or "org.apache.hadoop.util.Shell:" in occurrence:
        score -= 20
    return score


STATIC_REASON_PRIORITY = (
    ("target_short_writer_caller", 100), ("target_writer_actor_callee", 95),
    ("target_direct_field_writer", 90), ("target_actor_io_family", 85),
    ("target_short_field_writer", 80), ("target_short_call_path", 60),
    ("field_may_writer", 50), ("rpc_wire_may_producer", 50),
    ("thread_handoff_may_launcher", 50))


def static_reason_priority(reason: str) -> int:
    """How close Soot found an I/O callsite to the target's data flow."""
    return next((priority for prefix, priority in STATIC_REASON_PRIORITY
                 if reason.startswith(prefix)), 0)


def target_proximity_score(io_seq: int, check_seqs: list[int]) -> int:
    """A bounded preference for I/O just before a target check."""
    distance = min((check - io_seq for check in check_seqs if check > io_seq), default=None)
    if distance is None:
        return 0
    if distance <= 64:
        return 80
    if distance <= 256:
        return 50
    if distance <= 1024:
        return 20
    return 0


def observed_proximity(feedback: dict[str, Any]) -> dict[tuple[Any, ...], int]:
    """Each observed I/O call's best proximity to a later target check."""
    checks = feedback.get("target_check_seqs", [])
    scores: dict[tuple[Any, ...], int] = {}
    for observed in feedback.get("point_events", []):
        key = observed_identity(observed["point"])
        scores[key] = max(scores.get(key, 0),
                          target_proximity_score(observed.get("seq", -1), checks))
    return scores


def enqueue_seed(state: dict[str, Any], feedback: dict[str, Any],
                 static_priorities: dict[str, int],
                 static_exceptions: dict[str, list[str]] | None) -> None:
    """Queue one single-fault sequence per I/O point the healthy run observed."""
    proximity = observed_proximity(feedback)
    for observed in feedback["points"]:
        for point in fault_variants_for_io(observed, static_exceptions):
            near = proximity.get(observed_identity(point), 0)
            enqueue(state, [point], priority=20 + identity_priority(point) +
                    static_priorities.get(point["siteId"], 0) +
                    (15 if point.get("exceptionClass") in
                     (static_exceptions or {}).get(point["siteId"], []) else 0) + near,
                    target_proximity=near)


def enqueue_extensions(state: dict[str, Any], sequence: Sequence, result: dict[str, Any],
                       max_faults: int, static_priorities: dict[str, int] | None = None,
                       static_exceptions: dict[str, list[str]] | None = None) -> None:
    """Extend an admitted run by one I/O it actually executed after its last fault."""
    if len(sequence) >= max_faults or result.get("status") not in ADMITTED:
        return
    new_io = set(result.get("new_io_families", []))
    checks = result.get("target_check_seqs", [])
    for observed in result.get("point_events", []):
        if observed.get("seq", -1) <= result.get("last_applied_seq", -1):
            continue
        near = target_proximity_score(observed["seq"], checks)
        for point in fault_variants_for_io(observed["point"], static_exceptions):
            if point in sequence:
                continue
            enqueue(state, sequence + [point],
                    priority=10 * result.get("new_coverage_count", 0) +
                    (50 if fault_family(point) in new_io else 0) +
                    (3 if result["status"] == "target_exception_candidate" else 0) +
                    (static_priorities or {}).get(point["siteId"], 0) +
                    (15 if point.get("exceptionClass") in
                     (static_exceptions or {}).get(point["siteId"], []) else 0) +
                    identity_priority(point) + near,
                    target_proximity=near)


def completed_sequences(state: dict[str, Any]) -> list[Sequence]:
    return [item["sequence"] for item in state["completed"] if item.get("sequence")]


def budget_has_room(state: dict[str, Any], budget: dict[str, Any]) -> bool:
    """Spend trials past the base budget only while some keep the target."""
    completed = state["completed"]
    if len(completed) >= budget["max_trials"]:
        return False
    minimum = budget.get("min_target_retained_trials")
    if minimum is None or len(completed) < budget["base_trials"]:
        return True
    retained = sum(item["status"] in ADMITTED for item in completed)
    # No post-fault target observation at all is a workload or scope
    # problem; another block of trials would not gain coverage.
    return 0 < retained < minimum


# --- the bounded slots ---------------------------------------------------------
# Each slot picks among queued entries of one kind, or returns None.

def _common_tiebreak(entry: Entry) -> tuple[Any, ...]:
    index, item = entry
    return (-item.get("target_proximity", 0), -item["priority"], item["created"], index)


def _reply_fanout(queue: list[dict[str, Any]], previous: list[Sequence]) -> int | None:
    """A nonempty reply observed on several nodes may carry one state update to
    each; prefer the widest observed fanout."""
    fanout = [(index, item, reply_fanout_degree(item["sequence"]))
              for index, item in enumerate(queue)]
    fanout = [entry for entry in fanout if entry[2] >= 2]
    if not fanout:
        return None
    return min(fanout, key=lambda e: (-e[2], len(e[1]["sequence"]),
                                      -e[1].get("target_proximity", 0), -e[1]["priority"],
                                      e[1]["created"], e[0]))[0]


def _reply_chain(queue: list[dict[str, Any]], previous: list[Sequence]) -> int | None:
    """Repeated losses on one node keep a state-bearing reply absent until a
    later I/O consumes it."""
    chains = [(index, item, repeated_nonempty_reply_profile(item["sequence"]))
              for index, item in enumerate(queue)]
    chains = [entry for entry in chains if entry[2][0] >= 3]
    if not chains:
        return None
    return min(chains, key=lambda e: (-min(e[2][0], 4), len(e[1]["sequence"]), -e[2][1],
                                      -e[1].get("target_proximity", 0), -e[1]["priority"],
                                      e[1]["created"], e[0]))[0]


def _response_shape(queue: list[dict[str, Any]], previous: list[Sequence]) -> int | None:
    """A successful RPC may carry a state-changing command: single lost
    object-array replies, least tried first."""
    shaped = [(index, item) for index, item in enumerate(queue)
              if len(item["sequence"]) == 1 and object_array_response(item["sequence"][0])]
    if not shaped:
        return None

    def response_key(point: Point) -> tuple[Any, ...]:
        return (point["siteId"], point["responseShape"], fault_actors([point]),
                point.get("hitOrdinal"))

    tried: dict[tuple[Any, ...], int] = {}
    for sequence in previous:
        if object_array_response(sequence[-1]):
            key = response_key(sequence[-1])
            tried[key] = tried.get(key, 0) + 1
    return min(shaped, key=lambda e: (tried.get(response_key(e[1]["sequence"][0]), 0),)
               + _common_tiebreak(e))[0]


def _cross_actor(queue: list[dict[str, Any]], previous: list[Sequence]) -> int | None:
    """A lost control-plane reply on one actor can affect a data operation on
    another: multi-node plans, less tried node sets and shorter plans first."""
    actor_key = confirmed_fault_nodes
    cross = [(index, item) for index, item in enumerate(queue)
             if len(confirmed_fault_nodes(item["sequence"])) >= 2]
    if not cross:
        # Traces without explicit logical-node suffixes: actor names.
        actor_key = fault_actors
        cross = [(index, item) for index, item in enumerate(queue)
                 if len(fault_actors(item["sequence"])) >= 2]
    if not cross:
        return None
    tried: dict[tuple[str, ...], int] = {}
    for sequence in previous:
        actors = actor_key(sequence)
        if len(actors) >= 2:
            tried[actors] = tried.get(actors, 0) + 1
    return min(cross, key=lambda e: (tried.get(actor_key(e[1]["sequence"]), 0),
                                     len(e[1]["sequence"])) + _common_tiebreak(e))[0]


def _repeated_reply(queue: list[dict[str, Any]], previous: list[Sequence]) -> int | None:
    """A lost reply can be repaired by the next RPC: lose a second reply of the
    same actor and callsite, the closest and latest pair first."""
    repeated = [(index, item) for index, item in enumerate(queue)
                if repeated_reply_loss(item["sequence"])]
    if not repeated:
        return None
    return min(repeated, key=lambda e: (
        e[1]["sequence"][-1]["hitOrdinal"] - e[1]["sequence"][-2]["hitOrdinal"],
        -e[1]["sequence"][-2]["hitOrdinal"]) + _common_tiebreak(e))[0]


def _same_actor_followup(queue: list[dict[str, Any]], previous: list[Sequence]) -> int | None:
    """An actor may repair a failed call through a different I/O: interrupt
    that follow-up, on the least tried root first."""
    followups = [(index, item) for index, item in enumerate(queue)
                 if same_actor_followup(item["sequence"])]
    if not followups:
        return None
    tried_roots: dict[Any, int] = {}
    for sequence in previous:
        root = temporal_diversity_key(sequence[0])
        tried_roots[root] = tried_roots.get(root, 0) + 1
    return min(followups, key=lambda e: (
        tried_roots.get(temporal_diversity_key(e[1]["sequence"][0]), 0),
        -e[1].get("target_proximity", 0),
        -(e[1]["sequence"][-2]["siteId"].split(":", 1)[0] ==
          e[1]["sequence"][-1]["siteId"].split(":", 1)[0]),
        -e[1]["priority"], len(e[1]["sequence"]), e[1]["created"], e[0]))[0]


def _deep_sequence(queue: list[dict[str, Any]], previous: list[Sequence]) -> int | None:
    """Exception effects can overlap across actors: three-or-more-fault
    descendants, consecutive reply chains of one actor first."""
    deep = [(index, item) for index, item in enumerate(queue) if len(item["sequence"]) >= 3]
    if not deep:
        return None
    return min(deep, key=lambda e: (-consecutive_reply_streak(e[1]["sequence"]),
                                    -e[1].get("target_proximity", 0), -e[1]["priority"],
                                    len(e[1]["sequence"]), e[1]["created"], e[0]))[0]


def _exact_late_occurrence(queue: list[dict[str, Any]], previous: list[Sequence]) -> int | None:
    """A short JUnit can run several protocol steps inside one coarse bucket:
    an untried exact later invocation of a repeated callsite."""
    tried = {exact_temporal_site_key(sequence[-1]) for sequence in previous}
    late = [(index, item) for index, item in enumerate(queue)
            if len(item["sequence"]) == 1 and item["sequence"][-1].get("hitOrdinal", 1) > 1 and
            exact_temporal_site_key(item["sequence"][-1]) not in tried]
    if not late:
        return None
    return min(late, key=lambda e: (-e[1]["priority"], e[1]["sequence"][-1]["hitOrdinal"],
                                    e[1]["created"], e[0]))[0]


def _late_occurrence(queue: list[dict[str, Any]], previous: list[Sequence]) -> int | None:
    """A repeated I/O call can run after a control-plane state change: a later
    occurrence in an untried coarse bucket of its callsite."""
    tried = {temporal_site_key(sequence[-1]) for sequence in previous}
    late = [(index, item) for index, item in enumerate(queue)
            if len(item["sequence"]) == 1 and item["sequence"][-1].get("hitOrdinal", 1) > 1 and
            temporal_site_key(item["sequence"][-1]) not in tried]
    if not late:
        return None
    return min(late, key=lambda e: (-e[1]["priority"], e[1]["created"], e[0]))[0]


@dataclass(frozen=True)
class Slot:
    name: str
    modulus: int
    remainder: int
    choose: Callable[[list[dict[str, Any]], list[Sequence]], int | None]


# Checked in this order when the number of completed trials matches.
SLOTS = (
    Slot("reply_fanout", 10, 3, _reply_fanout),
    Slot("reply_chain", 13, 8, _reply_chain),
    Slot("response_shape", 7, 5, _response_shape),
    Slot("cross_actor", 11, 10, _cross_actor),
    Slot("repeated_reply_loss", 7, 6, _repeated_reply),
    Slot("same_actor_followup", 9, 8, _same_actor_followup),
    Slot("deep_sequence", 8, 7, _deep_sequence),
    Slot("exact_late_occurrence", 12, 11, _exact_late_occurrence),
    Slot("late_occurrence", 6, 5, _late_occurrence),
)


# --- the default ranking -------------------------------------------------------

def _default_choice(queue: list[dict[str, Any]], previous: list[Sequence],
                    static_priorities: dict[str, int] | None) -> int:
    """New I/O sites first, then new temporal families, then unrepeated roots.

    Single- and multi-fault sequences alternate; every fifth trial prefers
    I/O just before a target check and every third a target-side I/O Soot
    found, within the same ranking.
    """
    done = len(previous)
    single = sum(len(sequence) == 1 for sequence in previous)
    want_single = single <= done - single
    eligible = [(index, item) for index, item in enumerate(queue)
                if (len(item["sequence"]) == 1) == want_single] or list(enumerate(queue))
    if done % 5 == 4:
        near = [(index, item) for index, item in eligible
                if item.get("target_proximity", 0) >= 50]
        eligible = near or eligible
    if done % 3 == 2 and static_priorities:
        focused = [(index, item) for index, item in eligible
                   if max(static_priorities.get(point["siteId"], 0)
                          for point in (item["sequence"][0], item["sequence"][-1])) >= 80]
        eligible = focused or eligible
    family_counts: dict[Any, int] = {}
    # A failed request and a lost reply affect remote state differently, so
    # a callsite counts per phase.
    site_counts: dict[tuple[str, str], int] = {}
    root_counts: dict[Any, int] = {}
    for sequence in previous:
        last = temporal_diversity_key(sequence[-1])
        root = temporal_diversity_key(sequence[0])
        family_counts[last] = family_counts.get(last, 0) + 1
        site = (sequence[-1]["siteId"], sequence[-1].get("phase", "before"))
        site_counts[site] = site_counts.get(site, 0) + 1
        root_counts[root] = root_counts.get(root, 0) + 1
    # Untried callsites first, except every fourth choice, which keeps the
    # temporal-family preference alone.
    prefer_new_site = done % 4 != 3

    def rank(entry: Entry) -> tuple[Any, ...]:
        index, item = entry
        sequence = item["sequence"]
        root_penalty = (root_counts.get(temporal_diversity_key(sequence[0]), 0)
                        if len(sequence) > 1 else 0)
        site = (sequence[-1]["siteId"], sequence[-1].get("phase", "before"))
        return (site_counts.get(site, 0) if prefer_new_site else 0,
                family_counts.get(temporal_diversity_key(sequence[-1]), 0),
                root_penalty, -item["priority"], item["created"], index)

    return min(eligible, key=rank)[0]


def choose_next_sequence(state: dict[str, Any],
                         static_priorities: dict[str, int] | None = None) -> int:
    """The queue index of the next sequence to run."""
    previous = completed_sequences(state)
    for slot in SLOTS:
        if len(previous) % slot.modulus == slot.remainder:
            chosen = slot.choose(state["queue"], previous)
            if chosen is not None:
                return chosen
    return _default_choice(state["queue"], previous, static_priorities)
