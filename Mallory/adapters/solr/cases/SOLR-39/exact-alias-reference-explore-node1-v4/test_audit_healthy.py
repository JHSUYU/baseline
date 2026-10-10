"""Negative controls over the immutable healthy trace; no JVM is started."""

import copy
import gzip
import json
import tarfile
import unittest

from audit_healthy import ARCHIVE, HERE, PREFIX, STREAM, assess


class OutsideClosureHealthyAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            cls.events = [json.loads(line) for line in gzip.decompress(
                archive.extractfile(STREAM + "events.jsonl.gz").read()).splitlines() if line]
            log = archive.extractfile(STREAM + "junit.log").read().decode("utf-8", "replace")
        cls.markers = [json.loads(line.split(PREFIX, 1)[1]) for line in log.splitlines()
                       if PREFIX in line]
        cls.selection = json.loads((HERE / "fault-plan.json").read_text())["selection"]

    def test_exact_reference_path_is_labeled_outside_closure(self):
        result = assess(self.events, self.markers, self.selection)
        self.assertEqual(result["admission"], "outside_closure_exploratory_only")
        self.assertFalse(result["door_to_target_graph_witness"])

    def test_wrong_actor_door_is_rejected(self):
        rows = copy.deepcopy(self.events)
        next(row for row in rows if row["seq"] ==
             self.selection["healthy_watcher_door_seq"])["node"] = "node2"
        with self.assertRaises(ValueError):
            assess(rows, self.markers, self.selection)

    def test_changed_alias_reference_is_rejected(self):
        markers = copy.deepcopy(self.markers)
        for marker in markers:
            if marker.get("kind") == "write" and marker.get("node") == "node1" and (
                    marker.get("aliases_ref") == 21 and marker.get("zk_version") == 2):
                marker["aliases_ref"] = 999
                break
        with self.assertRaises(ValueError):
            assess(self.events, markers, self.selection)

    def test_false_graph_label_is_rejected(self):
        selection = dict(self.selection, observed_event_time_path_from_door=True)
        with self.assertRaises(ValueError):
            assess(self.events, self.markers, selection)


if __name__ == "__main__":
    unittest.main()
