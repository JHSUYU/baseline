"""GraphChecker's causal graph of one native run, abstracted as Mallory abstracts a run.

A run's GraphChecker trace (``runtime_trace.jsonl``) names every event by the
node that ran it (GraphChecker's source identity, e.g. ``auto0/master0#epoch0``)
and pairs what crosses nodes: a message's send with its receipt (transport,
correlation id, attempt and half), a store write with the reads and watch
notifications of the same version. Mallory (Meng et al., CCS 2023) observes a
run as Lamport timelines, one per node, joined by those cross-node relations,
and abstracts each event to a label that is stable across runs. The run's
observation is its set of abstract happens-before edges:

* program order: consecutive abstract events of one timeline: a node's thread,
  its name's numbers folded so pool threads of one kind align across runs
  (a mini cluster's nodes share one JVM; each thread is a sequential process);
* message: a send to its receipt;
* state: a store write to each read or watch notification of its version.

Comparing these edge sets between runs is Mallory's feedback: a run that adds
edges no earlier run had changed the system's causal behavior.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# GraphChecker trace events that become abstract events; the rest (field reads,
# call-site entries and returns, source bookkeeping) are finer than a timeline.
TIMELINE_EVENTS = {
    "METHOD_ENTER", "BRANCH", "EXCHANGE_SEND", "EXCHANGE_RECEIVE",
    "STORE_WRITE", "STORE_READ", "WATCH_FIRED", "PLANT_APPLIED", "PLANT_FATAL",
}

Event = tuple[str, str]          # (timeline: node | thread kind, abstract label)
Edge = tuple[Event, Event]


def read_trace(path: Path) -> Iterator[dict]:
    """Rows of a (possibly gzipped) trace; a JVM ended mid-row ends the trace."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if not line.endswith("\n"):
                return
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def node_of_address(address: str) -> str:
    """The node of an occurrence address (``<node>/region/...``)."""
    return address.split("/region/", 1)[0] if "/region/" in address else ""


def region_of_address(address: str) -> str:
    """The region of an occurrence address (``.../region/<region>/ctx:...``)."""
    rest = address.split("/region/", 1)[1] if "/region/" in address else ""
    return rest.split("/ctx:", 1)[0]


def context_of(address: str, frames: int = 3) -> str:
    """Where in GraphChecker's graph an occurrence stands, stable across runs.

    Its context (``ctx:``) names the message exchange it serves
    (``Anchor:<id>``, kept: GraphChecker names a message's handling by it) or
    the kind of root it runs under (``Root:CLIENT/test``, its counter dropped);
    its index (``idx:``) is the call path, of which the last frames before the
    occurrence's own method are kept.
    """
    ctx = address.split("/ctx:", 1)[1].split("/idx:", 1)[0] if "/ctx:" in address else ""
    anchor = re.match(r"(Anchor:[0-9a-f]+)@", ctx)
    ctx = anchor.group(1) if anchor else re.sub(r"#\d+$", "", ctx)
    path = address.split("/idx:", 1)[1] if "/idx:" in address else ""
    calls = [short_method(frame.split(">@", 1)[0] + ">") for frame in re.split(r"/(?=<)", path) if frame]
    return ctx + " " + ">".join(calls[-frames - 1:-1])


def short_method(signature: str) -> str:
    """``<pkg.Class: ret name(args)>`` -> ``Class.name``."""
    match = re.match(r"<([\w.$]+): [^ ]+ ([\w$<>]+)\(", signature or "")
    if not match:
        return signature or ""
    return match.group(1).rsplit(".", 1)[-1] + "." + match.group(2)


def short_site(site: str) -> str:
    """A bytecode site ``<...>#uN`` as ``Class.method#uN``."""
    method, _, unit = (site or "").partition("#")
    return short_method(method) + ("#" + unit if unit else "")


_NUMBERED = re.compile(r"\d{4,}")
_DIGITS = re.compile(r"\d+")


def timeline(node: str, thread: str) -> str:
    """A node's thread as a timeline, its numbers folded (pool and handler threads)."""
    return node + " | " + _DIGITS.sub("N", thread or "")


def stable_location(location: str) -> str:
    """A store location with run-specific numbers (sequential znodes, ids) folded."""
    return _NUMBERED.sub("N", location or "")


@dataclass
class RunGraph:
    """The abstract happens-before graph of one run."""

    edges: set[Edge] = field(default_factory=set)
    events: list[tuple[int, Event]] = field(default_factory=list)   # (trace seq, event)
    markers: list[dict] = field(default_factory=list)                # PLANT_MARKER rows
    applied_rows: set[int] = field(default_factory=set)              # plant rows applied
    fatal: bool = False                                              # PLANT_FATAL at the anchor
    fatal_rows: list[dict] = field(default_factory=list)
    # door evaluations outside GraphChecker's recording window (OUTSIDE_MARKER /
    # OUTSIDE_APPLIED rows) and the (site, place, invocation) of those failed
    outside: list[dict] = field(default_factory=list)
    outside_applied: set[tuple[str, str, int]] = field(default_factory=set)

    def timeline_before(self, line: str, seq: int, depth: int) -> tuple[str, ...]:
        """The last ``depth`` abstract labels of timeline ``line`` before trace ``seq``."""
        labels: list[str] = []
        for at, (owner, label) in reversed(self.events):
            if at >= seq or owner != line:
                continue
            labels.append(label)
            if len(labels) == depth:
                break
        return tuple(reversed(labels))


def outside_log(trace: Path) -> Path:
    """Where a run states its door evaluations outside the recording window."""
    return trace.parent.parent / (trace.parent.name + ".outside.jsonl")


def build(trace: Path, outside: Path | None = None) -> RunGraph:
    """GraphChecker's graph of the run whose trace is ``trace``.

    ``outside`` is the run's log of door evaluations outside the window: no
    graph event (GraphChecker names nothing there), but fault points.
    """
    graph = RunGraph()
    if outside is not None and (outside.is_file() or Path(str(outside) + ".gz").is_file()):
        for row in read_trace(outside if outside.is_file() else Path(str(outside) + ".gz")):
            graph.outside.append(row)
            if row.get("event") == "OUTSIDE_APPLIED":
                graph.outside_applied.add((row.get("siteId", ""), row.get("place", ""),
                                           row.get("invocation", 0)))
    call_line: dict[int, str] = {}
    marker_line = ""
    sends: dict[tuple, Event] = {}
    receipts: list[tuple[tuple, Event]] = []
    writes: dict[tuple[str, str], Event] = {}
    reads: list[tuple[tuple[str, str], Event]] = []
    last_on_line: dict[str, str] = {}

    def add(seq: int, line: str, label: str) -> Event:
        event = (line, label)
        previous = last_on_line.get(line)
        if previous is not None and previous != label:
            graph.edges.add(((line, previous), event))
        last_on_line[line] = label
        graph.events.append((seq, event))
        return event

    for row in read_trace(trace):
        kind = row.get("event")
        seq = row.get("seq", 0)
        if kind == "PLANT_MARKER":
            graph.markers.append(row)
            # the fault a marker plants is stated next, from the same call on the same thread
            marker_line = timeline(node_of_address(row.get("occurrenceAddress", "")) or "?",
                                   row.get("threadName", ""))
            continue
        if kind not in TIMELINE_EVENTS:
            continue
        if kind == "METHOD_ENTER":
            node = row.get("sourceKey") or node_of_address(row.get("occurrenceAddress", ""))
            if not node:
                continue
            line = timeline(node, row.get("threadName", ""))
            if isinstance(row.get("callId"), int):
                call_line[row["callId"]] = line
            add(seq, line, "enter " + short_method(row.get("method", "")))
        elif kind == "BRANCH":
            line = call_line.get(row.get("callId"), "")
            if line:
                add(seq, line, f"branch {short_site(row.get('siteId', ''))}={row.get('outcome')}")
        elif kind in ("EXCHANGE_SEND", "EXCHANGE_RECEIVE"):
            line = timeline(row.get("sourceKey") or "?", row.get("threadName", ""))
            key = (row.get("transport"), row.get("correlationId"), row.get("attemptId"),
                   row.get("half"))
            if kind == "EXCHANGE_SEND":
                event = add(seq, line, f"send {row.get('transport')} {row.get('half')} "
                                       f"{short_method(row.get('method', ''))}")
                sends[key] = event
            else:
                event = add(seq, line, f"receive {row.get('transport')} {row.get('half')}")
                receipts.append((key, event))
        elif kind in ("STORE_WRITE", "STORE_READ", "WATCH_FIRED"):
            location = stable_location(row.get("location", ""))
            line = timeline(node_of_address(row.get("occurrenceAddress", "")) or "?",
                            row.get("threadName", ""))
            version = (row.get("location", ""), str(row.get("version", "")))
            if kind == "STORE_WRITE":
                writes[version] = add(seq, line, f"write {row.get('transport')} {location}")
            elif kind == "STORE_READ":
                reads.append((version, add(seq, line, f"read {row.get('op')} {location}")))
            else:
                event = add(seq, line, f"watch {row.get('type')} {location}")
                reads.append(((row.get("location", ""), "*"), event))
        elif kind == "PLANT_APPLIED":
            graph.applied_rows.add(row.get("row"))
            add(seq, marker_line or "?", f"fault {row.get('planted', '')}")
        elif kind == "PLANT_FATAL":
            node = node_of_address(row.get("occurrenceAddress", "")) or "?"
            graph.fatal_rows.append(row)
            graph.fatal = graph.fatal or bool(row.get("atAnchor"))
            add(seq, timeline(node, "target"), "fatal " + short_site(row.get("siteId", "")))

    for key, receipt in receipts:
        sent = sends.get(key)
        if sent is not None:
            graph.edges.add((sent, receipt))
    latest_write: dict[str, Event] = {}
    for (location, version), event in writes.items():
        latest_write[location] = event
    for (location, version), event in reads:
        written = writes.get((location, version)) if version != "*" else latest_write.get(location)
        if written is not None and written != event:
            graph.edges.add((written, event))
    return graph
