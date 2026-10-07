#!/usr/bin/env python3
"""Offline V6 handoff and selector tests; no cluster JUnit is invoked."""

from __future__ import annotations

from contextlib import nullcontext
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import campaign_v2 as v2
import campaign_v5 as v5
import campaign_v6 as v6
from build_v2 import sha
from calibrate_v2 import SOURCE


ACTOR = 'JETTY/node1'
TARGET = [ACTOR, 'SOLR/CORE/testAddMultipleReplicas/shard1/core_node2/core',
          'JETTY/node1/core']


def point(ordinal: int, site: str = 'state:100') -> dict:
    return {'actorKey': ACTOR, 'sourceKey': SOURCE, 'operation': 'GET_DATA',
            'siteId': site, 'resource': '/collections/testAddMultipleReplicas/state.json',
            'hitOrdinal': ordinal, 'kind': 'CONNECTION_LOSS'}


def event(kind: str, seq: int, client: str, *, ordinal: int = 1,
          site: str = 'state:100', **changes) -> dict:
    row = {'event': kind, 'seq': seq, 'threadId': 7, 'actorKey': ACTOR,
           'sourceKey': SOURCE, 'operation': 'GET_DATA', 'siteId': site,
           'resource': '/collections/testAddMultipleReplicas/state.json',
           'hitOrdinal': ordinal, 'applied': kind == 'IO_APPLIED',
           'targetKey': '', 'leaderKey': '',
           'detail': f'clientIdentity={client};nodeName=node1'}
    row.update(changes)
    return row


def fixture_trace(fault_ordinal: int, client: str) -> list[dict]:
    guard = ('eligible=true;replicaType=NRT;corePresent=true;'
             f'clientIdentity={client};nodeName=node1;controllerIdentity=ctl')
    return [
        event('CLIENT_BIND', 1, client,
              detail=f'clientIdentity={client};nodeName=node1;controllerIdentity=ctl'),
        event('CLIENT_BIND', 2, 'other',
              detail='clientIdentity=other;nodeName=node1;controllerIdentity=otherctl'),
        event('IO_OBSERVED', 5, client, ordinal=55, site='pre:50'),
        event('IO_OBSERVED', 9, client, ordinal=fault_ordinal),
        event('IO_APPLIED', 10, client, ordinal=fault_ordinal,
              detail=(f'clientIdentity={client};nodeName=node1;'
                      'planStep=1;kind=CONNECTION_LOSS')),
        event('IO_OBSERVED', 12, client, ordinal=77, site='recovery:70'),
        event('IO_OBSERVED', 13, 'other', ordinal=88, site='wrong-client:80'),
        event('TARGET_CHECK', 20, client, operation='CORE_AVAILABILITY',
              siteId='ZkController.register:1325', targetKey=TARGET[1],
              leaderKey=TARGET[2], detail=guard),
        event('SUMMARY', 21, client, detail='applied=1/1'),
    ]


def result(number: int, fault_ordinal: int, **changes) -> dict:
    row = {'number': number, 'target': TARGET, 'sequence': [point(fault_ordinal)],
           'elapsed_seconds': 17.0 + number, 'junit_exit': 0,
           'exact_injection': True, 'applied_faults': 1,
           'target_after_fault': True, 'target_exception': False,
           'effective': True, 'new_coverage': 0, 'new_families': 0}
    row.update(changes)
    return row


class V6GateTest(unittest.TestCase):
    def minimal_state(self, *, stopped: bool = True, reason: str = 'selected_trial_cap') -> dict:
        item = result(1, 1, effective=False, target_after_fault=False)
        return {'case_id': 'SOLR-07', 'selected_count': 1, 'trials': [item],
                'seen': [v6.plan_id(TARGET, item['sequence'])], 'queue': [],
                'stopped': stopped, 'stop_reason': reason, 'effective_count': 0,
                'budget': {'effective_trials': 80, 'max_selected': 1, 'max_faults': 8},
                'scheduler_v5': {'policy': v5.POLICY, 'sha256': sha(v5.V5_FILE),
                                 'v4_sha256': sha(v5.V4_FILE),
                                 'handoff': {'selected': 0}}}

    def test_only_natural_below_budget_v5_can_handoff(self) -> None:
        state = self.minimal_state()
        self.assertEqual(v6.assert_natural_v5_stop(state), (1, 0))
        for invalid in (
                {**state, 'stopped': False},
                {**state, 'stop_reason': 'queue_exhausted'},
                {**state, 'scheduler_v6': {'policy': v6.POLICY}},
                {**state, 'seen': []},
                {**state, 'budget': {**state['budget'], 'max_selected': 2}}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(RuntimeError):
                    v6.assert_natural_v5_stop(invalid)

    def test_failed_independent_audit_cannot_write_live_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_file = Path(temporary) / 'state.json'
            state_file.write_text('sentinel')
            with (patch.object(v6, 'exclusive_controller', return_value=nullcontext()),
                  patch.object(v6, 'no_active_junit_or_v5'),
                  patch.object(v2, 'STATE', state_file),
                  patch.object(v6, 'validate_handoff', side_effect=RuntimeError('bad audit')),
                  patch.object(v2, 'atomic') as write):
                with self.assertRaisesRegex(RuntimeError, 'bad audit'):
                    v6.activate(Path('snapshot'), Path('manifest'),
                                Path('inventory'), Path('audit'), run_campaign=False)
                write.assert_not_called()
                self.assertEqual(state_file.read_text(), 'sentinel')

    def test_atomic_seal_is_idempotent_and_rejects_changed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'state-frozen.json'
            v6.immutable(path, b'first checkpoint\n')
            v6.immutable(path, b'first checkpoint\n')
            self.assertEqual(path.read_bytes(), b'first checkpoint\n')
            self.assertEqual(path.stat().st_mode & 0o222, 0)
            with self.assertRaisesRegex(RuntimeError, 'pre-existing immutable'):
                v6.immutable(path, b'different checkpoint\n')
            self.assertEqual(path.read_bytes(), b'first checkpoint\n')

    def test_v5_lock_and_live_junit_process_block_freeze_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v5_lock = root / 'v5' / 'controller.lock'
            v6_lock = root / 'v6' / 'controller.lock'
            v5_lock.parent.mkdir()
            with (patch.object(v6, 'V5_LOCK', v5_lock),
                  patch.object(v6, 'V6_LOCK', v6_lock),
                  patch.object(v6, 'HANDOFF', v6_lock.parent)):
                with v5_lock.open('a+b') as owner:
                    fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaisesRegex(RuntimeError, 'controller lock is held'):
                        with v6.exclusive_controller():
                            pass
                with v6.exclusive_controller():
                    pass
        junit = ('999999999 /usr/bin/java baseline.solr07.RunSingleJUnit '
                 'org.apache.solr.cloud.AddReplicaTest testAddMultipleReplicas\n')
        with patch.object(v6.subprocess, 'check_output', return_value=junit):
            with self.assertRaisesRegex(RuntimeError, 'JUnit still runs'):
                v6.no_active_junit_or_v5()

    def test_raw_manifest_rejects_mutation_or_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'trial-001'
            directory.mkdir()
            for name in v6.RAW_FILES:
                (directory / name).write_bytes(name.encode())
            state = {'selected_count': 1}
            with patch.object(v2, 'ROOT', root):
                manifest = v6.raw_manifest(state)
                v6.verify_raw_manifest(manifest, state)
                (directory / 'junit.log').write_text('changed')
                with self.assertRaisesRegex(RuntimeError, 'frozen raw artifact changed'):
                    v6.verify_raw_manifest(manifest, state)
                (directory / 'events.jsonl').unlink()
                with self.assertRaisesRegex(RuntimeError, 'frozen raw artifact changed'):
                    v6.verify_raw_manifest(manifest, state)

    def test_raw_ledger_checks_plan_run_and_applied_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            here = Path(temporary)
            root = here / 'campaign'
            directory = root / 'trial-001'
            directory.mkdir(parents=True)
            trial = result(1, 1)
            (directory / 'trial.json').write_text(json.dumps(trial))
            trace = fixture_trace(1, 'client1')
            (directory / 'events.jsonl').write_text(
                ''.join(json.dumps(row) + '\n' for row in trace))
            v2.write_plan(directory / 'fault.properties', TARGET, trial['sequence'])
            (here / 'build-receipt.json').write_text(json.dumps({
                'source_revision': 'original-solr',
                'test': 'AddReplicaTest#testAddMultipleReplicas'}))
            run = {'exit_code': 0, 'agent_sha256': 'agent',
                   'source_revision': 'original-solr',
                   'test': 'AddReplicaTest#testAddMultipleReplicas',
                   'assertions_enabled': True, 'instrumented': True,
                   'plan': str((directory / 'fault.properties').resolve())}
            (directory / 'run.json').write_text(json.dumps(run))
            state = {'trials': [trial], 'agent_sha256': 'agent'}
            with patch.object(v2, 'HERE', here), patch.object(v2, 'ROOT', root):
                v6.verify_raw_ledger(state)
                run['exit_code'] = 1
                (directory / 'run.json').write_text(json.dumps(run))
                with self.assertRaisesRegex(RuntimeError, 'raw JUnit run differs'):
                    v6.verify_raw_ledger(state)
                run['exit_code'] = 0
                (directory / 'run.json').write_text(json.dumps(run))
                (directory / 'fault.properties').write_text('count=0\n')
                with self.assertRaisesRegex(RuntimeError, 'raw fault plan differs'):
                    v6.verify_raw_ledger(state)
                v2.write_plan(directory / 'fault.properties', TARGET, trial['sequence'])
                (directory / 'events.jsonl').write_text('{"event":"SUMMARY"}\n')
                with self.assertRaisesRegex(RuntimeError, 'raw applied count differs'):
                    v6.verify_raw_ledger(state)

    def test_activation_preserves_old_ledger_queue_and_seen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_file = Path(temporary) / 'state.json'
            inventory_file = Path(temporary) / 'inventory.json'
            original = self.minimal_state()
            legacy = {'target': TARGET, 'sequence': [point(23, 'legacy:23')],
                      'wait': 9, 'parent_gain': 2}
            original['queue'].append(legacy)
            before = json.dumps(original, sort_keys=True)
            state_file.write_text(json.dumps(original))
            root = {'identity': v6.plan_id(TARGET, [point(77, 'new:77')]),
                    'target': TARGET, 'sequence': [point(77, 'new:77')],
                    'tier': 0, 'witness_trials': 2, 'post_witness_trials': 2,
                    'median_elapsed_seconds': 17.5}
            inventory_file.write_text(json.dumps({'candidates': [root]}))
            receipt = {'selected': 1, 'effective': 0,
                       'snapshot_sha256': 'snapshot', 'manifest_sha256': 'manifest',
                       'inventory_sha256': 'inventory', 'audit_sha256': 'audit'}
            with (patch.object(v6, 'exclusive_controller', return_value=nullcontext()),
                  patch.object(v6, 'no_active_junit_or_v5'),
                  patch.object(v6, 'validate_handoff', return_value=receipt),
                  patch.object(v2, 'STATE', state_file)):
                activated = v6.activate(Path('snapshot'), Path('manifest'),
                                        inventory_file, Path('audit'), run_campaign=False)
            persisted = json.loads(state_file.read_text())
            self.assertEqual(persisted, activated)
            self.assertEqual(persisted['trials'], original['trials'])
            self.assertEqual(persisted['seen'], original['seen'])
            self.assertEqual(persisted['queue'][0], legacy)
            self.assertEqual(persisted['queue'][1]['origin'], v6.ORIGIN_ROOT)
            self.assertEqual(persisted['scheduler_v6']['source_scheduler_v5'],
                             original['scheduler_v5'])
            self.assertNotIn('scheduler_v5', persisted)
            self.assertEqual(persisted['selected_count'], 1)
            self.assertEqual(persisted['budget']['max_selected'], 257)
            self.assertEqual(persisted['scheduler_v6']['deficit_at_handoff'], 80)
            self.assertEqual(json.dumps(original, sort_keys=True), before)

    def test_activate_completed_trial_then_resume_and_reject_partial_trial(self) -> None:
        """A frozen N+1 is valid after commit; the live next ID is never reused."""
        with tempfile.TemporaryDirectory() as temporary:
            here = Path(temporary)
            root = here / 'campaign'
            root.mkdir()
            state_file = root / 'state.json'
            (here / 'build-receipt.json').write_text(json.dumps({
                'source_revision': 'original-solr',
                'test': 'AddReplicaTest#testAddMultipleReplicas'}))

            def write_trial(item: dict, trace: list[dict]) -> None:
                number = item['number']
                directory = root / f'trial-{number:03d}'
                directory.mkdir()
                (directory / 'events.jsonl').write_text(
                    ''.join(json.dumps(row) + '\n' for row in trace))
                (directory / 'trial.json').write_text(json.dumps(item))
                (directory / 'junit.log').write_text(
                    'SOLR05_JUNIT_RESULT run=1 failures=0 ignored=0\n')
                (directory / 'jacoco.exec').write_bytes(b'coverage')
                v2.write_plan(directory / 'fault.properties', TARGET, item['sequence'])
                (directory / 'run.json').write_text(json.dumps({
                    'exit_code': item['junit_exit'], 'agent_sha256': 'agent',
                    'source_revision': 'original-solr',
                    'test': 'AddReplicaTest#testAddMultipleReplicas',
                    'assertions_enabled': True, 'instrumented': True,
                    'plan': str((directory / 'fault.properties').resolve())}))

            first = result(1, 1)
            write_trial(first, fixture_trace(1, 'client1'))
            frozen = self.minimal_state()
            frozen['trials'] = [first]
            frozen['effective_count'] = 1
            frozen['agent_sha256'] = 'agent'
            frozen['queue'] = [{'target': TARGET,
                                'sequence': [point(99, 'legacy:99')],
                                'parent_gain': 0, 'wait': 1}]
            frozen_raw = v6.canonical(frozen)
            state_file.write_bytes(frozen_raw)
            first_sha = sha(root / 'trial-001' / 'events.jsonl')

            with (patch.object(v2, 'HERE', here), patch.object(v2, 'ROOT', root),
                  patch.object(v2, 'STATE', state_file),
                  patch.object(v2, 'verify_state'),
                  patch.object(v6, 'exclusive_controller', return_value=nullcontext()),
                  patch.object(v6, 'no_active_junit_or_v5')):
                manifest = v6.raw_manifest(frozen)
                manifest['checkpoint_sha256'] = v6.digest(frozen_raw)
                inventory = v6.build_inventory(
                    {**frozen, '_frozen_sha256': v6.digest(frozen_raw)}, manifest)
                self.assertGreater(inventory['candidate_count'], 0)
                handoff = here / 'handoff-v6'
                snapshot = handoff / 'state.json'
                manifest_path = handoff / 'raw.json'
                inventory_path = handoff / 'inventory.json'
                audit_path = handoff / 'audit.json'
                for path, content in (
                        (snapshot, frozen_raw),
                        (manifest_path, v6.canonical(manifest)),
                        (inventory_path, v6.canonical(inventory)),
                        (audit_path, v6.canonical({
                            'case_id': 'SOLR-07',
                            'checkpoint_sha256': v6.digest(frozen_raw),
                            'selected': 1, 'effective': 1, 'errors': []}))):
                    v6.immutable(path, content)
                activated = v6.activate(snapshot, manifest_path, inventory_path,
                                        audit_path, run_campaign=False)
                source = inventory['candidates'][0]
                second = result(2, source['sequence'][0]['hitOrdinal'],
                                sequence=source['sequence'])
                second_trace = fixture_trace(second['sequence'][0]['hitOrdinal'],
                                             'client2')
                for row in second_trace:
                    if row['seq'] in (9, 10):
                        row.update({field: second['sequence'][0][field]
                                    for field in v2.FIELDS[:-1]})
                write_trial(second, second_trace)
                live = json.loads(state_file.read_text())
                live['queue'] = [entry for entry in live['queue'] if
                                 v6.plan_id(entry['target'], entry['sequence']) !=
                                 source['identity']]
                live['trials'].append(second)
                live['seen'].append(source['identity'])
                live['selected_count'] = 2
                v2.atomic(state_file, live)
                with (patch.object(v2, 'campaign') as run,
                      patch.object(v2, 'choose'), patch.object(v2, 'mutate')):
                    v6.continue_campaign()
                    run.assert_called_once()
                self.assertEqual(sha(root / 'trial-001' / 'events.jsonl'), first_sha)
                self.assertEqual(activated['trials'], [first])

                (root / 'trial-003').mkdir()
                with self.assertRaisesRegex(RuntimeError, 'unaccounted in-flight V6'):
                    v6.continue_campaign()
                (root / 'trial-003').rmdir()

                # If a process died after writing trial-002 but before committing
                # state, the directory is quarantined instead of replayed as ID 2.
                v2.atomic(state_file, activated)
                with self.assertRaisesRegex(RuntimeError, 'unaccounted in-flight V6'):
                    v6.continue_campaign()
                self.assertEqual(sha(root / 'trial-001' / 'events.jsonl'), first_sha)


class V6InventoryTest(unittest.TestCase):
    def test_repeated_post_fault_root_retains_exact_client_and_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trials = [result(1, 1), result(2, 2)]
            manifest = {'artifacts': {}}
            for trial in trials:
                number = trial['number']
                directory = root / f'trial-{number:03d}'
                directory.mkdir()
                trace = fixture_trace(number, f'client{number}')
                (directory / 'events.jsonl').write_text(
                    ''.join(json.dumps(row) + '\n' for row in trace))
                (directory / 'junit.log').write_text(
                    'SOLR05_JUNIT_RESULT run=1 failures=0 ignored=0\n')
                (directory / 'run.json').write_text(json.dumps({'exit_code': 0}))
                (directory / 'trial.json').write_text(json.dumps(trial))
                manifest['artifacts'][str(number)] = {
                    name: sha(directory / name)
                    for name in ('events.jsonl', 'junit.log', 'run.json', 'trial.json')}
            state = {'selected_count': 2, 'trials': trials,
                     'seen': [v6.plan_id(TARGET, item['sequence']) for item in trials],
                     'queue': [], 'scheduler_v5': {'handoff': {'selected': 0}},
                     '_frozen_sha256': 'frozen'}
            with patch.object(v2, 'ROOT', root):
                inventory = v6.build_inventory(state, manifest)
            self.assertEqual(inventory['candidate_count'], 2)
            by_site = {entry['sequence'][0]['siteId']: entry
                       for entry in inventory['candidates']}
            self.assertEqual(by_site['recovery:70']['tier'], 0)
            self.assertEqual(by_site['recovery:70']['post_witness_trials'], 2)
            self.assertEqual(by_site['pre:50']['tier'], 2)
            self.assertEqual(by_site['pre:50']['post_witness_trials'], 0)
            self.assertNotIn('wrong-client:80', by_site)
            self.assertEqual(inventory['tiers'], {'0': 1, '2': 1})

    def test_aged_legacy_plan_does_not_override_repeated_post_fault_root(self) -> None:
        root = {'target': TARGET, 'sequence': [point(77, 'recovery:70')],
                'origin': v6.ORIGIN_ROOT, 'tier': 0, 'wait': 0,
                'cost_seconds': 18.0}
        pre = {'target': TARGET, 'sequence': [point(55, 'pre:50')],
               'origin': v6.ORIGIN_ROOT, 'tier': 2, 'wait': 0,
               'cost_seconds': 17.0}
        legacy = {'target': TARGET, 'sequence': [point(88, 'legacy:80')],
                  'wait': 100, 'cost_seconds': 16.0}
        state = {'selected_count': 10, 'trials': [], 'queue': [legacy, pre, root],
                 'scheduler_v6': {'handoff': {'selected': 10},
                                  'source_scheduler_v5': {'parent_verdicts': {}}}}
        chosen = v6.choose(state)
        self.assertEqual(chosen['sequence'][0]['siteId'], 'recovery:70')
        self.assertEqual(len(state['queue']), 2)

    def test_pair_mutation_requires_passing_one_fault_parent(self) -> None:
        parent = result(1, 1)
        trace = fixture_trace(1, 'client1')
        state = {'seen': [v6.plan_id(TARGET, parent['sequence'])], 'queue': []}
        verdict = {'eligible': True, 'first_guard_seq': 20}
        with patch.object(v5, 'parent_verdict', return_value=verdict):
            v6.mutate(state, TARGET, parent['sequence'], trace, parent)
        self.assertEqual(len(state['queue']), 1)
        self.assertEqual(state['queue'][0]['sequence'][-1]['siteId'], 'recovery:70')
        self.assertEqual(state['queue'][0]['origin'], v6.ORIGIN_PAIR)
        failing = result(2, 2, junit_exit=1)
        v6.mutate(state, TARGET, failing['sequence'], trace, failing)
        self.assertEqual(len(state['queue']), 1)


if __name__ == '__main__':
    unittest.main()
