"""Admission rejects a stale resolver before any workload JUnit starts."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign


class ExactResolverProtocolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.jar = self.root / "analysis.jar"
        self.jar.write_bytes(b"pinned-analysis-jar")
        self.dependencies = self.root / "dependencies.txt"
        self.dependencies.write_text("/dependency/example.jar\n")
        self.config = {"runner": {"mode": "region_state"},
                       "recording": {"target_occurrence": "actor/region/exact"}}

    def probe(self, stdout, returncode=0):
        return subprocess.CompletedProcess([], returncode, stdout, "")

    def test_source_built_schema_two_is_pinned_at_admission(self):
        capabilities = {
            "schemaVersion": 1,
            "kind": "MALLORY_TARGET_RESOLVER_CAPABILITIES",
            "exactRequestedOccurrenceReceiptSchemaVersion": 2,
            "exactSelectionPolicy":
                "EXACT_REQUESTED_OCCURRENCE_THEN_EARLIEST_EVENT"}
        with patch.object(campaign, "_analysis_engine_jar", return_value=self.jar), \
             patch.object(campaign, "DEPENDENCIES", self.dependencies), \
             patch.object(campaign.subprocess, "run",
                          return_value=self.probe(json.dumps(capabilities))) as run:
            receipt = campaign._require_exact_resolver_protocol(
                self.config, Path('/usr/bin/python3'))
        self.assertEqual(campaign._sha(self.jar),
                         receipt["analysis_engine_jar_sha256"])
        self.assertEqual(capabilities, receipt["capabilities"])
        self.assertEqual("--capabilities", run.call_args.args[0][-1])
        self.assertEqual(20, run.call_args.kwargs["timeout"])

    def test_stale_schema_one_jar_fails_closed(self):
        with patch.object(campaign, "_analysis_engine_jar", return_value=self.jar), \
             patch.object(campaign, "DEPENDENCIES", self.dependencies), \
             patch.object(campaign.subprocess, "run",
                          return_value=self.probe('{"schemaVersion":1}')):
            with self.assertRaisesRegex(ValueError,
                                        "lacks exact occurrence receipt schema 2"):
                campaign._require_exact_resolver_protocol(
                    self.config, Path('/usr/bin/python3'))

    def test_old_jar_without_capabilities_fails_closed(self):
        with patch.object(campaign, "_analysis_engine_jar", return_value=self.jar), \
             patch.object(campaign, "DEPENDENCIES", self.dependencies), \
             patch.object(campaign.subprocess, "run",
                          return_value=self.probe("", returncode=1)):
            with self.assertRaisesRegex(ValueError,
                                        "lacks exact occurrence receipt schema 2"):
                campaign._require_exact_resolver_protocol(
                    self.config, Path('/usr/bin/python3'))

    def test_no_exact_region_target_needs_no_protocol_probe(self):
        self.config["recording"].pop("target_occurrence")
        with patch.object(campaign.subprocess, "run") as run:
            self.assertIsNone(campaign._require_exact_resolver_protocol(
                self.config, Path('/usr/bin/python3')))
        run.assert_not_called()

    def test_cached_admission_fails_before_recording_or_workload(self):
        weave = self.root / "weave.json"
        weave.write_text(json.dumps({"java": "/usr/bin/python3"}))
        self.config["native_weave_config"] = str(weave)
        with patch.object(campaign, "verify_existing", return_value={}), \
             patch.object(campaign, "_require_exact_resolver_protocol",
                          side_effect=ValueError("stale schema 1")) as gate, \
             patch.object(campaign, "_verify_recording_plan") as recorder:
            with self.assertRaisesRegex(ValueError, "stale schema 1"):
                campaign._admit(self.config, self.root)
        gate.assert_called_once()
        recorder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
