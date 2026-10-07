#!/usr/bin/env python3
"""Verify the completed SOLR-13 Overseer campaign and summarize its evidence."""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

import coverage as jacoco


HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE / 'evidence/campaign'
TERMINAL = {'budget_complete', 'queue_exhausted',
            'candidate_target_exception', 'attempt_cap_exhausted'}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def production_probes(path: Path, cp: str, production: set[str]) -> set[str]:
    assert path.is_file() and path.stat().st_size > 0, path
    output = subprocess.check_output([
        str(jacoco.JAVA / 'java'), '-cp', cp,
        'research.solr13stage2.Coverage', str(path)], text=True)
    probes = set()
    for row in output.splitlines():
        kind, class_id, name, index = row.split('\t')
        if kind == 'P' and name.split('$', 1)[0] in production:
            probes.add(class_id + ':' + name + ':' + index)
    return probes


def read_events(path: Path) -> list[dict]:
    with gzip.open(path, 'rt') as stream:
        return [json.loads(line) for line in stream]


def actor_chains(rows: list[dict], write: dict) -> list[tuple[dict, dict, dict]]:
    source = write['sourceKey']
    preceding = [event for event in rows if event['seq'] < write['seq']
                 and event['sourceKey'] == source]
    sends = [event for event in preceding if event['event'] == 'RPC_SEND']
    receives = [event for event in preceding if event['event'] == 'OVERSEER_RECEIVE']
    contexts = [event for event in preceding if event['event'] == 'ALIAS_WRITE_CONTEXT']
    return [(send, receive, context)
            for send in sends for receive in receives for context in contexts
            if send['seq'] < receive['seq'] < context['seq'] < write['seq']
            and receive['physicalNode'] == context['physicalNode']
            == write['physicalNode']]


def audit() -> dict:
    state = json.loads((CAMPAIGN / 'state.json').read_text())
    progress = json.loads((CAMPAIGN / 'progress.json').read_text())
    assert state['status'] in TERMINAL, state['status']
    assert state['active'] is None
    assert progress['status'] == state['status']
    completed = state['completed']
    assert [row['trial_number'] for row in completed] == list(
        range(1, len(completed) + 1))
    valid = [row for row in completed if not row.get('invalid_setup')]
    invalid = [row for row in completed if row.get('invalid_setup')]
    effective = [row for row in valid if row['effective']]
    assert len(valid) == progress['attempted_plans']
    assert len(invalid) == progress['invalid_setup_plans']
    assert len(effective) == progress['effective_target_retaining_trials']
    assert all(row['strict_injection'] and row['junit_pass'] and
               row['target_guard_after_last_fault'] > 0 and
               row['target_source_after_last_fault'] for row in effective)
    assert sum(row['strict_injection'] for row in valid) == progress['strict_injections']
    assert sum(row['target_exception_after_last_fault'] > 0 for row in valid) == \
        progress['target_exception_candidates']
    assert all(not row['effective'] and not row['strict_injection'] and
               not row['junit_pass'] for row in invalid)

    trial_dirs = sorted((CAMPAIGN / 'trials').glob('[0-9][0-9][0-9][0-9]-*'))
    assert len(trial_dirs) == len(completed)
    for row, trial in zip(completed, trial_dirs):
        assert trial.name.startswith(f"{row['trial_number']:04d}-")
        assert json.loads((trial / 'result.json').read_text()) == row
        trace = Path(row['trace'])
        assert trace.name == 'events.jsonl.gz'
        assert trace.is_file(), trace

    jacoco.build()
    cp = ':'.join((str(jacoco.CLASSES), str(jacoco.CORE), jacoco.classpath()))
    production = jacoco.production_classes()
    covered = set()
    for seed in ('healthy-01', 'healthy-02'):
        covered |= production_probes(HERE / 'evidence' / seed / 'jacoco.exec',
                                     cp, production)
    assert len(covered) == state['seed_probe_count']
    applied_writes = 0
    cross_node_writes = 0
    runs_with_cross_node_chain = 0
    for row in effective:
        run_has_cross_node_chain = False
        rows = read_events(Path(row['trace']))
        applied = [event for event in rows
                   if event['event'] == 'IO_OBSERVED' and event['applied']]
        assert len(applied) == row['applied_faults'] == row['planned_faults']
        assert [tuple(event[key] for key in ('marker', 'siteId', 'sourceKey',
                                            'resource', 'hitOrdinal'))
                for event in applied] == [
                    tuple(point[key] for key in ('marker', 'siteId', 'sourceKey',
                                                 'resource', 'hitOrdinal'))
                    for point in row['fault_sequence']]
        last = applied[-1]
        assert last['seq'] == row['last_applied_sequence']
        assert any(event['event'] == 'TARGET_CHECK'
                   and event['marker'] == 'SOLR13:CREATED_COLLECTION_VISIBLE_GUARD'
                   and event['sourceKey'] == row['target_source_after_last_fault']
                   and event['seq'] > last['seq'] for event in rows)
        throws = [event for event in rows
                  if event['event'] == 'TARGET_THROW'
                  and event['marker'] == 'SOLR13:CREATED_COLLECTION_MISSING_THROW'
                  and event['sourceKey'] == row['target_source_after_last_fault']
                  and event['seq'] > last['seq']]
        assert len(throws) == row['target_exception_after_last_fault']
        for write in applied:
            if write['marker'] != 'FAULT:ZK_NATIVE:setData' or \
                    write['resource'] != '/aliases.json':
                continue
            chains = actor_chains(rows, write)
            assert chains, (row['trial_number'], write['sourceKey'])
            applied_writes += 1
            if any(send['physicalNode'] != receive['physicalNode']
                   for send, receive, _ in chains):
                cross_node_writes += 1
                run_has_cross_node_chain = True
        probes = production_probes(Path(row['jacoco']), cp, production)
        assert len(probes) == row['production_probes_covered'], row['trial_number']
        assert len(probes - covered) == row['new_production_probes'], row['trial_number']
        covered |= probes
        runs_with_cross_node_chain += run_has_cross_node_chain
    assert covered == set(state['covered_probes'])
    assert len(covered) - state['seed_probe_count'] == progress['production_probe_gain']

    archives = sorted(CAMPAIGN.rglob('archive.json'))
    assert len(archives) >= progress['jvm_attempts']
    for receipt_path in archives:
        receipt = json.loads(receipt_path.read_text())
        compressed = receipt_path.with_name('events.jsonl.gz')
        assert compressed.is_file(), compressed
        assert digest(compressed) == receipt['gzip_sha256'], compressed
        assert compressed.stat().st_size == receipt['gzip_size'], compressed
        with gzip.open(compressed, 'rb') as stream:
            raw = stream.read()
        assert hashlib.sha256(raw).hexdigest() == receipt['raw_sha256'], compressed
        assert len(raw) == receipt['raw_size'], compressed

    result = {
        'case_id': 'SOLR-13',
        'phase': 'overseer_alias_write',
        'status': state['status'],
        'budget': state['budget'],
        'valid_attempted_plans': len(valid),
        'effective_target_retaining_trials': len(effective),
        'strict_injections': progress['strict_injections'],
        'valid_jvm_attempts': progress['valid_jvm_attempts'],
        'invalid_setup_plans': len(invalid),
        'invalid_setup_jvm_attempts': progress['invalid_setup_jvm_attempts'],
        'verified_archived_traces': len(archives),
        'interrupted_uncredited_jvm_attempts': len(archives) - progress['jvm_attempts'],
        'actor_correlated_applied_alias_writes': applied_writes,
        'cross_node_actor_correlated_alias_writes': cross_node_writes,
        'effective_runs_with_cross_node_actor_chain': runs_with_cross_node_chain,
        'jacoco_rechecked_effective_trials': len(effective),
        'junit_passes_effective': sum(row['junit_pass'] for row in effective),
        'target_exception_candidates': progress['target_exception_candidates'],
        'fault_count_distribution': dict(sorted(Counter(
            str(row['applied_faults']) for row in effective).items())),
        'max_applied_faults': progress['max_applied_faults'],
        'production_probe_gain': progress['production_probe_gain'],
        'io_family_gain': progress['io_family_gain'],
        'cumulative_valid_trial_seconds': progress['elapsed_seconds'],
        'original_source_revision': 'e27f44e3d78dfcec230c97e0a1240e3751daeff9',
    }
    output = CAMPAIGN / 'final-audit.json'
    temporary = output.with_name(output.name + '.tmp')
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    temporary.replace(output)
    return result


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, sort_keys=True))
