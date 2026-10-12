import hashlib
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fuzzer import (archive_trial_attempts, budget_has_room, campaign,
                    choose_next_sequence, fault_family, fault_point_for_io,
                    fault_variants_for_io, fingerprint,
                    in_io_scope, point_from_event,
                    rows, static_reason_priority, strict_injection,
                    trace_feedback, stable_occurrence,
                    selected_target_throw_lines, validate,
                    write_case_result, write_trial)

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
import hashlib, json, os
from pathlib import Path
trial = json.loads(Path(os.environ['CAUSYNTH_FAULT_TRIAL']).read_text())
trace = Path(os.environ['CAUSYNTH_TRACE_OUTPUT_DIR']) / 'runtime_trace.jsonl'
trace.parent.mkdir(parents=True, exist_ok=True)
mode = os.environ.get('MODE', 'normal')
attempt = int(os.environ.get('ATTEMPT', '1'))
if os.environ.get('STATE_SNAPSHOT'):
    state = json.loads(Path(os.environ['CASE_STATE']).read_text())
    Path(os.environ['STATE_SNAPSHOT']).write_text(json.dumps({
        'finished': state.get('finished'), 'status': state.get('status')}))
rows = []
seq = 0
if os.environ.get('CRASHFUZZ_STATIC_SELECTION'):
    artifact = Path(os.environ['CRASHFUZZ_STATIC_SELECTION'])
    selected = json.loads(artifact.read_text())
    digest = selected.get('input_digest') or hashlib.sha256(artifact.read_bytes()).hexdigest()
    rows.append({'schemaVersion':3,'event':'STATIC_SELECTION_APPLIED',
                 'seq':0,'digest':digest})
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
    def test_post_call_phase_has_distinct_replay_identity(self):
        before = point_from_event(marker(A, 'FAULT_POINT_OBSERVED', 1,
                                         phase='before'))
        after = point_from_event(marker(A, 'FAULT_POINT_OBSERVED', 2,
                                        phase='after'))
        self.assertEqual(before, A)
        self.assertEqual(after['phase'], 'after')
        self.assertNotEqual(fingerprint(before), fingerprint(after))
        self.assertNotEqual(fault_family(before), fault_family(after))
        self.assertIsNone(point_from_event(marker(A, 'FAULT_POINT_OBSERVED', 3,
                                                   phase='unknown')))
        applied = {'applied_count': 1, 'matched_count': 1,
                   'applied_points': [after],
                   'applied_fault_ids': [fingerprint(after)]}
        self.assertTrue(strict_injection(applied, [after]))
        self.assertFalse(strict_injection(applied, [before]))
        explicit_before = {**before, 'phase': 'before'}
        before_applied = {'applied_count': 1, 'matched_count': 1,
                          'applied_points': [before],
                          'applied_fault_ids': [fingerprint(explicit_before)]}
        self.assertTrue(strict_injection(before_applied, [explicit_before]))
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory) / 'fault-trial.json'
            write_trial(trial, [before, after], {})
            faults = json.loads(trial.read_text())['faults']
            self.assertEqual([fault['phase'] for fault in faults],
                             ['before', 'after'])
            self.assertEqual(faults[0]['faultId'], fingerprint(before))

    def test_hbase_embedded_cluster_ports_keep_replayable_actor_identity(self):
        site = '/<example.RpcServer: void call()>#u5'
        first = ('local/hdfs://localhost:46863 RpcServer.port=45509 '
                 'ms1140:41175' + site)
        second = ('local/hdfs://localhost:38291 RpcServer.port=34170 '
                  'ms1140:33812' + site)
        self.assertEqual(stable_occurrence(first), stable_occurrence(second))

    def test_soot_controlled_throw_uses_line_not_unit_ordinal(self):
        guard = TARGET + '#u4'
        selection = {'target_check_line': 20, 'target_selected_line': 23,
                     'branches': [{'method': TARGET, 'line': 20,
                                   'site_id': guard}],
                     'target_throw_sites': [
                         {'method': TARGET, 'line': 23,
                          'soot_site_id': TARGET + '#u11',
                          'thrown_type': 'example.TargetException',
                          'controlled_by': [guard]},
                         {'method': TARGET, 'line': 23,
                          'soot_site_id': TARGET + '#u12',
                          'thrown_type': 'java.lang.Throwable',
                          'controlled_by': []}]}
        target = {'method': TARGET, 'site_id': TARGET + '#u11',
                  'exception_type': 'example.TargetException'}
        self.assertEqual(selected_target_throw_lines(selection, target), [23])

    def test_selected_explicit_throw_counts_even_if_caught_in_method(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.jsonl'
            target = {'method': TARGET, 'site_id': SITE,
                      'check_events': ['CHECK_REACHED'],
                      'throw_event': 'EXPLICIT_THROW',
                      'explicit_throw_lines': [23],
                      'exception_type': 'example.TargetException'}
            jsonl(path, [
                {'event': 'METHOD_ENTER', 'seq': 1,
                 'method': TARGET, 'callId': 7},
                marker(A, 'FAULT_APPLIED', 2, faultId=fingerprint(A)),
                {'event': 'CHECK_REACHED', 'seq': 3, 'method': TARGET,
                 'siteId': SITE, 'callId': 7},
                {'event': 'EXPLICIT_THROW', 'seq': 4, 'method': TARGET,
                 'siteId': TARGET + '#bytecode:throw:23:0',
                 'sourceLine': 23, 'callId': 7,
                 'runtimeType': 'example.TargetException'},
                {'event': 'METHOD_EXIT_NORMAL', 'seq': 5,
                 'method': TARGET, 'callId': 7},
            ])
            feedback = trace_feedback(path, target)
            self.assertTrue(feedback['oracle'])
            self.assertEqual(feedback['target_exception_count'], 1)
            target['explicit_throw_lines'] = [24]
            self.assertFalse(trace_feedback(path, target)['oracle'])

    def test_occurrence_ordinal_distinguishes_repeated_actor_site_events(self):
        first = marker(A, 'FAULT_POINT_OBSERVED', 1, occurrenceOrdinal=1)
        second = marker(A, 'FAULT_POINT_OBSERVED', 2, occurrenceOrdinal=2)
        first_point = point_from_event(first)
        second_point = point_from_event(second)
        self.assertNotEqual(fingerprint(first_point), fingerprint(second_point))
        self.assertEqual(first_point['occurrenceOrdinal'], 1)
        self.assertEqual(second_point['occurrenceOrdinal'], 2)
        self.assertIsNone(point_from_event({**second, 'occurrenceOrdinal': 0}))
        self.assertIsNone(point_from_event({**second, 'identityGap': True}))
        applied = {'applied_count': 1, 'matched_count': 1,
                   'applied_points': [second_point],
                   'applied_fault_ids': [fingerprint(second_point)]}
        self.assertTrue(strict_injection(applied, [second_point]))
        self.assertFalse(strict_injection(applied, [first_point]))

    def test_regenerated_dfs_client_id_keeps_block_receiver_replayable(self):
        site = '/<example.DataXceiver: void writeBlock()>#u257'
        first = ('local/DataXceiver for client DFSClient_NONMAPREDUCE_-529516321_1 '
                 'at /127.0.0.1:50820 [Receiving block '
                 'BP-1319269182-128.110.217.200-1791835652282:blk_1073741825_1001]' + site)
        second = ('local/DataXceiver for client DFSClient_NONMAPREDUCE_1383440130_1 '
                  'at /127.0.0.1:37998 [Receiving block '
                  'BP-1605120718-128.110.217.200-1791835769457:blk_1073741825_1001]' + site)
        self.assertEqual(stable_occurrence(first), stable_occurrence(second))

    def test_timeout_trace_ignores_only_incomplete_final_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runtime_trace.jsonl'
            path.write_text('{"event":"FAULT_APPLIED"}\n{"event":"METHOD_ENT')
            self.assertEqual(list(rows(path)), [{'event': 'FAULT_APPLIED'}])
            path.write_text('{"event":"FAULT_APPLIED"}\n{"event":"METHOD_ENT\n')
            with self.assertRaises(ValueError):
                list(rows(path))

    def test_transient_socket_and_block_ids_keep_replayable_actor_identity(self):
        site = '/<example.DataXceiver: void replaceBlock()>#u101'
        first = ('local/DataXceiver for client /127.0.0.1:49718 '
                 '[Replacing block BP-1810136525-128.110.217.200-1791840306052:'
                 'blk_1073741832_1008 from f5205531-0996-4a38-81d2-6488ad4a823f]' + site)
        second = ('local/DataXceiver for client /127.0.0.1:55540 '
                  '[Replacing block BP-1756035988-128.110.217.200-1791840317376:'
                  'blk_1073741837_1013 from 8046a21a-9288-410a-82aa-227cd5e73437]' + site)
        self.assertEqual(stable_occurrence(first), stable_occurrence(second))
        self.assertNotEqual(stable_occurrence(first),
                            stable_occurrence(second.replace('replaceBlock', 'writeBlock')))

    def test_static_exception_adds_a_typed_variant(self):
        typed = 'example.ProtocolIOException'
        variants = fault_variants_for_io(A, {A['siteId']: [typed]})
        self.assertEqual(variants, [A, {**A, 'exceptionClass': typed}])
        self.assertNotEqual(fault_family(variants[0]), fault_family(variants[1]))

    def test_post_call_fault_only_models_lost_transport_response(self):
        typed = 'example.CalleeRejectedIOException'
        after = {**A, 'phase': 'after', 'exceptionClass': typed}
        self.assertEqual(fault_variants_for_io(after, {A['siteId']: [typed]}),
                         [{**after, 'exceptionClass': 'java.io.IOException'}])
        zk = {**after, 'sourceKey':
              'org.apache.zookeeper.ZooKeeper: java.lang.String create()'}
        self.assertEqual(fault_variants_for_io(zk, {A['siteId']: [typed]}),
                         [{**zk, 'exceptionClass':
                           'org.apache.zookeeper.KeeperException$ConnectionLossException'}])

    def test_adaptive_budget_counts_target_retaining_trials(self):
        budget = {'max_trials': 240, 'base_trials': 80,
                  'min_target_retained_trials': 30}
        state = {'completed': [{'status': 'lost_target'}] * 79}
        self.assertTrue(budget_has_room(state, budget))
        state['completed'].append({'status': 'lost_target'})
        self.assertFalse(budget_has_room(state, budget))
        state['completed'][0] = {'status': 'checked'}
        self.assertTrue(budget_has_room(state, budget))
        state['completed'] = [{'status': 'checked'}] * 30 + [
            {'status': 'lost_target'}] * 50
        self.assertFalse(budget_has_room(state, budget))

    def test_every_third_trial_reserves_a_static_target_io(self):
        state = {'completed': [{'sequence': [A, B]}, {'sequence': [B, A]}],
                 'queue': [{'sequence': [B], 'priority': 1000, 'created': 1},
                           {'sequence': [A], 'priority': 1, 'created': 2}]}
        self.assertEqual(choose_next_sequence(state, {A['siteId']: 85}), 1)

    def test_zookeeper_fault_uses_connection_loss_and_exact_identity(self):
        observed = {**A, 'sourceKey':
                    '<org.apache.solr.common.cloud.SolrZkClient: byte[] getData(java.lang.String)>'}
        requested = fault_point_for_io(observed)
        self.assertEqual(requested['exceptionClass'],
                         'org.apache.zookeeper.KeeperException$ConnectionLossException')
        applied = marker(requested, 'FAULT_APPLIED', 1,
                         sourceKey=observed['sourceKey'],
                         exceptionClass=requested['exceptionClass'],
                         faultId=fingerprint(requested))
        self.assertTrue(strict_injection({
            'applied_count': 1, 'matched_count': 1,
            'applied_points': [point_from_event(applied)],
            'applied_fault_ids': [applied['faultId']]}, [requested]))
        self.assertEqual(fault_point_for_io(A), A)

    def test_static_selection_limits_runtime_feedback_to_preselected_sites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, max_trials=1, max_faults=2)
            artifact = root / 'selection.json'
            artifact.write_text(json.dumps({
                'schema_version': 1,
                'analysis_kind': 'crashfuzz_coarse_soot_selection',
                'target_method': TARGET,
                'coverage_methods': [TARGET, '<example.Transport: void receive()>'],
                'io_methods': ['<example.Transport: void receive()>'],
                'io_calls': [{'method': '<example.Transport: void receive()>',
                              'site_id': A['siteId'], 'callee':
                              '<java.io.InputStream: int read()>', 'line': 1,
                              'unit_index': 2}]}))
            config['static_selection'] = {'artifact': str(artifact)}
            seed_events = list(json.loads(line) for line in
                               Path(config['seed']['trace']).read_text().splitlines())
            seed_events.insert(0, {'schemaVersion': 3,
                                   'event': 'STATIC_SELECTION_APPLIED',
                                   'seq': 0,
                                   'digest': hashlib.sha256(artifact.read_bytes()).hexdigest()})
            jsonl(Path(config['seed']['trace']), seed_events)
            state = campaign(config, root / 'out')
            result = json.loads(Path(state['completed'][0]['result']).read_text())
            self.assertEqual(result['new_io_count'], 0)
            self.assertEqual(state['seed']['feedback']['points'], [A])
            self.assertEqual(state['queue'], [])
            self.assertTrue(state['static_selection_digest'])

    def test_io_scope_can_keep_a_specific_cross_node_source(self):
        mirror = {**A, 'sourceKey': 'DN->DN:writeBlock:bp1:blk7'}
        proxy = {**A, 'sourceKey': 'DN->DN:replaceBlock:bp1:blk7'}
        scope = {'marker_prefixes': ['FAULT:TEST:'],
                 'source_key_prefixes': ['DN->DN:writeBlock:']}
        self.assertTrue(in_io_scope(mirror, scope))
        self.assertFalse(in_io_scope(proxy, scope))
        self.assertFalse(in_io_scope(A, scope))
        self.assertTrue(in_io_scope(mirror, {'source_keys': [mirror['sourceKey']]}))
        self.assertFalse(in_io_scope(proxy, {'source_keys': [mirror['sourceKey']]}))

    def test_summary_counts_only_fully_applied_target_trials(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            partial = root / 'partial.json'
            complete = root / 'complete.json'
            partial.write_text(json.dumps({
                'status': 'unmatched', 'strict_injection': False,
                'target_reached_after_fault': True,
                'target_after_fault': True, 'oracle': True}))
            complete.write_text(json.dumps({
                'status': 'baseline_exception_recurrence',
                'strict_injection': True,
                'target_reached_after_fault': True,
                'target_after_fault': True, 'oracle': True}))
            state = {
                'case_id': 'CHECK-01', 'system': 'example',
                'test_class': 'example.OriginalClusterTest',
                'test_method': 'testOriginal',
                'seed': {'feedback': {'coverage': [], 'points': []}},
                'coverage': [], 'io_families': [],
                'completed': [
                    {'result': str(partial), 'sequence': [A, B]},
                    {'result': str(complete), 'sequence': [A]},
                ],
            }
            write_case_result(root, state)
            summary = json.loads((root / 'result.json').read_text())
            self.assertEqual(summary['strict_injections'], 1)
            self.assertEqual(summary['post_fault_target_reach_trials'], 1)
            self.assertEqual(summary['target_exception_after_fault_trials'], 1)

    def test_coverage_prefix_filters_runner_events(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trace.jsonl'
            jsonl(path, [
                {'event': 'METHOD_ENTER', 'seq': 1,
                 'method': '<runner.Harness: void run()>', 'callId': 1},
                {'event': 'BRANCH', 'seq': 2,
                 'method': '<runner.Harness: void run()>',
                 'siteId': '<runner.Harness: void run()>#u1',
                 'callId': 1, 'outcome': True},
                {'event': 'METHOD_ENTER', 'seq': 3,
                 'method': TARGET, 'callId': 2},
                {'event': 'BRANCH', 'seq': 4, 'method': TARGET,
                 'siteId': SITE, 'callId': 2, 'outcome': False},
            ])
            target = {'method': TARGET, 'site_id': SITE,
                      'exception_type': 'example.TargetException',
                      'coverage_include_prefixes': ['<example.']}
            feedback = trace_feedback(path, target)
            self.assertEqual(feedback['coverage'], [
                'BRANCH:' + SITE + ':False', 'METHOD:' + TARGET])

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
            self.assertEqual(summary['coverage_gain'], sum(
                summary['coverage_gain_by_kind'].values()))
            self.assertGreater(summary['coverage_gain_by_kind']['methods'], 0)
            self.assertGreater(summary['coverage_gain_by_kind']['branch_outcomes'], 0)
            self.assertEqual(summary['target_outcome_changed_trials'], 2)
            self.assertEqual(summary['aggregate_seconds'] if
                             'aggregate_seconds' in summary else 0, 0)
            self.assertFalse(list((root / 'out').rglob('*plan*')))
            again = campaign(config, root / 'out')
            self.assertEqual(again['completed'], state['completed'])

    def test_fault_can_expose_check_absent_from_healthy_seed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, max_trials=1)
            jsonl(Path(config['seed']['trace']),
                  [marker(A, 'FAULT_POINT_OBSERVED', 1)])
            state = campaign(config, root / 'out')
            self.assertFalse(state['seed']['target_reached'])
            self.assertEqual(len(state['completed']), 1)
            result = json.loads(Path(state['completed'][0]['result']).read_text())
            self.assertTrue(result['strict_injection'])
            self.assertTrue(result['target_reached_after_fault'])
            self.assertEqual(result['status'], 'target_exception_candidate')

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
            config['target']['exception_type'] = 'example.OtherException'
            config['archive_completed_trials'] = True
            state = campaign(config, root / 'out')
            self.assertEqual(len(state['completed']), 1)
            result = json.loads(Path(state['completed'][0]['result']).read_text())
            self.assertEqual(result['attempt'], 2)
            self.assertTrue(result['strict_injection'])
            self.assertEqual(len(list((root / 'out/CHECK-01/trials').glob(
                '*/attempt-*/result.json'))), 2)
            traces = sorted((root / 'out/CHECK-01/trials').glob(
                '*/attempt-*/trace/runtime_trace.jsonl.gz'))
            self.assertEqual(len(traces), 2)
            self.assertFalse(list((root / 'out/CHECK-01/trials').glob(
                '*/attempt-*/trace/runtime_trace.jsonl')))
            self.assertEqual(len(campaign(config, root / 'out')['completed']), 1)

    def test_budget_depth_expansion_uses_saved_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, max_trials=1, max_faults=1)
            snapshot = root / 'runner-state.json'
            config['trial']['env'].update({
                'CASE_STATE': '{case_dir}/state.json',
                'STATE_SNAPSHOT': str(snapshot),
            })
            first = campaign(config, root / 'out')
            self.assertEqual(len(first['completed']), 1)
            self.assertEqual(first['queue'], [])
            self.assertTrue(first['finished'])
            config['budget']['max_trials'] = 2
            config['budget']['max_faults'] = 2
            resumed = campaign(config, root / 'out')
            self.assertEqual(len(resumed['completed']), 2)
            self.assertEqual(resumed['completed'][1]['sequence'], [A, B])
            self.assertEqual(resumed['completed'][0]['result'],
                             first['completed'][0]['result'])
            self.assertEqual(json.loads(snapshot.read_text())['finished'], False)

    def test_default_budget_is_80_trials_and_eight_faults(self):
        with tempfile.TemporaryDirectory() as temp:
            config = fixture(Path(temp))
            config['budget'] = {}
            validate(config)
            self.assertEqual(config['budget']['max_trials'], 80)
            self.assertEqual(config['budget']['max_faults'], 8)

    def test_exact_selector_and_target_check_after_final_fault(self):
        point = dict(A)
        applied = {'matched_count': 1, 'applied_count': 1,
                   'applied_points': [point],
                   'applied_fault_ids': [fingerprint(point)]}
        self.assertTrue(strict_injection(applied, [point]))
        self.assertFalse(strict_injection({**applied, 'applied_points': [B]},
                                          [point]))
        self.assertTrue(strict_injection({**applied,
                                         'applied_points': [{**point,
                                                            'occurrenceOrdinal': 1}]},
                                         [point]))
        ordinal_point = {**point, 'occurrenceOrdinal': 2}
        ordinal_applied = {**applied,
                           'applied_points': [ordinal_point],
                           'applied_fault_ids': [fingerprint(ordinal_point)]}
        self.assertTrue(strict_injection(ordinal_applied, [ordinal_point]))
        self.assertFalse(strict_injection(
            {**ordinal_applied, 'applied_points': [{**ordinal_point,
                                                   'occurrenceOrdinal': 1}]},
            [ordinal_point]))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root, mode='pre_target', max_trials=1)
            state = campaign(config, root / 'out')
            result = json.loads(Path(state['completed'][0]['result']).read_text())
            self.assertTrue(result['target_reached'])
            self.assertFalse(result['target_reached_after_fault'])
            self.assertEqual(result['status'], 'lost_target')

    def test_datanode_heartbeat_actor_identity_survives_ephemeral_name(self):
        old = {**A, 'occurrence':
               'local/BP-9520-127.0.0.1-123 heartbeating to '
               'localhost/127.0.0.1:34567/' + A['siteId']}
        new = {**old, 'occurrence':
               'local/BPServiceActor heartbeating/' + A['siteId']}
        applied = {'matched_count': 1, 'applied_count': 1,
                   'applied_points': [new],
                   'applied_fault_ids': [fingerprint(old)]}
        self.assertTrue(strict_injection(applied, [old]))
        self.assertFalse(strict_injection(
            {**applied, 'applied_points': [{**new, 'hitOrdinal': 2}]}, [old]))

    def test_default_thread_object_hash_does_not_break_replay(self):
        original = {**A, 'occurrence':
                    'local/org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker$1@e7a1919/'
                    + A['siteId']}
        replayed = {**original, 'occurrence':
                    'local/org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker$1@29235c48/'
                    + A['siteId']}
        applied = {'matched_count': 1, 'applied_count': 1,
                   'applied_points': [replayed],
                   'applied_fault_ids': [fingerprint(original)]}
        self.assertTrue(strict_injection(applied, [original]))

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

    def test_target_field_writer_callback_outranks_broad_dispatch(self):
        self.assertGreater(static_reason_priority('target_short_writer_caller'),
                           static_reason_priority('callee_may_dispatch'))
        self.assertGreater(static_reason_priority('target_direct_field_writer'),
                           static_reason_priority('callee_may_dispatch'))

    def test_completed_retry_archives_every_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = Path(temp) / 'trial'
            for number in (1, 2):
                attempt = trial / f'attempt-{number:02d}'
                trace = attempt / 'trace' / 'runtime_trace.jsonl'
                trace.parent.mkdir(parents=True)
                trace.write_text(f'attempt {number}\n')
                (attempt / 'result.json').write_text(json.dumps({'trace': str(trace)}))
            final = {'trace': str(trial / 'attempt-02/trace/runtime_trace.jsonl')}
            archived = archive_trial_attempts(trial, final)
            self.assertEqual(len(archived), 2)
            for number in (1, 2):
                attempt = trial / f'attempt-{number:02d}'
                trace = attempt / 'trace' / 'runtime_trace.jsonl'
                self.assertFalse(trace.exists())
                with gzip.open(str(trace) + '.gz', 'rt') as stream:
                    self.assertEqual(stream.read(), f'attempt {number}\n')
                record = json.loads((attempt / 'result.json').read_text())
                self.assertEqual(record['trace'], str(trace) + '.gz')
            self.assertEqual(final['trace'], str(trial / 'attempt-02/trace/runtime_trace.jsonl.gz'))

    def test_archive_repairs_legacy_attempt_pointer_to_existing_gzip(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = Path(temp) / 'trial'
            attempt = trial / 'attempt-01'
            trace = attempt / 'trace/runtime_trace.jsonl'
            trace.parent.mkdir(parents=True)
            with gzip.open(str(trace) + '.gz', 'wt') as stream:
                stream.write('preserved trace\n')
            (attempt / 'result.json').write_text(json.dumps({'trace': str(trace)}))
            (attempt / 'trace/manifest.json').write_text(
                json.dumps({'trace': str(trace)}))
            final = {'trace': str(trace)}
            self.assertEqual(archive_trial_attempts(trial, final), [str(trace) + '.gz'])
            self.assertEqual(final['trace'], str(trace) + '.gz')
            self.assertEqual(json.loads((attempt / 'result.json').read_text())['trace'],
                             str(trace) + '.gz')
            self.assertEqual(json.loads((attempt / 'trace/manifest.json').read_text())
                             ['trace'], str(trace) + '.gz')


if __name__ == '__main__':
    unittest.main()
