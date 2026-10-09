#!/usr/bin/env python3
"""Recompute SOLR-01 V2 claims from saved plans, traces, and JUnit receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
STATE = HERE / 'campaign/state.json'
OUTPUT = HERE / 'campaign/raw-audit.json'
ACTOR = 'CLIENT/CloudHttp2SolrClientTest.httpBasedCloudSolrClient'
SITE = 'BaseHttpClusterStateProvider.getAliases:247'
RESOURCE = '/admin/collections?action=LISTALIASES'
FIELDS = ('actorKey', 'destinationKey', 'siteId', 'resource',
          'callOrdinal', 'attemptOrdinal', 'kind')


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def details(row: dict) -> dict[str, str]:
    return dict(part.split('=', 1) for part in row['detail'].split(';') if '=' in part)


def plan(path: Path) -> list[dict]:
    values = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
    return [{field: (int(values[f'step.{index}.{field}'])
                     if field in ('callOrdinal', 'attemptOrdinal')
                     else values[f'step.{index}.{field}']) for field in FIELDS}
            for index in range(1, int(values['count']) + 1)]


def matches(row: dict, planned: dict) -> bool:
    if any(row[field] != planned[field] for field in FIELDS[:1] + FIELDS[2:-1]):
        return False
    destination = planned['destinationKey']
    return (row['destinationKey'] == destination or
            (destination == f"JETTY/attempt{row['attemptOrdinal']}" and
             row['destinationKey'].startswith('JETTY/node')))


def audit_trial(record: dict) -> tuple[dict, list[str]]:
    number = record['number']
    folder = HERE / 'campaign' / f'trial-{number:03d}'
    errors: list[str] = []
    local = json.loads((folder / 'trial.json').read_text())
    if local != record:
        errors.append('atomic checkpoint differs from trial receipt')
    planned = plan(folder / 'fault.properties')
    if planned != record['sequence']:
        errors.append('saved fault plan differs from checkpoint')
    rows = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines()
            if line.strip()]
    by_seq = {row['seq']: row for row in rows}
    bindings = {details(row).get('providerIdentity'): details(row).get('clientIdentity')
                for row in rows if row['event'] == 'CLIENT_BIND'}
    node_bindings = {details(row).get('nodeName'): row['destinationKey']
                     for row in rows if row['event'] == 'NODE_BIND'}
    applied = [row for row in rows if row['event'] == 'IO_APPLIED']
    summary = [row for row in rows if row['event'] == 'SUMMARY']
    exact = (len(applied) == len(planned) and len(summary) == 1 and
             summary[0]['detail'] == f'applied={len(planned)}/{len(planned)}')
    actor_keys: set[tuple[str, str, int, int]] = set()
    actual_nodes: set[str] = set()
    for index, row in enumerate(applied):
        fields = details(row)
        previous = by_seq.get(row['seq'] - 1)
        if index >= len(planned) or not matches(row, planned[index]):
            exact = False
        if (previous is None or previous['event'] != 'IO_OBSERVED' or
                any(previous[field] != row[field] for field in FIELDS[:-1])):
            exact = False
        if (fields.get('planStep') != str(index + 1) or index >= len(planned) or
                fields.get('kind') != planned[index]['kind']):
            exact = False
        if (row['actorKey'] != ACTOR or row['siteId'] != SITE or row['resource'] != RESOURCE or
                bindings.get(fields.get('providerIdentity')) != fields.get('clientIdentity') or
                node_bindings.get(fields.get('nodeName')) != row['destinationKey']):
            exact = False
        node = fields.get('nodeName', '')
        base = fields.get('baseUrl', '')
        if '_solr' not in node or base not in (
                'http://' + node.replace('_solr', '/solr'),
                'https://' + node.replace('_solr', '/solr')):
            exact = False
        actual_nodes.add(node)
        actor_keys.add((fields.get('providerIdentity', ''), fields.get('clientIdentity', ''),
                        row['threadId'], row['callOrdinal']))
    if applied and (len(actor_keys) != 1 or len(actual_nodes) != len(applied)):
        exact = False
    if exact != record['exact_injection']:
        errors.append(f'exact injection raw={exact} recorded={record["exact_injection"]}')
    after = thrown = False
    if exact:
        provider, client, _, call = next(iter(actor_keys))
        checks = [row for row in rows if row['event'] == 'TARGET_CHECK'
                  and row['seq'] > applied[-1]['seq'] and row['actorKey'] == ACTOR
                  and row['callOrdinal'] == call and
                  details(row).get('providerIdentity') == provider and
                  details(row).get('clientIdentity') == client]
        after = bool(checks)
        thrown = any(by_seq.get(check['seq'] + 1, {}).get('event') == 'TARGET_THROW'
                     for check in checks)
    if after != record['target_after_fault'] or thrown != record['target_exception']:
        errors.append('post-fault target or selected throw differs from raw')
    if (exact and after) != record['effective']:
        errors.append('effective trial differs from raw')
    run = json.loads((folder / 'run.json').read_text())
    if (run['exit_code'] != record['junit_exit'] or
            run['elapsed_seconds'] != record['elapsed_seconds']):
        errors.append('JUnit outcome or duration differs from receipt')
    hashes = {name: digest(folder / name) for name in
              ('events.jsonl', 'jacoco.exec', 'junit.log', 'fault.properties', 'run.json')}
    if record['effective'] and hashes['jacoco.exec'] is None:
        errors.append('effective trial lacks JaCoCo raw')
    return {'number': number, 'exact_from_raw': exact, 'effective_from_raw': exact and after,
            'target_exception_from_raw': thrown, 'applied_from_raw': len(applied),
            'concrete_nodes': sorted(actual_nodes), 'hashes': hashes}, errors


def main() -> None:
    state = json.loads(STATE.read_text())
    if not state.get('stopped'):
        raise RuntimeError('audit requires a completed atomic V2 campaign')
    records = state['trials']
    errors: list[str] = []
    if [row['number'] for row in records] != list(range(1, len(records) + 1)):
        errors.append('trial numbering is discontinuous')
    rows = []
    for record in records:
        audited, trial_errors = audit_trial(record)
        rows.append(audited)
        errors.extend(f"trial {record['number']}: {error}" for error in trial_errors)
    report = {'case_id': 'SOLR-01', 'identity_version': 'actor-v2',
              'attempts': len(rows),
              'strict_from_raw': sum(row['exact_from_raw'] for row in rows),
              'valid_from_raw': sum(row['effective_from_raw'] for row in rows),
              'target_exceptions_from_raw': sum(row['effective_from_raw'] and
                                                row['target_exception_from_raw'] for row in rows),
              'errors': errors, 'trials': rows}
    temporary = OUTPUT.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    temporary.replace(OUTPUT)
    print(json.dumps({key: report[key] for key in
                      ('attempts', 'strict_from_raw', 'valid_from_raw',
                       'target_exceptions_from_raw', 'errors')}, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
