#!/usr/bin/env python3
"""Pure/offline V5 scheduler and handoff tests; never start a cluster JUnit."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import campaign_v2 as v2
import campaign_v5 as v5
from build_v2 import sha
from calibrate_v2 import SOURCE


ACTOR = 'JETTY/node1'
TARGET = [ACTOR, 'SOLR/CORE/testAddMultipleReplicas/shard1/core_node2/core',
          'JETTY/node1/core']


def step(ordinal: int = 1, site: str = 'getLeaderProps:1495') -> dict:
    return {'actorKey': ACTOR, 'sourceKey': SOURCE, 'operation': 'GET_DATA',
            'siteId': site, 'resource': '/collections/c/leaders/shard1/leader',
            'hitOrdinal': ordinal, 'kind': 'CONNECTION_LOSS'}


def row(event: str, seq: int, **changes) -> dict:
    value = {'event': event, 'seq': seq, 'threadId': 7, 'actorKey': ACTOR,
             'sourceKey': SOURCE, 'operation': 'GET_DATA',
             'siteId': 'getLeaderProps:1495',
             'resource': '/collections/c/leaders/shard1/leader',
             'hitOrdinal': 1, 'applied': event == 'IO_APPLIED',
             'targetKey': '', 'leaderKey': '',
             'detail': 'clientIdentity=client;nodeName=node1'}
    value.update(changes)
    return value


def parent_rows(core_present: bool = True, client: str = 'client',
                target_thread: int = 7) -> list[dict]:
    guard = ('eligible=true;replicaType=NRT;corePresent=' +
             str(core_present).lower() + ';clientIdentity=' + client +
             ';nodeName=node1;controllerIdentity=ctl')
    return [
        row('CLIENT_BIND', 1, detail='clientIdentity=client;nodeName=node1;controllerIdentity=ctl'),
        row('IO_OBSERVED', 9),
        row('IO_APPLIED', 10, detail='clientIdentity=client;nodeName=node1;planStep=1;kind=CONNECTION_LOSS'),
        row('TARGET_CHECK', 11, threadId=target_thread, operation='CORE_AVAILABILITY',
            siteId='ZkController.register:1325', targetKey=TARGET[1],
            leaderKey=TARGET[2], detail=guard),
        row('SUMMARY', 12, detail='applied=1/1'),
    ]


def result(sequence: list[dict], number: int = 1, **changes) -> dict:
    value = {'number': number, 'target': TARGET, 'sequence': sequence,
             'junit_exit': 0, 'exact_injection': True, 'applied_faults': len(sequence),
             'target_after_fault': True, 'target_exception': False,
             'effective': True, 'new_coverage': 0, 'new_families': 0}
    value.update(changes)
    return value


def write_parent(directory: Path, *, core_present: bool = True,
                 client: str = 'client', passed: bool = True,
                 target_thread: int = 7) -> None:
    directory.mkdir(parents=True)
    (directory / 'run.json').write_text(json.dumps({'exit_code': 0}))
    (directory / 'junit.log').write_text(
        'SOLR05_JUNIT_RESULT run=1 failures=0 ignored=0\n' if passed else
        'SOLR05_JUNIT_RESULT run=1 failures=1 ignored=0\n')
    (directory / 'events.jsonl').write_text(''.join(
        json.dumps(item) + '\n' for item in parent_rows(core_present, client, target_thread)))


def stopped_state() -> dict:
    parent = result([step()])
    return {'case_id': 'SOLR-07', 'selected_count': 1, 'trials': [parent],
            'seen': [v2.identity((TARGET, [step()]))],
            'queue': [{'target': TARGET, 'sequence': [step(), step(2)],
                       'parent_gain': 0, 'wait': 0}],
            'budget': {'effective_trials': 10, 'max_selected': 1, 'max_faults': 8},
            'effective_count': 1, 'stopped': True, 'stop_reason': 'selected_trial_cap',
            'scheduler_v4': {'policy': 'all_stable_actor_roots_v4',
                             'sha256': sha(v5.V4_FILE)}}


class ParentProofTests(unittest.TestCase):
    def test_passing_same_client_live_core_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'trial-001'
            write_parent(directory)
            verdict = v5.parent_verdict(result([step()]), directory)
            self.assertTrue(verdict['eligible'], verdict)
            self.assertTrue(verdict['direct_thread'])
            self.assertEqual(verdict['first_guard_seq'], 11)

    def test_teardown_or_failed_or_other_client_parent_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for name, options in (
                ('closed', {'core_present': False}),
                ('wrong_client', {'client': 'other'}),
                ('failed_junit', {'passed': False}),
            ):
                directory = base / name
                write_parent(directory, **options)
                self.assertFalse(v5.parent_verdict(result([step()]), directory)['eligible'], name)
            directory = base / 'passed'
            write_parent(directory)
            self.assertFalse(v5.parent_verdict(
                result([step()], target_exception=True), directory)['eligible'])
            self.assertFalse(v5.parent_verdict(
                result([step()], junit_exit=1), directory)['eligible'])

    def test_async_same_actor_parent_is_eligible_but_lower_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'trial-001'
            write_parent(directory, target_thread=8)
            verdict = v5.parent_verdict(result([step()]), directory)
            self.assertTrue(verdict['eligible'])
            self.assertFalse(verdict['direct_thread'])

    def test_target_throw_requires_guard_after_fault_on_same_controller(self) -> None:
        trace = parent_rows(core_present=False)
        guard = trace[3]
        throw = row('TARGET_THROW', 12, operation='CORE_AVAILABILITY',
                    siteId='ZkController.register:1326', targetKey=TARGET[1],
                    leaderKey=TARGET[2],
                    detail='failure=SolrException;controllerIdentity=ctl')
        trace.insert(4, throw)
        trace[-1]['seq'] = 13
        self.assertEqual(len(v5.paired_post_fault_throws(trace, result([step()]))), 1)
        throw['detail'] = 'failure=SolrException;controllerIdentity=other'
        self.assertEqual(v5.paired_post_fault_throws(trace, result([step()])), [])
        throw['detail'] = 'failure=SolrException;controllerIdentity=ctl'
        guard['seq'] = 8  # fault interleaves between guard and throw
        self.assertEqual(v5.paired_post_fault_throws(trace, result([step()])), [])


class SelectionTests(unittest.TestCase):
    def make_state(self) -> dict:
        parent = result([step()])
        parent_id = v5.parent_key(TARGET, parent['sequence'])
        children = [{'target': TARGET,
                     'sequence': [step(), step(number, f'getData:{number}')],
                     'parent_gain': 0, 'wait': 0}
                    for number in range(2, 6)]
        return {'selected_count': 0, 'trials': [parent], 'queue': children + [
            {'target': TARGET, 'sequence': [step(20, 'newRoot')],
             'parent_gain': 0, 'wait': 0}],
            'scheduler_v5': {'parent_verdicts': {
                parent_id: {'eligible': True, 'direct_thread': True}}}}

    def test_four_productive_descendants_then_one_root(self) -> None:
        state = self.make_state()
        lengths = []
        for count in range(5):
            state['selected_count'] = count
            lengths.append(len(v5.choose(state)['sequence']))
        self.assertEqual(lengths, [2, 2, 2, 2, 1])

    def test_old_zero_gain_descendant_gets_service(self) -> None:
        state = self.make_state()
        state['queue'][0]['wait'] = 19
        for child in state['queue'][1:4]:
            child['parent_gain'] = 100
        selected = v5.choose(state)
        self.assertEqual(selected['sequence'][1]['hitOrdinal'], 2)

    def test_resume_determinism_and_no_completed_plan_in_queue(self) -> None:
        state = self.make_state()
        clone = json.loads(json.dumps(state))
        self.assertEqual(v5.choose(state), v5.choose(clone))
        self.assertEqual(state['queue'], clone['queue'])


class HandoffTests(unittest.TestCase):
    def test_freeze_and_raw_manifest_gate_without_junit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            campaign = home / 'campaign'
            trial = campaign / 'trial-001'
            trial.mkdir(parents=True)
            state = stopped_state()
            live = campaign / 'state.json'
            live.write_text(json.dumps(state))
            (trial / 'run.json').write_text(json.dumps({'exit_code': 0}))
            (trial / 'trial.json').write_text(json.dumps(state['trials'][0]))
            v2.write_plan(trial / 'fault.properties', TARGET, [step()])
            (trial / 'events.jsonl').write_text(''.join(
                json.dumps(item) + '\n' for item in parent_rows()))
            (trial / 'junit.log').write_text('SOLR05_JUNIT_RESULT run=1 failures=0 ignored=0\n')
            (trial / 'jacoco.exec').write_bytes(b'offline-placeholder')
            with (patch.object(v2, 'ROOT', campaign), patch.object(v2, 'STATE', live),
                  patch.object(v5, 'HANDOFF', home / 'handoff'),
                  patch.object(v5, 'no_v4_process'), patch.object(v2, 'verify_state')):
                frozen = v5.freeze()
                snapshot = Path(frozen['snapshot'])
                manifest = Path(frozen['manifest'])
                self.assertFalse(snapshot.stat().st_mode & 0o222)
                self.assertFalse(manifest.stat().st_mode & 0o222)
                audit = home / 'audit.json'
                audit.write_text(json.dumps({
                    'checkpoint_sha256': frozen['checkpoint_sha256'],
                    'selected': 1, 'effective': 1, 'errors': []}))
                audit.chmod(0o444)
                self.assertEqual(v5.validate_handoff(
                    snapshot, manifest, audit, state)['effective'], 1)
                (trial / 'junit.log').chmod(0o644)
                (trial / 'junit.log').write_text('changed')
                with self.assertRaisesRegex(RuntimeError, 'raw evidence changed'):
                    v5.validate_handoff(snapshot, manifest, audit, state)

    def test_stopped_budget_only_and_no_inflight_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = stopped_state()
            with patch.object(v2, 'ROOT', root):
                v5.checked_snapshot(state)
                for change in ({'stopped': False}, {'stop_reason': 'queue_exhausted'},
                               {'effective_count': 0}):
                    invalid = {**state, **change}
                    with self.assertRaises(RuntimeError):
                        v5.checked_snapshot(invalid)
                (root / 'trial-002').mkdir()
                with self.assertRaisesRegex(RuntimeError, 'in-flight'):
                    v5.checked_snapshot(state)

    def test_orphan_and_crash_before_80_extension_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(v2, 'ROOT', Path(temporary)):
                state = stopped_state()
                state['queue'][0]['sequence'][0]['siteId'] = 'wrong-parent'
                with self.assertRaisesRegex(RuntimeError, 'effective completed parent'):
                    v5.checked_snapshot(state)
                state = stopped_state()
                state['budget']['effective_trials'] = 80
                state['effective_count'] = 80
                state['stop_reason'] = 'effective_budget_met'
                state['trials'] = [result([step(i)], number=i, new_coverage=1 if i == 80 else 0)
                                   for i in range(1, 81)]
                state['selected_count'] = 80
                state['seen'] = [v2.identity((TARGET, row['sequence']))
                                 for row in state['trials']]
                state['queue'] = []
                with self.assertRaisesRegex(RuntimeError, 'extension was not committed'):
                    v5.checked_snapshot(state)

    def test_frozen_audit_sha_and_error_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = stopped_state()
            snapshot = root / 'snapshot.json'
            manifest = root / 'manifest.json'
            audit = root / 'audit.json'
            live = root / 'live.json'
            raw = json.dumps(state).encode()
            snapshot.write_bytes(raw)
            live.write_bytes(raw)
            manifest.write_text(json.dumps({'checkpoint_sha256': v5.digest_bytes(raw),
                                            'selected': 1, 'artifacts': {}}))
            audit.write_text(json.dumps({'checkpoint_sha256': v5.digest_bytes(raw),
                                         'selected': 1, 'effective': 1, 'errors': []}))
            for artifact in (snapshot, manifest, audit):
                artifact.chmod(0o444)
            with patch.object(v2, 'ROOT', root), patch.object(v2, 'STATE', live):
                self.assertEqual(v5.validate_handoff(
                    snapshot, manifest, audit, state, verify_raw=False)['selected'], 1)
                audit.chmod(0o644)
                audit.write_text(json.dumps({'checkpoint_sha256': v5.digest_bytes(raw),
                                             'selected': 1, 'effective': 1,
                                             'errors': ['raw mismatch']}))
                audit.chmod(0o444)
                with self.assertRaisesRegex(RuntimeError, 'disagree'):
                    v5.validate_handoff(snapshot, manifest, audit, state, verify_raw=False)


if __name__ == '__main__':
    unittest.main()
