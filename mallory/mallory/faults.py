"""Fault points: where a run could fail, and the plant that makes a run fail there.

A planted GraphChecker run states every fault marker it evaluates
(``PLANT_MARKER``: the marker's root name, its call site and the run's enclosing
occurrence ids, innermost first). A fault point is one such evaluation: the
call site, the innermost enclosing occurrence and the invocation of that site
under that occurrence. Planting a ``FAULT`` row with those three makes the
marker fail at that very evaluation (``RecordingPlant.marker`` counts a site's
evaluations under the planted occurrence the same way).

Outside GraphChecker's recording window no occurrence names an evaluation:
there a fault point is the call site, its place (``before`` the window opened
or ``after`` it closed, the node its thread serves, the thread's name with its
numbers folded) and the invocation counted per site and place, as the run's
``OUTSIDE_MARKER`` rows state it, with the door call's nearest callers outside
the door's package for its context; such points are planted through their own
file (``causynth.plant.outside``). So a campaign can fail any woven door
anywhere in the workload, not only where GraphChecker records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .graph import RunGraph, context_of, node_of_address, region_of_address, short_site, timeline


@dataclass(frozen=True)
class FaultPoint:
    site: str          # the marker's call site (``<...>#uN``)
    root: str          # the marker's root name: what fails, e.g. FAULT:HBASE_RPC:RESPONSE
    occurrence: str    # the innermost enclosing occurrence id
    invocation: int    # the site's evaluation under that occurrence, from 1
    node: str          # the node that evaluated it
    line: str          # its timeline: the node's thread (graph.timeline)
    region: str        # the GraphChecker region of the innermost occurrence
    context: str       # its exchange or root and call path (graph.context_of)
    seq: int           # its trace seq in the run it was observed in (-1 outside the window)
    place: str = ""    # outside the window: before|after, node, thread (else "")
    nanos: int = 0     # the JVM's nanoTime of the evaluation: one order in and out of the window

    @property
    def action(self) -> str:
        """What Mallory's policy chooses: which failure, at which code site."""
        return f"{self.root} @ {short_site(self.site)}"

    @property
    def outside(self) -> bool:
        return bool(self.place)

    @property
    def key(self) -> tuple[str, str, int]:
        return self.site, self.occurrence, self.invocation


def points(graph: RunGraph, after_nanos: int = -1) -> list[FaultPoint]:
    """Every door evaluation of a run after ``after_nanos``, in and out of the window, in order."""
    counted: dict[tuple[str, str], int] = {}
    found = []
    for row in graph.markers:
        occurrences = row.get("occurrences") or []
        if not occurrences:
            continue
        innermost = occurrences[0]
        for occurrence in occurrences:
            counted[(row["siteId"], occurrence)] = counted.get((row["siteId"], occurrence), 0) + 1
        found.append(FaultPoint(site=row["siteId"], root=row.get("rootId", ""),
                                occurrence=innermost,
                                invocation=counted[(row["siteId"], innermost)],
                                node=node_of_address(row.get("occurrenceAddress", "")),
                                line=timeline(node_of_address(row.get("occurrenceAddress", "")) or "?",
                                              row.get("threadName", "")),
                                region=region_of_address(row.get("occurrenceAddress", "")),
                                context=context_of(row.get("occurrenceAddress", "")),
                                seq=row.get("seq", -1), nanos=row.get("nanos", 0)))
    for row in graph.outside:
        place = row.get("place", "")
        phase, node, thread = (place.split("|", 2) + ["", ""])[:3]
        found.append(FaultPoint(site=row["siteId"], root=row.get("rootId", ""),
                                occurrence="outside:" + place, invocation=row.get("invocation", 0),
                                node=node, line=(node or "?") + " | " + thread,
                                region="outside " + phase,
                                # the operation it serves, as an occurrence's context does inside
                                context=f"outside {phase} {row.get('callers', '')}",
                                seq=-1, place=place, nanos=row.get("nanos", 0)))
    found.sort(key=lambda point: point.nanos)
    return [point for point in found if point.nanos > after_nanos]


def evaluated_at(graph: RunGraph, plan: tuple[FaultPoint, ...]) -> int:
    """When the run evaluated its plan's last fault (nanoTime), or -1."""
    wanted = {point.key for point in plan}
    return max((point.nanos for point in points(graph) if point.key in wanted), default=-1)


def compatible(plan: tuple[FaultPoint, ...], point: FaultPoint) -> bool:
    """A plan plants one occurrence per site in the window, so its invocations count alike."""
    return all(p.key != point.key and
               (p.outside or point.outside or p.site != point.site or
                p.occurrence == point.occurrence)
               for p in plan)


def plan_id(plan: tuple[FaultPoint, ...]) -> str:
    text = json.dumps([list(p.key) for p in plan])
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def outside_plant(path: Path) -> Path:
    """The file of a plant's faults outside the window."""
    return path.with_name(path.name.replace(".plant.jsonl", "") + ".plant-outside.jsonl")


def write_plant(path: Path, plan: tuple[FaultPoint, ...], target_rows: list[dict]
                ) -> tuple[list[int], set[tuple[str, str, int]]]:
    """The plant for ``plan``: the plant rows of its window faults, and its outside faults."""
    inside = [point for point in plan if not point.outside]
    rows = []
    for point in inside:
        rows.append({"kind": "ROOT", "category": "FAULT", "rootId": point.root,
                     "occurrence": point.occurrence, "siteId": point.site,
                     "invocation": point.invocation, "value": "true"})
    rows.extend(dict(row) for row in target_rows)
    for number, row in enumerate(rows):
        row["row"] = number
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    outside = [{"siteId": p.site, "place": p.place, "invocation": p.invocation}
               for p in plan if p.outside]
    outside_plant(path).write_text("".join(json.dumps(row) + "\n" for row in outside))
    return (list(range(len(inside))),
            {(p.site, p.place, p.invocation) for p in plan if p.outside})


def to_json(plan: tuple[FaultPoint, ...]) -> list[dict]:
    return [asdict(point) for point in plan]


def from_json(rows: list[dict]) -> tuple[FaultPoint, ...]:
    return tuple(FaultPoint(**row) for row in rows)
