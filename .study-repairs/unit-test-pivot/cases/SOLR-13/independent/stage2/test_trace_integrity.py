"""Ensure stage two never credits a JVM with an incomplete trace."""

import gzip
from pathlib import Path
import tempfile
import unittest

from campaign import TraceIncomplete, events


class TraceIntegrityTest(unittest.TestCase):
    def test_truncated_jsonl_is_incomplete_even_after_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'events.jsonl'
            trace.write_bytes(b'{"event":"IO_OBSERVED","seq":1}\n'
                              b'{"event":"IO_OBSERVED","seq":2,"siteId":"org.apac')
            with self.assertRaises(TraceIncomplete):
                events(trace)
            with gzip.open(str(trace) + '.gz', 'wb') as archive:
                archive.write(trace.read_bytes())
            trace.unlink()
            with self.assertRaises(TraceIncomplete):
                events(trace)

    def test_complete_retry_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'events.jsonl'
            trace.write_bytes(b'{"event":"IO_OBSERVED","seq":1}\n'
                              b'{"event":"SUMMARY","seq":2,"detail":"applied=1/1"}\n')
            self.assertEqual('SUMMARY', events(trace)[-1]['event'])


if __name__ == '__main__':
    unittest.main()
