#!/usr/bin/env python3
"""SOLR-38 source-backed last-writer STATE edge for one pinned Solr version.

The base Mallory graph remains unchanged. This case-local graph adds an
observed edge only after the complete trace and pinned source prove the same
CloudDescriptor object's unique setter write and actual getter return.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
AUDIT = HERE.parent / "election-unique-writer-audit-v1/audit.py"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph as BaseGraph  # noqa: E402

spec = importlib.util.spec_from_file_location("solr38_unique_writer_audit", AUDIT)
if spec is None or spec.loader is None:
    raise RuntimeError("pinned SOLR-38 offline audit unavailable")
unique_writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(unique_writer)


class SourceBackedSolr38Graph(BaseGraph):
    """Promote only independently audited, target-bound value event pairs."""

    def __init__(self, events: tuple[dict, ...], *, reject_coarse_roots: bool = False):
        unique_writer.verify_source(SOURCE)
        super().__init__(events, reject_coarse_roots=reject_coarse_roots)
        by_id = self._events_by_id
        witnesses = unique_writer.witnesses(list(events))
        pairs = {(row["value_write"], row["value_read"]) for row in witnesses}
        for producer_id, consumer_id in sorted(pairs):
            producer, consumer = by_id.get(producer_id), by_id.get(consumer_id)
            if producer is None or consumer is None:
                self.gaps["solr38_missing_audited_event"] += 1
                continue
            if (producer.get("type") != "STATE_WRITE" or
                    producer.get("site") != unique_writer.VALUE_WRITE or
                    consumer.get("type") != "STATE_READ" or
                    consumer.get("site") != unique_writer.VALUE_READ):
                self.gaps["solr38_audited_event_changed"] += 1
                continue
            self._add(producer, consumer, "state",
                      "solr38_source_backed_last_writer_same_object_same_thread",
                      certainty="observed")
        # The typed I/O door is inside waitForReplicasToComeUp, while the
        # setter event is in its caller runLeaderProcess. The pinned source
        # and balanced same-thread region intervals in the witness establish
        # the return-to-caller order, which the generic graph does not infer.
        for door_id, write_id in sorted({(row["door"], row["value_write"])
                                         for row in witnesses}):
            door, write = by_id.get(door_id), by_id.get(write_id)
            if door is None or write is None:
                self.gaps["solr38_missing_audited_return"] += 1
                continue
            self._add(door, write, "program_order",
                      "solr38_source_backed_same_thread_nested_return",
                      certainty="observed")


def install() -> None:
    """Install before the campaign analyzes any trial, including healthy r0000."""
    from Mallory.core import feedback
    feedback.OccurrenceGraph = SourceBackedSolr38Graph
