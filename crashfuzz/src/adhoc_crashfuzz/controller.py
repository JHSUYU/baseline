"""Synchronous fault-point controller for independently running JVM nodes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socketserver
import threading
import time
from typing import List, Protocol

from .model import Event, FaultAction, FaultSequence, PointKey
from .mutation import ObservedPoint


class NodeControl(Protocol):
    def kill_node(self, node: str) -> None: ...
    def start_node(self, node: str) -> None: ...


class FaultController:
    def __init__(self, sequence: FaultSequence, backend: NodeControl,
                 journal: Path):
        self.sequence = sequence
        self.backend = backend
        self.journal = journal
        self.points: List[ObservedPoint] = []
        self.injected: List[tuple] = []  # (action, arrival order)
        self.match_modes = {}  # arrival order -> exact or site_occurrence
        self.error = ""
        self._next = 0
        self._frozen = False
        self._epochs = {}
        self._site_counts = {}
        self._lock = threading.Lock()
        journal.parent.mkdir(parents=True, exist_ok=True)

    @property
    def complete(self) -> bool:
        return not self.error and self._next == len(self.sequence.actions)

    @property
    def last_injected_order(self) -> int:
        return self.injected[-1][1] if self.injected else -1

    def freeze(self) -> bool:
        """End fault injection at the workload boundary, before checkers run."""
        with self._lock:
            self._frozen = True
            return self.complete

    def on_event(self, row: dict) -> str:
        try:
            event = Event.from_dict(row)
            key = event.point_key()
        except (KeyError, TypeError, ValueError) as invalid:
            return "ERROR invalid fault-point event: " + str(invalid)
        with self._lock:
            if self._frozen:
                return "CONTINUE"
            if self.error:
                return "ERROR " + self.error
            order = len(self.points)
            epoch = self._epochs.get(key.node, 0)
            count_key = (key.node, epoch, key.site, key.phase)
            site_occurrence = self._site_counts.get(count_key, 0) + 1
            self._site_counts[count_key] = site_occurrence
            self.points.append(ObservedPoint(key, order, epoch,
                                             site_occurrence))
            match_mode = ""
            if self._next < len(self.sequence.actions):
                planned = self.sequence.actions[self._next]
                if key == planned.trigger:
                    match_mode = "exact"
                elif (planned.site_occurrence == site_occurrence
                      and planned.site_occurrence > 0
                      and key.node == planned.trigger.node
                      and key.site == planned.trigger.site
                      and key.phase == planned.trigger.phase
                      and key.ordinal == planned.trigger.ordinal):
                    match_mode = "site_occurrence"
            matched = bool(match_mode)
            record = {"order": order, "epoch": epoch, "point": key.to_dict(),
                      "site_occurrence": site_occurrence,
                      "matched": matched, "match_mode": match_mode,
                      "wall_ms": int(time.time() * 1000),
                      "process": event.process, "seq": event.seq}
            # The controller journal and the agent trace are durable before
            # any crash command can be issued.
            with self.journal.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record, sort_keys=True) + "\n")
                out.flush()
                os.fsync(out.fileno())
            if not matched:
                return "CONTINUE"
            action = self.sequence.actions[self._next]
            try:
                if action.kind == "CRASH":
                    self.backend.kill_node(action.target_node)
                else:
                    self.backend.start_node(action.target_node)
                    self._epochs[action.target_node] = (
                        self._epochs.get(action.target_node, 0) + 1)
            except Exception as failure:
                self.error = "{} {} failed: {}".format(
                    action.kind, action.target_node, failure)
                return "ERROR " + self.error
            self.injected.append((action, order))
            self.match_modes[order] = match_mode
            self._next += 1
            return "CONTINUE"


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, controller: FaultController):
        self.controller = controller
        super().__init__(address, _Handler)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(60)
        raw = self.rfile.readline(65537)
        if not raw or len(raw) > 65536:
            self.wfile.write(b"ERROR invalid event length\n")
            return
        try:
            row = json.loads(raw)
            answer = self.server.controller.on_event(row)
        except (json.JSONDecodeError, TypeError) as invalid:
            answer = "ERROR invalid JSON: " + str(invalid)
        try:
            self.wfile.write((answer + "\n").encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            # An injected crash can close the reporting node's socket.
            pass


class EventServer:
    def __init__(self, controller: FaultController, host: str = "0.0.0.0",
                 port: int = 0):
        self._server = _Server((host, port), controller)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def __enter__(self) -> "EventServer":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
