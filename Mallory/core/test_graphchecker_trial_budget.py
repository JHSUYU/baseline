import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.core.graphchecker_trial import analyze_trial


class GraphBuilderBudgetTest(unittest.TestCase):
    def test_large_trace_builder_has_bounded_heap_and_sufficient_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = Path(temp)
            (trial / "graphchecker-trace.jsonl").write_text("{}\n")
            jar = trial / "graph.jar"
            jar.write_bytes(b"fixture")
            observed = {}

            def fake_run(command, **options):
                observed["command"] = command
                observed["timeout"] = options["timeout"]
                (trial / "graphchecker-feedback.json").write_text(json.dumps({
                    "schemaVersion": 1, "targetSite": "target"}))

            with patch("Mallory.core.graphchecker_trial.subprocess.run",
                       side_effect=fake_run):
                analyze_trial(trial, "target", jar=jar)
            self.assertEqual("-Xmx6g", observed["command"][1])
            self.assertEqual(300, observed["timeout"])


if __name__ == "__main__":
    unittest.main()
