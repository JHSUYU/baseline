"""The controller must verify that the original JUnit workload actually ran."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .campaign import _run_trial, run
from .junit import collect_junit_receipt


class JUnitGateTest(unittest.TestCase):
    def _fake_maven(self, root: Path, tests: int, errors: int = 0,
                    skipped: int = 0) -> dict:
        launcher = root / "mvn"
        launcher.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
suffix = next(x.split("=", 1)[1] for x in sys.argv if x.startswith("-Dsurefire.reportNameSuffix="))
reports = Path("target/surefire-reports")
reports.mkdir(parents=True, exist_ok=True)
reports.joinpath("TEST-Fake-" + suffix + ".xml").write_text(
    '<testsuite tests="' + os.environ["FAKE_TESTS"] + '" failures="0" errors="' +
    os.environ["FAKE_ERRORS"] + '" skipped="' + os.environ["FAKE_SKIPPED"] + '"/>')
event = dict(type="TARGET_CHECK", id="e1", seq=1, node="node0", epoch=0,
             occurrence="r1", region="r1", site="Fake#check")
Path(os.environ["MALLORY_EVENT_FILE"]).write_text(json.dumps(event) + "\\n")
print("BUILD SUCCESS")
''')
        launcher.chmod(0o755)
        return {"case_id": "FAKE-JUNIT", "system": "hdfs", "cluster_test": "Fake#test",
                "cwd": str(root), "command": [str(launcher), "-Dtest=Fake#test", "surefire:test"],
                "env": {"FAKE_TESTS": str(tests), "FAKE_ERRORS": str(errors),
                        "FAKE_SKIPPED": str(skipped)},
                "target": {"check_sites": ["Fake#check"], "throw_site": "Fake#throw",
                           "exception_class": "java.io.IOException"},
                "budget": {"trials": 1, "seconds": 10, "max_faults_per_trial": 1,
                           "trial_timeout_seconds": 5}}

    def test_maven_rc_zero_with_zero_tests_rejects_healthy_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = run(self._config(root, tests=0), root / "out")
            trial = json.loads((root / "out/trials/r0000/result.json").read_text())
            self.assertEqual(trial["return_code"], 0)
            self.assertTrue(trial["feedback"]["target_reached"])
            self.assertEqual(trial["feedback"]["status"], "healthy_no_tests")
            self.assertEqual(summary["status"], "healthy_seed_invalid")
            self.assertFalse(json.loads((root / "out/result.json").read_text())
                             ["healthy_seed_valid"])

    def test_maven_rc_zero_with_junit_error_rejects_healthy_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = run(self._config(root, tests=1, errors=1), root / "out")
            trial = json.loads((root / "out/trials/r0000/result.json").read_text())
            self.assertEqual(trial["return_code"], 0)
            self.assertEqual(trial["junit_validation"]["errors"], 1)
            self.assertEqual(trial["feedback"]["status"], "healthy_junit_failed")
            self.assertEqual(summary["status"], "healthy_seed_invalid")

    def test_maven_all_skipped_rejects_healthy_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = run(self._config(root, tests=1, skipped=1), root / "out")
            trial = json.loads((root / "out/trials/r0000/result.json").read_text())
            receipt = trial["junit_validation"]
            self.assertEqual(trial["feedback"]["status"], "healthy_no_tests")
            self.assertEqual(receipt["tests"], receipt["skipped"])
            self.assertEqual(receipt["stdout_sha256"], trial["stdout_sha256"])
            self.assertEqual(receipt["stderr_sha256"], trial["stderr_sha256"])
            self.assertEqual(summary["status"], "healthy_seed_invalid")

    @staticmethod
    def _config(root: Path, tests: int, errors: int = 0, skipped: int = 0) -> Path:
        config = JUnitGateTest()._fake_maven(root, tests, errors, skipped)
        path = root / "case.json"
        path.write_text(json.dumps(config))
        return path

    def test_fault_trial_junit_failure_does_not_override_target_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._fake_maven(root, tests=1, errors=1)
            result = _run_trial(config, root / "out", 1, [], lambda _pid: None, None)
            self.assertEqual(result["junit_validation"]["status"], "failed")
            self.assertEqual(result["feedback"]["status"], "observed")

    def test_production_runner_without_junit_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._fake_maven(root, tests=1)
            # An executable with an unrecognized runner shape cannot present
            # the required JUnit receipt for a production system.
            config["command"] = ["python3", "-c", "print('BUILD SUCCESS')"]
            result = _run_trial(config, root / "out", 0, [], lambda _pid: None, None)
            self.assertEqual(result["return_code"], 0)
            self.assertEqual(result["junit_validation"]["status"], "not_applicable")
            self.assertEqual(result["feedback"]["status"],
                             "healthy_junit_runner_unrecognized")

    def test_direct_junit_wrappers_are_bound_to_raw_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            (trial / "stdout.log").write_text("")
            (trial / "stderr.log").write_text("MALLORY_JUNIT found=1 succeeded=1 failed=0\n")
            hbase = collect_junit_receipt(
                trial, ["java", "edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit"],
                trial, 0, None)
            self.assertEqual(hbase["status"], "passed")
            self.assertEqual(hbase["tests"], 1)
            self.assertEqual(len(hbase["stderr_sha256"]), 64)

            (trial / "junit.log").write_text("MALLORY_TEST_RESULT run=1 failures=0 ignored=0\n")
            (trial / "pilot-result.json").write_text(json.dumps(
                {"junit": {"run": 1, "failures": 0, "ignored": 0}}))
            solr = collect_junit_receipt(
                trial, ["python3", "run_pilot.py"], trial, 0, None)
            self.assertEqual(solr["status"], "passed")
            self.assertEqual(solr["tests"], 1)
            self.assertEqual(len(solr["wrapper_sha256"]), 64)

            # JUnit 4 counts an assumption skip as run=1, ignored=0.
            (trial / "junit.log").write_text(
                "MALLORY_TEST_ASSUMPTION 'awaitsfix' test group is disabled\n"
                "MALLORY_TEST_RESULT run=1 failures=0 ignored=0\n")
            skipped = collect_junit_receipt(
                trial, ["python3", "run_pilot.py"], trial, 1, None)
            self.assertEqual(skipped["status"], "no_tests")
            self.assertEqual(skipped["assumption_failures"], 1)

            (trial / "junit.log").write_text(
                "MALLORY_TEST_RESULT run=0 failures=0 ignored=1\n")
            (trial / "pilot-result.json").write_text(json.dumps(
                {"junit": {"run": 0, "failures": 0, "ignored": 1}}))
            ignored = collect_junit_receipt(
                trial, ["python3", "run_pilot.py"], trial, 1, None)
            self.assertEqual(ignored["status"], "no_tests")
            self.assertEqual(ignored["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
