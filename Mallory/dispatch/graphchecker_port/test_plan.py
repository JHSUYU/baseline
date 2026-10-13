import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from Mallory.dispatch.graphchecker_port.plan import build_plan, checkpoint_state


class PlanTest(unittest.TestCase):
    def test_only_core_terminal_checkpoint_with_result_skips_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = [
                {"case_id": f"{prefix}-{n:02d}", "system": system}
                for prefix, system, count in (("HDFS", "hdfs", 50),
                                              ("HBASE", "hbase", 30),
                                              ("SOLR", "solr", 20),
                                              ("ZOOKEEPER", "zookeeper", 2))
                for n in range(1, count + 1)
            ]
            inventory = root / "inventory.json"
            inventory.write_text(json.dumps({"cases": cases}), encoding="utf-8")
            configs = root / "configs"
            configs.mkdir()
            (configs / "HDFS-01.json").write_text("{}", encoding="utf-8")
            config_digest = hashlib.sha256(b"{}").hexdigest()
            state = root / "state"
            (state / "HDFS-01").mkdir(parents=True)
            (state / "HDFS-01/checkpoint.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HDFS-01",
                "config_sha256": config_digest, "status": "running",
                "terminal": False}), encoding="utf-8")
            (state / "HDFS-02").mkdir()
            (state / "HDFS-02/checkpoint.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HDFS-02",
                "config_sha256": "pinned", "status": "complete_queue",
                "terminal": True}), encoding="utf-8")
            (state / "HDFS-02/summary.json").write_text(json.dumps({
                "case_id": "HDFS-02", "config_sha256": "pinned",
                "status": "complete_queue", "terminal": True}), encoding="utf-8")
            (state / "HDFS-03").mkdir()
            (state / "HDFS-03/checkpoint.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HDFS-03",
                "config_sha256": "pinned", "status": "complete_queue",
                "terminal": True}), encoding="utf-8")
            (configs / "HDFS-04.json").write_text("{}", encoding="utf-8")
            (state / "HDFS-04").mkdir()
            (state / "HDFS-04/checkpoint.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HDFS-04",
                "config_sha256": "old-config", "status": "running",
                "terminal": False}), encoding="utf-8")
            plan = build_plan(inventory, configs, state)
            by_id = {row["case_id"]: row for row in plan["cases"]}
            self.assertEqual("resumable", by_id["HDFS-01"]["checkpoint_state"])
            self.assertEqual("waiting_snapshots", by_id["HDFS-01"]["dispatch_state"])
            self.assertEqual("skip_terminal", by_id["HDFS-02"]["dispatch_state"])
            self.assertEqual("blocked_terminal_without_summary",
                             by_id["HDFS-03"]["checkpoint_state"])
            self.assertEqual("blocked_config_changed",
                             by_id["HDFS-04"]["checkpoint_state"])
            self.assertEqual("waiting_config", by_id["SOLR-01"]["dispatch_state"])
            self.assertEqual("node0", by_id["HDFS-01"]["host"])
            self.assertEqual("node2", by_id["SOLR-01"]["host"])
            self.assertEqual(1, plan["max_jobs_per_host"])

    def test_unknown_or_mismatched_checkpoint_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = root / "HBASE-01"
            case.mkdir()
            checkpoint = case / "checkpoint.json"
            checkpoint.write_text(json.dumps({"case_id": "HBASE-01",
                                              "schema_version": 1,
                                              "config_sha256": "pinned",
                                              "status": "done"}), encoding="utf-8")
            self.assertEqual("blocked_unknown_checkpoint_schema",
                             checkpoint_state("HBASE-01", root)[0])
            checkpoint.write_text(json.dumps({"case_id": "HDFS-01",
                                              "schema_version": 1,
                                              "config_sha256": "pinned",
                                              "status": "running",
                                              "terminal": False}), encoding="utf-8")
            self.assertEqual("blocked_invalid_checkpoint",
                             checkpoint_state("HBASE-01", root)[0])


if __name__ == "__main__":
    unittest.main()
