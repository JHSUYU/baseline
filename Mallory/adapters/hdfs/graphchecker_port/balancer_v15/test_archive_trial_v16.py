"""The raw archive gate is scoped to its own campaign JVM."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from .archive_trial_v16 import _campaign_java_running


class ArchiveJavaScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.raw = self.root / "raw"
        self.other = self.root / "solr"
        self.proc = self.root / "proc"
        for path in (self.output, self.raw, self.other, self.proc):
            path.mkdir()

    def process(self, number: int, command: list[str], *,
                comm: str = "java", cwd: Path | None = None) -> Path:
        path = self.proc / str(number)
        path.mkdir()
        (path / "comm").write_text(comm + "\n")
        (path / "cmdline").write_bytes(b"\0".join(item.encode() for item in command) + b"\0")
        (path / "fd").mkdir()
        os.symlink(cwd or self.other, path / "cwd")
        return path

    def test_unrelated_java_does_not_block(self) -> None:
        self.process(10, ["java", "-cp", str(self.other / "solr.jar")])
        self.assertFalse(_campaign_java_running(self.output, self.raw, self.proc))

    def test_own_java_command_blocks(self) -> None:
        self.process(10, ["java", "--trace-dir", str(self.raw / "r0007/trace")])
        self.assertTrue(_campaign_java_running(self.output, self.raw, self.proc))

    def test_own_java_open_file_blocks(self) -> None:
        process = self.process(10, ["java", "Main"])
        trace = self.raw / "runtime_trace.jsonl"
        trace.write_text("row\n")
        os.symlink(trace, process / "fd/3")
        self.assertTrue(_campaign_java_running(self.output, self.raw, self.proc))

    def test_non_java_command_is_ignored(self) -> None:
        self.process(10, ["python", str(self.raw / "trace")], comm="python")
        self.assertFalse(_campaign_java_running(self.output, self.raw, self.proc))


if __name__ == "__main__":
    unittest.main()
