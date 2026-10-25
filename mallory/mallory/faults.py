"""Fault points: where a run could fail, and the plant that makes a run fail there.

A planted GraphChecker run states every fault marker it evaluates
(``PLANT_MARKER``: the marker's root name, its call site and the run's enclosing
occurrence ids, innermost first). A fault point is one such evaluation: the
call site, the innermost enclosing occurrence and the invocation of that site
under that occurrence. Planting a ``FAULT`` row with those three makes the
marker fail at that very evaluation (``RecordingPlant.marker`` counts a site's
evaluations under the planted occurrence the same way).
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
    seq: int           # its trace seq in the run it was observed in

    @property
    def action(self) -> str:
        """What Mallory's policy chooses: which failure, at which code site."""
        return f"{self.root} @ {short_site(self.site)}"

    @property
    def key(self) -> tuple[str, str, int]:
        return self.site, self.occurrence, self.invocation


def points(graph: RunGraph, after_seq: int = -1) -> list[FaultPoint]:
    """Every marker evaluation of a run after ``after_seq``, as a fault point."""
    counted: dict[tuple[str, str], int] = {}
    found = []
    for row in graph.markers:
        occurrences = row.get("occurrences") or []
        if not occurrences:
            continue
        innermost = occurrences[0]
        for occurrence in occurrences:
            counted[(row["siteId"], occurrence)] = counted.get((row["siteId"], occurrence), 0) + 1
        if row.get("seq", -1) <= after_seq:
            continue
        found.append(FaultPoint(site=row["siteId"], root=row.get("rootId", ""),
                                occurrence=innermost,
                                invocation=counted[(row["siteId"], innermost)],
                                node=node_of_address(row.get("occurrenceAddress", "")),
                                line=timeline(node_of_address(row.get("occurrenceAddress", "")) or "?",
                                              row.get("threadName", "")),
                                region=region_of_address(row.get("occurrenceAddress", "")),
                                context=context_of(row.get("occurrenceAddress", "")),
                                seq=row.get("seq", -1)))
    return found


def compatible(plan: tuple[FaultPoint, ...], point: FaultPoint) -> bool:
    """A plan plants one occurrence per site, so its invocations count alike."""
    return all(p.key != point.key and (p.site != point.site or p.occurrence == point.occurrence)
               for p in plan)


def plan_id(plan: tuple[FaultPoint, ...]) -> str:
    text = json.dumps([list(p.key) for p in plan])
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def write_plant(path: Path, plan: tuple[FaultPoint, ...], target_rows: list[dict]) -> list[int]:
    """The plant for ``plan``; returns the plant rows of its faults."""
    rows = []
    for point in plan:
        rows.append({"kind": "ROOT", "category": "FAULT", "rootId": point.root,
                     "occurrence": point.occurrence, "siteId": point.site,
                     "invocation": point.invocation, "value": "true"})
    rows.extend(dict(row) for row in target_rows)
    for number, row in enumerate(rows):
        row["row"] = number
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return list(range(len(plan)))


def to_json(plan: tuple[FaultPoint, ...]) -> list[dict]:
    return [asdict(point) for point in plan]


def from_json(rows: list[dict]) -> tuple[FaultPoint, ...]:
    return tuple(FaultPoint(**row) for row in rows)
