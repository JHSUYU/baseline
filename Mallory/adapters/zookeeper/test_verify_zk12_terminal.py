"""Tamper regressions for the independent ZK12 terminal evidence gate."""

import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_zk12_terminal as gate


class TerminalVerifierTest(unittest.TestCase):
    def fixture(self):
        occurrence = "zk0:2:org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V:root:1"
        common = {"node": "zk0", "epoch": 2, "thread_id": 17,
                  "occurrence": occurrence}
        events = [
            {"id": "m", "seq": 1, "ts": 100, "type": "FAULT_MATCHED",
             "fault_id": "f", "site": gate.DOOR, "door_ordinal": 3,
             "exception_class": gate.EXCEPTION, **common},
            {"id": "a", "seq": 2, "ts": 101, "type": "FAULT_APPLIED",
             "fault_id": "f", "site": gate.DOOR, "door_ordinal": 3,
             "exception_class": gate.EXCEPTION, **common},
            {"id": "c", "seq": 3, "ts": 102, "type": "TARGET_CHECK",
             "site": gate.CHECK, **common},
        ]
        trial = {
            "case_id": gate.CASE, "trial_id": 1,
            "plan": [{"fault_type": "EXCEPTION", "exception_class": gate.EXCEPTION,
                      "fault_id": "f", "point": {"site": gate.DOOR, "node": "zk0",
                                                  "epoch": 2, "door_ordinal": 3}}],
            "feedback": {"all_faults_matched": True, "all_faults_applied": True,
                         "all_faults_effective": True, "status": "observed"},
            "junit_validation": {"status": "passed"},
        }
        return trial, events

    def encode(self, trial, events):
        raw = b"".join(json.dumps(e).encode() + b"\n" for e in events)
        compressed = gzip.compress(raw, mtime=0)
        trial["events_evidence"] = {
            "gzip_sha256": hashlib.sha256(compressed).hexdigest(),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_bytes": len(raw),
        }
        return compressed

    def test_valid_strict_continuation(self):
        trial, events = self.fixture()
        row = gate.verify_trial(trial, self.encode(trial, events), 1)
        self.assertEqual(row["classification"], "target_retained_no_throw")
        self.assertEqual(row["postfault_check_ids"], ["c"])

    def test_trace_byte_tamper_rejected(self):
        trial, events = self.fixture()
        trace = self.encode(trial, events)
        with self.assertRaisesRegex(ValueError, "compressed trace digest"):
            gate.verify_trial(trial, trace + b"X", 1)

    def test_match_apply_order_tamper_rejected_even_with_new_hash(self):
        trial, events = self.fixture()
        events[0]["seq"], events[1]["seq"] = 2, 1
        with self.assertRaisesRegex(ValueError, "event sequence"):
            gate.verify_trial(trial, self.encode(trial, events), 1)

    def test_different_thread_target_cannot_count(self):
        trial, events = self.fixture()
        events[2]["thread_id"] = 18
        with self.assertRaisesRegex(ValueError, "core status disagrees"):
            gate.verify_trial(trial, self.encode(trial, events), 1)

    def test_selected_throw_rejected(self):
        trial, events = self.fixture()
        events.append({"id": "t", "seq": 4, "ts": 103, "type": "TARGET_THROW",
                       "site": gate.THROW, "node": "zk0", "epoch": 2,
                       "thread_id": 17, "occurrence": events[0]["occurrence"]})
        with self.assertRaisesRegex(ValueError, "selected target exception"):
            gate.verify_trial(trial, self.encode(trial, events), 1)

    def test_archive_member_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "case.tar.gz"
            payload = b"evidence"
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("trials/r0001/result.json")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            manifest = {
                "archive_sha256": gate.digest(archive.read_bytes()),
                "members": {"trials/r0001/result.json": {
                    "bytes": len(payload), "sha256": gate.digest(b"tampered")}},
            }
            with self.assertRaisesRegex(ValueError, "archive member changed"):
                gate.archive_members(archive, manifest)


if __name__ == "__main__":
    unittest.main()
