"""The healthy trace pin must survive scanning later fault trials."""

import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("zk13_case_runner", HERE / "run.py")
RUNNER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUNNER)


class TraceLedgerTest(unittest.TestCase):
    def test_healthy_trace_pin_is_not_last_fault_trace(self):
        with tempfile.TemporaryDirectory(prefix="zk13-trace-ledger-") as directory:
            attempt = Path(directory)
            (attempt / "trials/r0000").mkdir(parents=True)
            (attempt / "trials/r0001").mkdir()
            (attempt / "result.json").write_text(json.dumps({
                "status": "queue_exhausted", "fault_trials_completed": 1,
                "healthy_seed_valid": True, "runtime_attestation": {"valid": True},
            }))
            (attempt / "driver-exit.json").write_text('{"exit_code":0}')
            digests = []
            for index, lines in enumerate(([{"type": "TARGET_CHECK", "site": next(iter(RUNNER.CONFIG_TARGET_CHECKS)),
                                             "node": "zk1", "outcome": "TAKEN"}],
                                            [{"type": "DOOR", "site": "fault-door", "node": "zk1"}])):
                trial_dir = attempt / "trials" / f"r{index:04d}"
                trace = trial_dir / "events.jsonl.gz"
                with gzip.open(trace, "wt", encoding="utf-8") as stream:
                    for event in lines:
                        stream.write(json.dumps(event) + "\n")
                digest = RUNNER.sha(trace)
                digests.append(digest)
                (trial_dir / "result.json").write_text(json.dumps({
                    "events_evidence": {"gzip_path": trace.name, "gzip_sha256": digest},
                    "junit_validation": {"status": "passed"},
                    "feedback": {"status": "observed"},
                }))
            self.assertNotEqual(*digests)
            row = RUNNER.evidence_row(attempt)
            self.assertEqual(row["healthy_trace_sha256"], digests[0])
            self.assertEqual(row["trials"][1]["trace_sha256"], digests[1])


if __name__ == "__main__":
    unittest.main()
