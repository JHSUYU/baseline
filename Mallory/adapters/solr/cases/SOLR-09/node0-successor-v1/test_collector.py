"""Offline SHA and fail-closed receiver tests; no JVM or SSH."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


collector = module('solr09_node0_collector', 'collect_offhost.py')
receiver = module('solr09_node2_receiver', 'remote_finalize.py')


class CollectorTest(unittest.TestCase):
    def test_manifest_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'result.json').write_text('{}')
            self.assertIn('result.json', collector.files_under(root))
            (root / 'link').symlink_to(root / 'result.json')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                collector.files_under(root)

    def test_receiver_rejects_changed_member_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            receiver.PARENT = parent
            receiver.TEMP = parent / '.SOLR-09.tmp'
            receiver.FINAL = parent / 'SOLR-09'
            receiver.TEMP.mkdir()
            result = receiver.TEMP / 'result.json'
            result.write_text('{"status":"queue_exhausted"}')
            files = receiver.files_under(receiver.TEMP)
            manifest = {'schema_version': 1, 'case_id': 'SOLR-09',
                        'status': 'queue_exhausted',
                        'result_sha256': files['result.json']['sha256'],
                        'files': files}
            changed = json.loads(json.dumps(manifest))
            changed['files']['result.json']['sha256'] = '0' * 64
            with self.assertRaises(ValueError):
                receiver.finalize(changed)
            first = receiver.finalize(manifest)
            self.assertEqual(first, receiver.finalize(manifest))
            self.assertTrue(receiver.FINAL.is_dir())

    def test_campaign_reformatted_config_keeps_exact_semantic_identity(self):
        original = collector.SOURCE
        try:
            with tempfile.TemporaryDirectory() as temp:
                collector.SOURCE = Path(temp)
                staged = json.loads((HERE / 'config-full-node0.json').read_text())
                (collector.SOURCE / 'config.json').write_text(json.dumps(staged, sort_keys=True))
                (collector.SOURCE / 'result.json').write_text(json.dumps({
                    'case_id': 'SOLR-09', 'status': 'queue_exhausted',
                    'calibration_only': False, 'fault_trials_completed': 0}))
                self.assertIn('config.json', collector.terminal_manifest()['files'])
                staged['case_id'] = 'OTHER'
                (collector.SOURCE / 'config.json').write_text(json.dumps(staged))
                with self.assertRaisesRegex(ValueError, 'config identity'):
                    collector.terminal_manifest()
        finally:
            collector.SOURCE = original


if __name__ == '__main__':
    unittest.main()
