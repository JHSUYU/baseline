import tempfile
import fcntl
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import rerun102_worker


class ExceptionResolutionTest(unittest.TestCase):
    def resolve(self, source, check, line):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = Path('src/Target.java')
            path = root / rerun102_worker.SOURCE_DIR['HDFS'] / relative
            path.parent.mkdir(parents=True)
            path.write_text(source)
            row = {'system': 'HDFS 3.4.3', 'check_code': check,
                   'exact_check_location': {'file': str(relative),
                                            'selected_line': line}}
            with patch.object(rerun102_worker, 'SOURCE_ROOT', root):
                return rerun102_worker.exception_type(row)

    def test_java_lang_exception_stays_in_java_lang(self):
        source = 'package example;\nclass Target { void check() {\nthrow new AssertionError();\n}}\n'
        self.assertEqual(self.resolve(source, 'throw new AssertionError();', 3),
                         'java.lang.AssertionError')

    def test_nested_import_and_rethrow_use_binary_class_name(self):
        source = ('package example;\n'
                  'import org.apache.zookeeper.KeeperException.SessionExpiredException;\n'
                  'class Target { void check() {\n'
                  'try { throw new SessionExpiredException(); }\n'
                  'catch (SessionExpiredException e) {\n'
                  'if (true) throw e;\n}}}\n')
        expected = 'org.apache.zookeeper.KeeperException$SessionExpiredException'
        self.assertEqual(self.resolve(source, 'throw new SessionExpiredException();', 4),
                         expected)
        self.assertEqual(self.resolve(source, 'if (true) throw e;', 6), expected)

    def test_inherited_nested_exception_uses_superclass(self):
        source = ('package example;\n'
                  'import org.apache.hadoop.security.token.SecretManager;\n'
                  'class Target extends SecretManager<String> {\n'
                  'void check() throws InvalidToken {\n'
                  'throw new InvalidToken("missing");\n}}\n')
        self.assertEqual(self.resolve(source, 'throw new InvalidToken("missing");', 5),
                         'org.apache.hadoop.security.token.SecretManager$InvalidToken')

    def test_nonthrowing_state_guard_has_no_direct_exception_oracle(self):
        source = ('package example;\nclass Target { boolean check() {\n'
                  'if (key == null) key = refresh();\nreturn key != null;\n}}\n')
        self.assertIsNone(self.resolve(source,
                                       'if (key == null) key = refresh();', 3))

    def test_unfinished_case_pins_its_static_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            artifact = base / 'soot-selection.json'
            artifact.write_text(json.dumps({'target_method': '<T: void check()>',
                                            'input_digest': 'digest-a'}))
            checkpoint = base / 'campaign-old/CHECK-01/state.json'
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text(json.dumps({'static_selection_digest': 'digest-a',
                                              'seed': {'trace': 'healthy'},
                                              'completed': []}))
            self.assertEqual(rerun102_worker.live_selection_artifact(
                base, 'CHECK-01', '<T: void check()>'), artifact)
            self.assertIsNone(rerun102_worker.live_selection_artifact(
                base, 'CHECK-01', '<Other: void check()>'))

    def test_expanded_selection_is_pinned_before_initial_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            initial = base / 'soot-selection.json'
            initial.write_text(json.dumps({'target_method': '<T: void check()>',
                                           'input_digest': 'initial'}))
            expanded = base / 'caller-expanded/soot-selection.json'
            expanded.parent.mkdir()
            expanded.write_text(json.dumps({'target_method': '<T: void check()>',
                                            'input_digest': 'expanded',
                                            'selection_profile': 'caller_expanded'}))
            for name, digest in (('campaign', 'initial'),
                                 ('campaign-expanded', 'expanded')):
                checkpoint = base / name / 'CHECK-01/state.json'
                checkpoint.parent.mkdir(parents=True)
                checkpoint.write_text(json.dumps({'static_selection_digest': digest,
                                                  'seed': {'trace': 'healthy'},
                                                  'completed': []}))
            self.assertEqual(rerun102_worker.live_selection_artifact(
                base, 'CHECK-01', '<T: void check()>'), expanded)

    def test_wide_selection_is_pinned_before_smaller_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            wide = base / 'caller-expanded-800/soot-selection.json'
            wide.parent.mkdir()
            wide.write_text(json.dumps({'target_method': '<T: void check()>',
                                        'input_digest': 'wide',
                                        'selection_profile': 'caller_expanded_800'}))
            checkpoint = base / 'campaign-wide/CHECK-01/state.json'
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text(json.dumps({'static_selection_digest': 'wide',
                                              'seed': {'trace': 'healthy'},
                                              'completed': []}))
            self.assertEqual(rerun102_worker.live_selection_artifact(
                base, 'CHECK-01', '<T: void check()>'), wide)
            self.assertEqual(rerun102_worker.healthy_dir(
                base, json.loads(wide.read_text())), base / 'healthy-800')
            self.assertEqual(rerun102_worker.healthy_dir(
                base, json.loads(wide.read_text()), 'nightly'),
                base / 'healthy-800-nightly')

    def test_fault_point_detection_uses_runtime_event(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'trace.jsonl'
            trace.write_text('{"event":"CHECK_REACHED"}\n')
            self.assertFalse(rerun102_worker.observed_fault_points(trace))
            point = {'schemaVersion': 3, 'event': 'FAULT_POINT_OBSERVED',
                     'marker': 'FAULT:IO', 'siteId': '<T: void call()>#u1',
                     'occurrenceAddress': 'actor/io/1', 'hitOrdinal': 1}
            trace.write_text(json.dumps({**point, 'identityGap': True}) + '\n')
            self.assertFalse(rerun102_worker.observed_fault_points(trace))
            trace.write_text(json.dumps({**point, 'identityGap': True}) + '\n' +
                             json.dumps(point) + '\n')
            self.assertTrue(rerun102_worker.observed_fault_points(trace))

    def test_failed_healthy_junit_is_retained_and_retried_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'healthy'
            output.mkdir()
            log = root / 'healthy-run.log'
            attempts = []

            def run(_argv, path):
                attempts.append(len(attempts) + 1)
                path.write_text(f'runner attempt {attempts[-1]}')
                (output / 'junit.log').write_text(f'JUnit attempt {attempts[-1]}')
                return 1 if attempts[-1] == 1 else 0

            with patch.object(rerun102_worker, 'run_logged', side_effect=run):
                self.assertEqual(rerun102_worker.run_healthy_with_retry(
                    ['runner'], log, output), 0)
            self.assertEqual(attempts, [1, 2])
            self.assertEqual((root / 'healthy-run-failed-1.log').read_text(),
                             'runner attempt 1')
            self.assertEqual((output / 'junit.log.failed-1').read_text(),
                             'JUnit attempt 1')
            self.assertEqual(log.read_text(), 'runner attempt 2')

    def test_parallel_claim_preserves_running_case_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'HDFS-01'
            base.mkdir()
            summary = {'case_id': 'HDFS-01', 'system': 'HDFS 3.4.3',
                       'status': 'fuzzing', 'finished': False}
            (base / 'case-summary.json').write_text(json.dumps(summary))
            with (base / '.run-case.lock').open('a+') as claim:
                fcntl.flock(claim, fcntl.LOCK_EX | fcntl.LOCK_NB)
                observed = rerun102_worker.run_case(
                    {'case_id': 'HDFS-01', 'system': 'HDFS 3.4.3'}, root, 80, 10)
            self.assertEqual(observed, summary)
            self.assertEqual(json.loads((base / 'case-summary.json').read_text()),
                             summary)

    def test_finished_queue_exhaustion_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'HDFS-01'
            base.mkdir()
            summary = {'case_id': 'HDFS-01', 'system': 'HDFS 3.4.3',
                       'status': 'no_valid_target_trial', 'finished': True,
                       'fault_trials': 7}
            (base / 'case-summary.json').write_text(json.dumps(summary))
            observed = rerun102_worker.run_case(
                {'case_id': 'HDFS-01', 'system': 'HDFS 3.4.3'}, root, 80, 10)
            self.assertEqual(observed, summary)


if __name__ == '__main__':
    unittest.main()
