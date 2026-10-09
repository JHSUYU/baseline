"""Regression for the incomplete JSONL tail seen in SOLR-13 trial 9."""

import gzip
from pathlib import Path
import tempfile
import unittest

from campaign import TraceIncomplete, events


class TraceIntegrityTest(unittest.TestCase):
    def test_partial_last_record_is_never_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'events.jsonl'
            trace.write_bytes(b'{"event":"IO_OBSERVED","seq":1}\n'
                              b'{"event":"IO_OBSERVED","seq":2,"siteId":"org.apac')
            with self.assertRaisesRegex(TraceIncomplete, 'final JSONL record'):
                events(trace)
            archived = Path(str(trace) + '.gz')
            with gzip.open(archived, 'wb') as output:
                output.write(trace.read_bytes())
            trace.unlink()
            with self.assertRaisesRegex(TraceIncomplete, 'final JSONL record'):
                events(trace)

    def test_complete_trace_parses_after_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'events.jsonl'
            trace.write_bytes(b'{"event":"IO_OBSERVED","seq":1}\n'
                              b'{"event":"SUMMARY","seq":2,"detail":"applied=1/1"}\n')
            self.assertEqual(['IO_OBSERVED', 'SUMMARY'],
                             [row['event'] for row in events(trace)])


if __name__ == '__main__':
    unittest.main()
