#!/usr/bin/env python3
"""Require two new original JUnit healthy runs and audit runtime actor joins."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from build_v2 import HERE, sha
from run_v2 import AGENT, run, verify_build

# Retain previous JUnit runs as raw diagnostics. The relative-attempt matcher
# changes agent bytecode, so these two new runs calibrate its exact build.
SEEDS = (HERE / 'healthy-07', HERE / 'healthy-08')
ACTOR = 'CLIENT/CloudHttp2SolrClientTest.httpBasedCloudSolrClient'
SITE = 'BaseHttpClusterStateProvider.getAliases:247'
RESOURCE = '/admin/collections?action=LISTALIASES'


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def detail(value: str) -> dict[str, str]:
    return dict(part.split('=', 1) for part in value.split(';') if '=' in part)


def audit(rows: list[dict]) -> dict:
    bindings: dict[str, str] = {}
    clients: dict[str, str] = {}
    for row in rows:
        if row['event'] == 'NODE_AMBIGUOUS':
            raise RuntimeError('ambiguous Jetty node binding')
        if row['event'] == 'NODE_BIND':
            node = detail(row['detail']).get('nodeName')
            role = row['destinationKey']
            if not node or not role.startswith('JETTY/node'):
                raise RuntimeError('incomplete Jetty node binding')
            if node in bindings and bindings[node] != role:
                raise RuntimeError('one live node mapped to multiple roles')
            bindings[node] = role
        if row['event'] == 'CLIENT_BIND':
            fields = detail(row['detail'])
            if row['actorKey'] != ACTOR or not fields.get('providerIdentity'):
                raise RuntimeError('incomplete selected-client binding')
            prior = clients.setdefault(fields['providerIdentity'], fields['clientIdentity'])
            if prior != fields['clientIdentity']:
                raise RuntimeError('provider bound to multiple CloudHttp2SolrClients')
    if set(bindings.values()) != {'JETTY/node1', 'JETTY/node2', 'JETTY/node3'}:
        raise RuntimeError('original 3-Jetty roles not all observed')
    if len(clients) != 1:
        raise RuntimeError('selected HTTP client/provider is not unique')
    selected_requests = [row for row in rows if row['event'] == 'REQUEST_ENTER'
                         and row['actorKey'] == ACTOR]
    for row in selected_requests:
        fields = detail(row['detail'])
        if clients.get(fields.get('providerIdentity')) != fields.get('clientIdentity'):
            raise RuntimeError('request receiver contradicts selected client/provider')
    io = [row for row in rows if row['event'] == 'IO_OBSERVED']
    entries = [row for row in rows if row['event'] == 'TARGET_ENTER']
    checks = [row for row in rows if row['event'] == 'TARGET_CHECK']
    if not io or not entries or not checks or len(entries) != len(checks):
        raise RuntimeError('healthy alias provider call, IO, or target check absent')
    active: dict[int, str] = {}
    for row in rows:
        if row['event'] not in ('TARGET_ENTER', 'IO_OBSERVED', 'TARGET_CHECK'):
            continue
        fields = detail(row['detail'])
        provider = fields.get('providerIdentity')
        if row['actorKey'] != ACTOR or provider not in clients:
            raise RuntimeError('alias operation came from another provider')
        thread = row['threadId']
        if row['event'] == 'TARGET_ENTER':
            if thread in active:
                raise RuntimeError('overlapping alias provider calls on one thread')
            active[thread] = provider
        elif active.get(thread) != provider:
            raise RuntimeError('alias IO/check not inside the bound provider call')
        elif row['event'] == 'TARGET_CHECK':
            if fields.get('clientIdentity') != clients[provider]:
                raise RuntimeError('target check contradicts selected client binding')
            del active[thread]
    if active:
        raise RuntimeError('healthy alias provider call lacked a target check')
    for row in io:
        fields = detail(row['detail'])
        if (row['actorKey'] != ACTOR or row['siteId'] != SITE or
                row['resource'] != RESOURCE or
                bindings.get(fields.get('nodeName')) != row['destinationKey'] or
                clients.get(fields.get('providerIdentity')) != fields.get('clientIdentity')):
            raise RuntimeError('alias IO contradicts selected provider or destination role')
        if row['applied']:
            raise RuntimeError('healthy seed applied a fault')
    if any(row['event'] == 'TARGET_THROW' for row in rows):
        raise RuntimeError('healthy target unexpectedly threw')
    summary = [row for row in rows if row['event'] == 'SUMMARY']
    if len(summary) != 1 or summary[0]['detail'] != 'applied=0/0':
        raise RuntimeError('healthy trace incomplete')
    return {'nodes': bindings, 'client_provider': clients,
            'selected_request_count': len(selected_requests), 'io_count': len(io),
            'provider_enter_count': len(entries), 'check_count': len(checks)}


def locked_hashes() -> dict[str, str]:
    names = ('build_v2.py', 'run_v2.py', 'calibrate_v2.py', 'campaign_v2.py',
             'smoke_v2.py', 'build-receipt.json')
    return {name: sha(HERE / name) for name in names}


def calibrate() -> dict:
    receipt = verify_build()
    results = []
    for seed in SEEDS:
        metadata = json.loads((seed / 'run.json').read_text())
        if metadata['exit_code'] != 0 or metadata['plan'] is not None:
            raise RuntimeError(f'original healthy JUnit did not pass: {seed}')
        if metadata['agent_sha256'] != receipt['agent_sha256']:
            raise RuntimeError('healthy seed used a different agent')
        rows = events(seed / 'events.jsonl')
        results.append({'trace_sha256': sha(seed / 'events.jsonl'),
                        'jacoco_sha256': sha(seed / 'jacoco.exec'),
                        'audit': audit(rows)})
    if set(results[0]['audit']['nodes'].values()) != set(results[1]['audit']['nodes'].values()):
        raise RuntimeError('stable Jetty role set changed between healthy runs')
    if results[0]['trace_sha256'] == results[1]['trace_sha256']:
        raise RuntimeError('healthy runs must be two independent fresh executions')
    result = {'case_id': 'SOLR-01', 'test': receipt['test'],
              'agent_sha256': sha(AGENT), 'runner_hashes': locked_hashes(),
              'healthy': results}
    temporary = HERE / 'calibration-receipt.json.tmp'
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    temporary.replace(HERE / 'calibration-receipt.json')
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> None:
    verify_build()
    for seed in SEEDS:
        if not (seed / 'run.json').exists():
            run(seed)
    calibrate()


if __name__ == '__main__':
    main()
