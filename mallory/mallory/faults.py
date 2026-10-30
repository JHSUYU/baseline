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
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .graph import (RunGraph, context_of, node_of_address, read_trace, region_of_address, role,
                    short_site, timeline)


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


_COUNTERS = re.compile(r"([#@])\d+")


def _fold(text: str) -> str:
    """An address or endpoint with its instance counters folded (``#3``, ``@1``, ``att:0``)."""
    return _COUNTERS.sub(r"\1N", re.sub(r"att:\d+", "att:N", text or ""))


def generalized(trace: Path, plan: tuple[FaultPoint, ...]) -> list[tuple[FaultPoint, ...]]:
    """Each of ``plan``'s window faults with its siblings in the run of ``trace``: the
    evaluations of the same site and root, on a node of the same role, at the same
    invocation, under an occurrence of the same shape -- its address with instance
    counters folded, and for an occurrence serving a message exchange that
    exchange's request (its producer's call path and operation), so that the same
    request of another session or attempt is a sibling. Not Mallory's fault identity
    (it is a replay's): planting every sibling makes the detecting failure happen
    whichever of them the run's timing makes decisive. An outside fault stays alone.
    """
    rows = list(read_trace(trace))
    anchor_correlation: dict[str, str] = {}
    request: dict[str, str] = {}
    for row in rows:
        if row.get("event") != "EXCHANGE_SEND":
            continue
        anchor_correlation[row.get("producerEndpointId", "")] = row.get("correlationId", "")
        if row.get("half") == "REQUEST":
            request[row.get("correlationId", "")] = row.get("producerEndpoint", "")

    def shape(address: str) -> str:
        ctx = address.split("/ctx:", 1)[1].split("/idx:", 1)[0] if "/ctx:" in address else ""
        anchor = re.match(r"Anchor:([0-9a-f]+)@", ctx)
        if anchor and request.get(anchor_correlation.get(anchor.group(1), "")):
            path = address.split("/idx:", 1)[1] if "/idx:" in address else ""
            return ("exchange " + _fold(request[anchor_correlation[anchor.group(1)]])
                    + " | " + _fold(path))
        return _fold(address.split("/region/", 1)[-1])

    counted: dict[tuple[str, str], int] = {}
    evaluations = []                       # (site, root, occurrence, invocation, address)
    for row in rows:
        if row.get("event") != "PLANT_MARKER" or not row.get("occurrences"):
            continue
        innermost = row["occurrences"][0]
        for occurrence in row["occurrences"]:
            counted[(row["siteId"], occurrence)] = counted.get((row["siteId"], occurrence), 0) + 1
        evaluations.append((row["siteId"], row.get("rootId", ""), innermost,
                            counted[(row["siteId"], innermost)], row.get("occurrenceAddress", "")))
    address_of = {(site, occurrence, invocation): address
                  for site, _, occurrence, invocation, address in evaluations}
    groups = []
    for point in plan:
        address = address_of.get(point.key)
        if point.outside or address is None:
            groups.append((point,))
            continue
        wanted = (point.site, point.root, role(node_of_address(address)), point.invocation,
                  shape(address))
        seen = {point.key}
        group = [point]
        for site, root, occurrence, invocation, other in evaluations:
            if ((site, root, role(node_of_address(other)), invocation, shape(other)) == wanted
                    and (site, occurrence, invocation) not in seen):
                seen.add((site, occurrence, invocation))
                group.append(FaultPoint(site=site, root=root, occurrence=occurrence,
                                        invocation=invocation, node=node_of_address(other),
                                        line=point.line, region=region_of_address(other),
                                        context=context_of(other), seq=-1))
        groups.append(tuple(group))
    return groups


def to_json(plan: tuple[FaultPoint, ...]) -> list[dict]:
    return [asdict(point) for point in plan]


def from_json(rows: list[dict]) -> tuple[FaultPoint, ...]:
    return tuple(FaultPoint(**row) for row in rows)
