#!/usr/bin/env python3
"""Offline negative checks for HBASE-34 v2 admission; no JVM is started."""

import copy
import importlib.util
import json
import struct
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("hbase34_v2_preflight", HERE / "preflight.py")
assert SPEC and SPEC.loader
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


class V2AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((HERE / "healthy.json").read_text())
        cls.parent = json.loads((HERE.parent / "hbase34-kdc-classpath-v1/healthy.json").read_text())
        cls.pins = json.loads((HERE / "manifest.json").read_text())

    def test_exact_v2_is_accepted(self):
        PREFLIGHT.validate_v2_config(self.config, self.parent, self.pins)

    def test_bc_provider_after_wildcard_is_rejected(self):
        changed = copy.deepcopy(self.config)
        cp = PREFLIGHT.classpath(changed)
        cp.remove(self.pins["bc_order"][0])
        cp.append(self.pins["bc_order"][0])
        changed["command"][changed["command"].index("-cp") + 1] = ":".join(cp)
        with self.assertRaisesRegex(ValueError, "more than the allowed classpath"):
            PREFLIGHT.validate_v2_config(changed, self.parent, self.pins)

    def test_workload_change_is_rejected(self):
        changed = copy.deepcopy(self.config)
        changed["command"][-1] = "testOtherToken"
        with self.assertRaisesRegex(ValueError, "more than the allowed classpath"):
            PREFLIGHT.validate_v2_config(changed, self.parent, self.pins)

    def test_fault_trial_promotion_is_rejected(self):
        changed = copy.deepcopy(self.config)
        changed["auto_promote_if_healthy"] = True
        with self.assertRaisesRegex(ValueError, "more than the allowed classpath"):
            PREFLIGHT.validate_v2_config(changed, self.parent, self.pins)

    def test_java_eight_major_gate(self):
        header = b"\xca\xfe\xba\xbe\x00\x00"
        self.assertEqual(PREFLIGHT.class_major(header + struct.pack(">H", 52)), 52)
        self.assertGreater(PREFLIGHT.class_major(header + struct.pack(">H", 53)), 52)
        with self.assertRaisesRegex(ValueError, "invalid Java class"):
            PREFLIGHT.class_major(b"not a class")


if __name__ == "__main__":
    unittest.main()
