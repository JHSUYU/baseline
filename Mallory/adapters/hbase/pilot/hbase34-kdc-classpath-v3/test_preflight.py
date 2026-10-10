#!/usr/bin/env python3
"""Offline HBASE-34 v3 admission tests; no Java process is launched."""

import copy
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


PREFLIGHT = module("hbase34_v3_preflight", HERE / "preflight.py")
RUN = module("hbase34_v3_run", HERE / "run_case.py")


class HelperAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pins = json.loads((HERE / "manifest.json").read_text())
        cls.config = json.loads((HERE / "healthy.json").read_text())
        cls.parent = json.loads((HERE.parent / "hbase34-kdc-classpath-v2/healthy.json").read_text())

    def test_exact_config_is_accepted(self):
        PREFLIGHT.validate_v3_config(self.config, self.parent, self.pins)

    def test_workload_change_is_rejected(self):
        changed = copy.deepcopy(self.config)
        changed["command"][-1] = "testDifferentMethod"
        with self.assertRaisesRegex(ValueError, "more than the isolated helper"):
            PREFLIGHT.validate_v3_config(changed, self.parent, self.pins)

    def test_fault_promotion_change_is_rejected(self):
        changed = copy.deepcopy(self.config)
        changed["auto_promote_if_healthy"] = True
        with self.assertRaisesRegex(ValueError, "more than the isolated helper"):
            PREFLIGHT.validate_v3_config(changed, self.parent, self.pins)

    def test_trial_classpath_reorder_is_rejected(self):
        changed = copy.deepcopy(self.config)
        cp_index = changed["command"].index("-cp") + 1
        cp = changed["command"][cp_index].split(":")
        cp.remove(PREFLIGHT.TRIAL_CP)
        cp.append(PREFLIGHT.TRIAL_CP)
        changed["command"][cp_index] = ":".join(cp)
        with self.assertRaisesRegex(ValueError, "more than the isolated helper"):
            PREFLIGHT.validate_v3_config(changed, self.parent, self.pins)

    def test_prepare_creates_exact_trial_local_classes(self):
        with tempfile.TemporaryDirectory(prefix="mallory-hbase34-v3-offline-") as work:
            trial = Path(work) / "r0000"
            trial.mkdir()
            directory = RUN.prepare(trial, self.pins)
            self.assertEqual(directory, trial / "hbase34-testclasses")
            for key in ("helper_jar", "anchor_tests_jar"):
                item = self.pins[key]
                with zipfile.ZipFile(item["path"]) as archive:
                    self.assertEqual((directory / item["member"]).read_bytes(),
                                     archive.read(item["member"]))
            probe = directory / "ssl-probe.xml"
            probe.write_text("writable trial resource root")
            self.assertEqual(probe.read_text(), "writable trial resource root")

    def test_prepare_rejects_modified_source_pin(self):
        with tempfile.TemporaryDirectory(prefix="mallory-hbase34-v3-offline-") as work:
            trial = Path(work) / "r0000"
            trial.mkdir()
            changed = copy.deepcopy(self.pins)
            changed["helper_jar"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "pinned source jar changed"):
                RUN.prepare(trial, changed)


if __name__ == "__main__":
    unittest.main()
