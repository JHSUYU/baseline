"""Exact prior-trace and versioned healthy-summary feedback equivalence."""

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from .graphchecker_trial import analyze_trial, runtime_jar


def row(**fields):
    return json.dumps(fields, separators=(",", ":")) + "\n"


class HealthySummaryTest(unittest.TestCase):
    @unittest.skipUnless(runtime_jar().is_file(), "build graphchecker-runtime first")
    def test_cached_healthy_summary_equals_full_prior_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            healthy = (row(kind="ACTIVATION", occurrenceId="old", node="server",
                           regionId="R.old", seq=1)
                       + row(kind="COVERAGE", occurrenceId="old", siteId="old-before",
                             seq=2)
                       + row(kind="TARGET_CHECK", occurrenceId="old", siteId="T",
                             outcome="FALSE", seq=3)
                       + row(kind="COVERAGE", occurrenceId="old", siteId="old-later",
                             seq=4))
            faulted = (row(kind="ACTIVATION", occurrenceId="old", node="server",
                           regionId="R.old", seq=1)
                       + row(kind="COVERAGE", occurrenceId="old", siteId="old-before",
                             seq=2)
                       + row(kind="WRITE", occurrenceId="old", writerEndpointId="w",
                             locationVersion="key@1", seq=4)
                       + row(kind="ACTIVATION", occurrenceId="new", node="server",
                             regionId="R.new", seq=5)
                       + row(kind="READ", occurrenceId="new", readerEndpointId="r",
                             writerEndpointId="w", writerOccurrenceId="old",
                             locationVersion="key@1", seq=6)
                       + row(kind="COVERAGE", occurrenceId="new", siteId="new-branch",
                             seq=7)
                       + row(kind="TARGET_CHECK", occurrenceId="new", siteId="T",
                             outcome="TRUE", seq=8))
            plain = root / "healthy.jsonl"
            packed = root / "healthy.jsonl.gz"
            plain.write_text(healthy, encoding="utf-8")
            with gzip.open(packed, "wb") as stream:
                stream.write(healthy.encode("utf-8"))
            full_trial = root / "full"
            cached_trial = root / "cached"
            repeat_trial = root / "repeat"
            for trial in (full_trial, cached_trial, repeat_trial):
                trial.mkdir()
                (trial / "graphchecker-trace.jsonl").write_text(faulted,
                                                                 encoding="utf-8")
            full = analyze_trial(full_trial, "T", prior_trace=plain,
                                 jar=runtime_jar())
            cached = analyze_trial(cached_trial, "T", prior_trace=packed,
                                   jar=runtime_jar())
            self.assertEqual(full, cached)
            self.assertEqual(full["newClosureNodes"], cached["newClosureNodes"])
            self.assertEqual(full["newClosureEdges"], cached["newClosureEdges"])
            self.assertEqual(full["newClosureCoverageSites"],
                             cached["newClosureCoverageSites"])
            files = list(root.glob("healthy.jsonl.gz.*.summary.json"))
            self.assertEqual(1, len(files))
            version = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(1, version["summaryVersion"])
            self.assertEqual(["T"], version["targetSites"])
            self.assertEqual(cached, analyze_trial(repeat_trial, "T",
                                                   prior_trace=packed,
                                                   jar=runtime_jar()))
            self.assertEqual(version, json.loads(files[0].read_text(encoding="utf-8")))
            version["summarySha256"] = "0" * 64
            files[0].write_text(json.dumps(version), encoding="utf-8")
            repaired_trial = root / "repaired"
            repaired_trial.mkdir()
            (repaired_trial / "graphchecker-trace.jsonl").write_text(
                faulted, encoding="utf-8")
            self.assertEqual(full, analyze_trial(repaired_trial, "T",
                                                 prior_trace=packed,
                                                 jar=runtime_jar()))
            self.assertNotEqual("0" * 64,
                                json.loads(files[0].read_text(encoding="utf-8"))
                                ["summarySha256"])
            old_trace_sha = json.loads(files[0].read_text(encoding="utf-8"))[
                "priorTraceSha256"]
            with gzip.open(packed, "wb") as stream:
                stream.write((healthy + "\n").encode("utf-8"))
            changed_trial = root / "changed-trace"
            changed_trial.mkdir()
            (changed_trial / "graphchecker-trace.jsonl").write_text(
                faulted, encoding="utf-8")
            self.assertEqual(full, analyze_trial(changed_trial, "T",
                                                 prior_trace=packed,
                                                 jar=runtime_jar()))
            self.assertNotEqual(old_trace_sha,
                                json.loads(files[0].read_text(encoding="utf-8"))
                                ["priorTraceSha256"])


if __name__ == "__main__":
    unittest.main()
