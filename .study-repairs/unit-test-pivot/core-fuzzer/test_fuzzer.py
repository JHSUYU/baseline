import json
import sys
import tempfile
import unittest
from pathlib import Path

from fuzzer import (campaign, fingerprint, point_from_event, strict_injection,
                    trace_feedback, validate)

TARGET = '<example.Target: void check()>'
SITE = TARGET + '#u8'
A = {'marker': 'FAULT:TEST:REQUEST',
     'siteId': '<example.Transport: void receive()>#u2',
     'occurrence': 'node/request/io-1', 'hitOrdinal': 1}
B = {'marker': 'FAULT:TEST:RECOVERY',
     'siteId': '<example.Recovery: void read()>#u3',
     'occurrence': 'node/recovery/io-1', 'hitOrdinal': 1}


def jsonl(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(event) + '\n' for event in events))


def marker(point, event, seq, **extra):
    return {'schemaVersion': 3, 'event': event, 'seq': seq,
            'marker': point['marker'], 'siteId': point['siteId'],
            'occurrenceAddress': point['occurrence'],
            'hitOrdinal': point['hitOrdinal'], **extra}


RUNNER = r'''
import json, os
from pathlib import Path
trial = json.loads(Path(os.environ['CAUSYNTH_FAULT_TRIAL']).read_text())
trace = Path(os.environ['CAUSYNTH_TRACE_OUTPUT_DIR']) / 'runtime_trace.jsonl'
trace.parent.mkdir(parents=True, exist_ok=True)
mode = os.environ.get('MODE', 'normal')
attempt = int(os.environ.get('ATTEMPT', '1'))
rows = []
seq = 0
if mode == 'pre_target':
    rows.extend([
        {'schemaVersion':3,'event':'METHOD_ENTER','seq':1,
         'method':TARGET,'callId':10},
        {'schemaVersion':3,'event':'BRANCH','seq':2,
         'method':TARGET,'siteId':SITE,'callId':10,'outcome':False}])
    seq = 2
for point in trial['faults']:
    identity = {k:point[k] for k in ('marker','siteId','hitOrdinal')}
    identity['occurrenceAddress'] = point['occurrence']
    seq += 1
    rows.append({'schemaVersion':3,'event':'FAULT_POINT_OBSERVED',
                 'seq':seq,**identity})
    if mode == 'unmatched' and attempt == 1:
        break
    seq += 1
    rows.append({'schemaVersion':3,'event':'FAULT_MATCHED','seq':seq,
                 'faultId':point['faultId'],**identity})
    seq += 1
    rows.append({'schemaVersion':3,'event':'FAULT_APPLIED','seq':seq,
                 'faultId':point['faultId'],**identity})
if len(trial['faults']) == 1:
    seq += 1
    rows.append({'schemaVersion':3,'event':'FAULT_POINT_OBSERVED','seq':seq,
                 'marker':B['marker'],'siteId':B['siteId'],
                 'occurrenceAddress':B['occurrence'],
                 'hitOrdinal':B['hitOrdinal']})
if mode not in ('lost', 'pre_target'):
    seq += 1
    rows.append({'schemaVersion':3,'event':'METHOD_ENTER','seq':seq,
                 'method':'<example.Recovery: void run()>','callId':20})
    seq += 1
    rows.append({'schemaVersion':3,'event':'METHOD_ENTER','seq':seq,
                 'method':TARGET,'callId':10})
    seq += 1
    rows.append({'schemaVersion':3,'event':'BRANCH','seq':seq,
                 'method':TARGET,'siteId':SITE,'callId':10,'outcome':True})
    seq += 1
    rows.append({'schemaVersion':3,'event':'METHOD_EXIT_THROW','seq':seq,
                 'method':TARGET,'callId':10,
                 'runtimeType':'example.TargetException'})
trace.write_text(''.join(json.dumps(row)+'\n' for row in rows))
'''


def fixture(root, *, mode='normal', max_trials=2, max_faults=2):
    work = root / 'system'
    temp = root / 'tmp'
    work.mkdir()
    temp.mkdir()
    seed = root / 'seed.jsonl'
    jsonl(seed, [marker(A, 'FAULT_POINT_OBSERVED', 1),
                 {'schemaVersion': 3, 'event': 'METHOD_ENTER', 'seq': 2,
                  'method': TARGET, 'callId': 10},
                 {'schemaVersion': 3, 'event': 'BRANCH', 'seq': 3,
                  'method': TARGET, 'callId': 10, 'siteId': SITE,
                  'outcome': False}])
    runner = root / 'runner.py'
    runner.write_text('TARGET=' + repr(TARGET) + '\nSITE=' + repr(SITE) +
                      '\nB=' + repr(B) + '\n' + RUNNER)
    return {'case_id': 'CHECK-01', 'system': 'example',
            'test_class': 'example.OriginalClusterTest',
            'test_method': 'testOriginal', 'cwd': str(work),
            'workspaces': {'system_test': str(work), 'temp': str(temp)},
            'target': {'method': TARGET, 'site_id': SITE,
                       'exception_type': 'example.TargetException'},
            'seed': {'trace': str(seed), 'elapsed_seconds': 1.0},
            'trial': {'command': [sys.executable, str(runner)],
                      'env': {'MODE': mode, 'ATTEMPT': '{attempt}'}},
            'budget': {'max_trials': max_trials, 'max_faults': max_faults,
                       'max_unmatched_retries': 1},
            'timeout_seconds': 10}


class CoverageIoTest(unittest.TestCase):
    def test_alternative_final_guards_require_exact_post_fault_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = TARGET + '#u34', TARGET + '#u43'
            target = {
                'method': TARGET,
                'exception_type': 'example.TargetException',
                'fatal_guard_paths': [
                    [{'siteId': first, 'outcome': True}],
                    [{'siteId': second, 'outcome': True}],
                ],
            }
            base = [
                {'event': 'METHOD_ENTER', 'seq': 1, 'method': TARGET,
                 'callId': 10},
                {'event': 'BRANCH', 'seq': 2, 'method': TARGET,
                 'callId': 10, 'siteId': first, 'outcome': False},
                marker(A, 'FAULT_APPLIED', 3, faultId=fingerprint(A)),
            ]
            unrelated_throw = base + [
                {'event': 'METHOD_EXIT_THROW', 'seq': 4,
                 'method': TARGET, 'callId': 10,
                 'runtimeType': 'example.TargetException'},
            ]
            path = root / 'trace.jsonl'
            jsonl(path, unrelated_throw)
            feedback = trace_feedback(path, target)
            self.assertFalse(feedback['target_reached_after_fault'])
            self.assertFalse(feedback['oracle'])

            reached = base + [
                {'event': 'BRANCH', 'seq': 4, 'method': TARGET,
                 'callId': 10, 'siteId': second, 'outcome': True},
                {'event': 'METHOD_EXIT_THROW', 'seq': 5,
                 'method': TARGET, 'callId': 10,
                 'runtimeType': 'example.TargetException'},
            ]
            jsonl(path, reached)
            feedback = trace_feedback(path, target)
            self.assertTrue(feedback['target_reached_after_fault'])
            self.assertTrue(feedback['oracle'])
            self.assertEqual(feedback['target_outcomes_after_fault'], [True])

            target['check_site_ids'] = [first, second]
            feedback = trace_feedback(path, target)
            self.assertTrue(feedback['target_reached_after_fault'])

    def test_runtime_occurrence_accepts_arbitrary_nonempty_identity(self):
        observed = marker(A, 'FAULT_POINT_OBSERVED', 1)
        self.assertEqual(point_from_event(observed), A)
        self.assertIsNone(point_from_event({**observed,
                                            'occurrenceAddress': '  '}))

    def test_call_site_check_and_typed_throw_differential(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, max_trials=1, max_faults=1)
            journal = '<example.Journal: void checkRequest()>'
            site = journal + '#u78'
            expected = 'java.lang.IllegalArgumentException'

            def call(seq, invocation, call_id):
                return [
                    {'schemaVersion': 3, 'event': 'METHOD_ENTER', 'seq': seq,
                     'method': journal, 'callId': call_id,
                     'occurrenceAddress': 'journal/request/check-1'},
                    {'schemaVersion': 3, 'event': 'CALL_SITE_ENTER',
                     'seq': seq + 1, 'method': journal, 'callId': 0,
                     'siteId': site, 'invocationId': invocation},
                    {'schemaVersion': 3, 'event': 'CALL_SITE_THROW',
                     'seq': seq + 2, 'method': journal, 'callId': 0,
                     'siteId': site, 'invocationId': invocation,
                     'runtimeType': ''},
                    {'schemaVersion': 3, 'event': 'METHOD_EXIT_THROW',
                     'seq': seq + 3, 'method': journal, 'callId': call_id,
                     'runtimeType': expected}]

            target = {'method': journal, 'site_id': site,
                      'occurrence': 'journal/request/check-1',
                      'throw_site_id': site,
                      'check_events': ['CALL_SITE_RETURN', 'CALL_SITE_THROW'],
                      'throw_event': 'CALL_SITE_THROW',
                      'exception_type': expected}
            config['target'] = target
            seed = Path(config['seed']['trace'])
            jsonl(seed, [marker(A, 'FAULT_POINT_OBSERVED', 1)] + call(2, 100, 10))
            trial_rows = (call(1, 101, 10) +
                          [marker(A, 'FAULT_POINT_OBSERVED', 5),
                           marker(A, 'FAULT_MATCHED', 6,
                                  faultId=fingerprint(A)),
                           marker(A, 'FAULT_APPLIED', 7,
                                  faultId=fingerprint(A))] +
                          call(8, 102, 11))
            # The first call precedes the fault; only the second validates
            # post-final-fault target reach. Both count for the healthy
            # differential, which therefore rises from one to two.
            runner = root / 'callsite_runner.py'
            runner.write_text(
                'import json, os\nfrom pathlib import Path\n'
                'rows = ' + repr(trial_rows) + '\n'
                'p = Path(os.environ["CAUSYNTH_TRACE_OUTPUT_DIR"]) / '
                '"runtime_trace.jsonl"\n'
                'p.parent.mkdir(parents=True, exist_ok=True)\n'
                'p.write_text("".join(json.dumps(e)+"\\n" for e in rows))\n')
            config['trial']['command'] = [sys.executable, str(runner)]
            state = campaign(config, root / 'out')
            result = json.loads(Path(state['completed'][0]['result']).read_text())
            self.assertEqual(result['status'], 'target_exception_candidate')
            self.assertEqual(result['baseline_target_fatal_exception_count'], 1)
            self.assertEqual(result['target_fatal_exception_count'], 2)
            self.assertEqual(result['target_outcomes_after_fault'],
                             ['CALL_SITE_THROW'])
            self.assertTrue(result['target_reached_after_fault'])
            self.assertTrue(result['strict_injection'])
            # A throw without its matching invocation is no target check.
            bad = root / 'unpaired.jsonl'
            invalid = json.loads(json.dumps(trial_rows))
            invalid[-2]['invocationId'] = 999
            jsonl(bad, invalid)
            feedback = trace_feedback(bad, target)
            self.assertFalse(feedback['target_reached_after_fault'])
            self.assertFalse(feedback['oracle'])
            returned = root / 'returned.jsonl'
            normal = json.loads(json.dumps(trial_rows))
            normal[-2]['event'] = 'CALL_SITE_RETURN'
            normal[-1]['event'] = 'METHOD_EXIT_NORMAL'
            normal[-1]['runtimeType'] = ''
            jsonl(returned, normal)
            feedback = trace_feedback(returned, target)
            self.assertTrue(feedback['target_reached_after_fault'])
            self.assertEqual(feedback['target_outcomes_after_fault'],
                             ['CALL_SITE_RETURN'])
            self.assertFalse(feedback['oracle'])

    def test_graph_free_seed_discovers_io_and_mutates_actual_sequence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            validate(config)
            state = campaign(config, root / 'out')
            self.assertEqual(len(state['completed']), 2)
            self.assertEqual([len(c['sequence']) for c in state['completed']],
                             [1, 2])
            self.assertEqual(state['completed'][1]['sequence'], [A, B])
            results = [json.loads(Path(c['result']).read_text())
                       for c in state['completed']]
            self.assertTrue(all(r['strict_injection'] for r in results))
            self.assertEqual(results[0]['new_io_count'], 1)
            self.assertGreater(results[0]['new_coverage_count'], 0)
            self.assertEqual(results[1]['applied_fault_ids'],
                             [fingerprint(A), fingerprint(B)])
            self.assertEqual(results[0]['target_outcomes_after_fault'], [True])
            self.assertTrue(results[0]['target_outcome_changed'])
            summary = json.loads((root / 'out/CHECK-01/result.json').read_text())
            self.assertEqual(summary['status'], 'candidate_review')
            self.assertEqual(summary['bug_mark'], 'candidate')
            self.assertEqual(summary['io_family_gain'], 1)
            self.assertEqual(summary['target_outcome_changed_trials'], 2)
            self.assertEqual(summary['aggregate_seconds'] if
                             'aggregate_seconds' in summary else 0, 0)
            self.assertFalse(list((root / 'out').rglob('*plan*')))
            again = campaign(config, root / 'out')
            self.assertEqual(again['completed'], state['completed'])

    def test_lost_target_discards_feedback_and_descendants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, mode='lost')
            state = campaign(config, root / 'out')
            result = json.loads(Path(state['completed'][0]['result']).read_text())
            self.assertEqual(result['status'], 'lost_target')
            self.assertEqual(result['new_io_count'], 0)
            self.assertEqual(state['queue'], [])
            self.assertEqual(len(state['io_families']), 1)

    def test_unmatched_retry_is_bounded_and_resume_keeps_one_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, mode='unmatched', max_trials=1)
            state = campaign(config, root / 'out')
            self.assertEqual(len(state['completed']), 1)
            result = json.loads(Path(state['completed'][0]['result']).read_text())
            self.assertEqual(result['attempt'], 2)
            self.assertTrue(result['strict_injection'])
            self.assertEqual(len(list((root / 'out/CHECK-01/trials').glob(
                '*/attempt-*/result.json'))), 2)
            self.assertEqual(len(campaign(config, root / 'out')['completed']), 1)

    def test_budget_depth_expansion_uses_saved_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, max_trials=1, max_faults=1)
            first = campaign(config, root / 'out')
            self.assertEqual(len(first['completed']), 1)
            self.assertEqual(first['queue'], [])
            config['budget']['max_trials'] = 2
            config['budget']['max_faults'] = 2
            resumed = campaign(config, root / 'out')
            self.assertEqual(len(resumed['completed']), 2)
            self.assertEqual(resumed['completed'][1]['sequence'], [A, B])
            self.assertEqual(resumed['completed'][0]['result'],
                             first['completed'][0]['result'])

    def test_default_budget_is_48_trials_and_four_faults(self):
        with tempfile.TemporaryDirectory() as temp:
            config = fixture(Path(temp))
            config['budget'] = {}
            validate(config)
            self.assertEqual(config['budget']['max_trials'], 48)
            self.assertEqual(config['budget']['max_faults'], 4)

    def test_exact_selector_and_target_check_after_final_fault(self):
        point = dict(A)
        applied = {'matched_count': 1, 'applied_count': 1,
                   'applied_points': [point],
                   'applied_fault_ids': [fingerprint(point)]}
        self.assertTrue(strict_injection(applied, [point]))
        self.assertFalse(strict_injection({**applied, 'applied_points': [B]},
                                          [point]))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, mode='pre_target', max_trials=1)
            state = campaign(config, root / 'out')
            result = json.loads(Path(state['completed'][0]['result']).read_text())
            self.assertTrue(result['target_reached'])
            self.assertFalse(result['target_reached_after_fault'])
            self.assertEqual(result['status'], 'lost_target')

    def test_coarse_io_scope_filters_without_changing_exact_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, max_trials=1)
            config['io_scope'] = {'marker_prefixes': ['FAULT:TEST:REQUEST']}
            state = campaign(config, root / 'out')
            result = json.loads(Path(state['completed'][0]['result']).read_text())
            self.assertEqual(result['new_io_count'], 0)
            self.assertEqual(state['queue'], [])
            self.assertEqual(state['completed'][0]['sequence'], [A])


if __name__ == '__main__':
    unittest.main()
