#!/usr/bin/env python3
"""Negative controls for the sealed SOLR-38 exact-reference audit."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import audit


ARCHIVE = (audit.ROOT / "data/mallory/evidence_archives/"
           "SOLR-38-election-value-healthy-node1-v2.tar.gz")
MEMBER = "SOLR-38-election-value-healthy-node1-v2/trials/r0000/events.jsonl.gz"


class UniqueWriterAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if audit.sha(ARCHIVE) != audit.SEALED_ARCHIVE_SHA256:
            raise ValueError("sealed archive digest differs")
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            compressed = archive.extractfile(MEMBER).read()
        if hashlib.sha256(compressed).hexdigest() != audit.SEALED_TRACE_SHA256:
            raise ValueError("sealed trace digest differs")
        cls.events = [json.loads(line) for line in gzip.decompress(compressed).splitlines()]

    def test_sealed_positive_and_native_graph_gap(self) -> None:
        rows = audit.witnesses(self.events)
        self.assertEqual(len(rows), 12)
        self.assertEqual({r["descriptor_object"] for r in rows}, {"o24", "o37"})
        self.assertTrue(all(r["last_writer_before_read"] == r["native_write"]
                            and r["intervening_native_writes"] == 0
                            and r["complete_trace_native_writer_count"] == 2
                            and not r["core_graph_strict_path"] for r in rows))

    def test_same_value_on_different_object_is_rejected(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row.get("site") == audit.VALUE_WRITE:
                row["object"] = "another-descriptor"
        self.assertEqual(audit.witnesses(events), [])

    def test_additional_native_writer_is_rejected(self) -> None:
        events = copy.deepcopy(self.events)
        writes = [row for row in events if row.get("type") == "STATE_WRITE"
                  and str(row.get("site", "")).startswith(audit.NATIVE_WRITE)
                  and row.get("object") in {"o24", "o37"}]
        self.assertEqual(len(writes), 2)
        for write in writes:
            competing = copy.deepcopy(write)
            competing["seq"] = write["seq"] + 1
            competing["id"] = write["id"] + ":competing"
            events.append(competing)
        self.assertEqual(audit.witnesses(events), [])

    def test_wrong_thread_cannot_link_read_to_target(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row.get("site") == audit.VALUE_READ:
                row["thread_id"] = -1
        self.assertEqual(audit.witnesses(events), [])

    def test_wrong_election_exception_is_rejected(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row.get("type") == "DOOR_OBSERVED" and str(row.get("site", "")).startswith(audit.DOOR):
                row["exception_class"] = "java.io.IOException"
        self.assertEqual(audit.witnesses(events), [])

    def test_false_getter_return_is_rejected(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row.get("site") == audit.VALUE_READ:
                row["key"] = "solr38:isLeader=false"
        self.assertEqual(audit.witnesses(events), [])

    def test_mismatched_target_occurrence_is_rejected(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row.get("type") == "TARGET_CHECK" and str(row.get("site", "")).startswith(audit.TARGET):
                row["occurrence"] = "different-target-invocation"
        self.assertEqual(audit.witnesses(events), [])

    def test_truncated_trace_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "truncated trace"):
            audit.witnesses(self.events + [{"type": "TRACE_TRUNCATED"}])

    def test_changed_source_is_rejected(self) -> None:
        source = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in audit.SOURCE_PINS:
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((source / name).read_bytes())
            self.assertEqual(len(audit.verify_source(root)), 5)
            target = root / next(name for name in audit.SOURCE_PINS if name.endswith("CloudDescriptor.java"))
            target.write_bytes(target.read_bytes() + b"\n// changed\n")
            with self.assertRaisesRegex(ValueError, "pinned Solr source differs"):
                audit.verify_source(root)


if __name__ == "__main__":
    unittest.main()
