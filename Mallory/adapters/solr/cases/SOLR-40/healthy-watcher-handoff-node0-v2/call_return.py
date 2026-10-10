"""Conservative same-thread return edges for a balanced instrumented call stack.

The shared Mallory graph connects a parent event to a nested REGION_ENTER.
This module supplies the other direction: a child REGION_EXIT to the first
subsequent event on its still-live parent region. It does not infer a shared
field edge or promote sampled state evidence to observed evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def add_balanced_returns(graph: Any, events: tuple[dict, ...], event_address: Any,
                         event_seq: Any) -> dict[str, int]:
    """Add observed return edges only for wholly balanced actor/thread groups."""
    ids = Counter(row.get("id") for row in events if isinstance(row.get("id"), str))
    enters = Counter(event_address(row) for row in events
                     if row.get("type") == "REGION_ENTER" and event_address(row) is not None)
    groups: dict[tuple[str, int, int], list[dict]] = defaultdict(list)
    for row in events:
        node, epoch, thread = row.get("node"), row.get("epoch"), row.get("thread_id")
        if (isinstance(node, str) and isinstance(epoch, int) and
                isinstance(thread, int) and not isinstance(thread, bool)):
            groups[(node, epoch, thread)].append(row)
    counters: Counter[str] = Counter()
    for rows in groups.values():
        rows.sort(key=event_seq)
        stack: list[dict] = []
        pending: list[tuple[dict, str]] = []
        staged: list[tuple[dict, dict]] = []
        valid = True
        last_seq = -1
        for row in rows:
            seq, address, kind = event_seq(row), event_address(row), row.get("type")
            row_id = row.get("id")
            if (seq <= last_seq or address is None or
                    not isinstance(row_id, str) or ids[row_id] != 1):
                valid = False
                break
            last_seq = seq
            # A return may enter the parent only while that exact frame lives.
            if pending and stack:
                live = {event_address(frame) for frame in stack}
                pending = [(exit_row, parent) for exit_row, parent in pending
                           if parent in live]
                for exit_row, parent in tuple(pending):
                    if address == parent:
                        staged.append((exit_row, row))
                        pending.remove((exit_row, parent))
            if kind == "REGION_ENTER":
                if (enters[address] != 1 or
                        (stack and row.get("parent_id") != stack[-1].get("occurrence"))):
                    valid = False
                    break
                stack.append(row)
            elif kind == "REGION_EXIT":
                if (not stack or event_address(stack[-1]) != address or
                        stack[-1].get("region") != row.get("region")):
                    valid = False
                    break
                stack.pop()
                if stack:
                    parent = stack[-1]
                    if row.get("occurrence") != parent.get("occurrence"):
                        pending.append((row, event_address(parent)))
        if stack:
            valid = False
        if not valid:
            counters["unbalanced_or_ambiguous_group"] += 1
            continue
        for producer, consumer in staged:
            prior = len(graph.edges)
            graph._add(producer, consumer, "return",
                       "balanced_same_thread_child_exit_to_parent")
            if len(graph.edges) > prior:
                counters["observed_return_edges"] += 1
    graph._time_cache.clear()
    return dict(counters)
