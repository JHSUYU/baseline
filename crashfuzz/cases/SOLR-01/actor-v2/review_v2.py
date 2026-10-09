#!/usr/bin/env python3
"""Classify selected SOLR-01 throws against the original endpoint fallback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
STATE = HERE / 'campaign/state.json'
OUTPUT = HERE / 'campaign/candidate-review.json'
SOURCE = (HERE.parent / 'independent/solr-source/solr/solrj/src/java/org/apache/'
          'solr/client/solrj/impl/BaseHttpClusterStateProvider.java')
ACTOR = 'CLIENT/CloudHttp2SolrClientTest.httpBasedCloudSolrClient'


def detail(row: dict) -> dict[str, str]:
    return dict(part.split('=', 1) for part in row['detail'].split(';') if '=' in part)


def review(trial: dict) -> dict:
    folder = HERE / 'campaign' / f"trial-{trial['number']:03d}"
    rows = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines()
            if line.strip()]
    applied = [row for row in rows if row['event'] == 'IO_APPLIED']
    first, last = applied[0], applied[-1]
    raw_provider = detail(first)['providerIdentity']
    raw_client = detail(first)['clientIdentity']
    call = first['callOrdinal']
    enters = [row for row in rows if row['event'] == 'TARGET_ENTER'
              and row['seq'] < first['seq'] and row['actorKey'] == ACTOR
              and row['threadId'] == first['threadId']
              and detail(row).get('providerIdentity') == raw_provider]
    if not enters:
        raise RuntimeError(f"trial {trial['number']}: no selected call entry")
    enter = enters[-1]
    live = detail(enter).get('liveNodes', '')
    if not (live.startswith('[') and live.endswith(']')):
        raise RuntimeError(f"trial {trial['number']}: malformed live-node snapshot")
    live_nodes = {name.strip() for name in live[1:-1].split(',') if name.strip()}
    failed_nodes = {detail(row).get('nodeName') for row in applied}
    checks = [row for row in rows if row['event'] == 'TARGET_CHECK'
              and row['seq'] > last['seq'] and row['callOrdinal'] == call
              and detail(row).get('providerIdentity') == raw_provider
              and detail(row).get('clientIdentity') == raw_client]
    throws = [row for row in rows if row['event'] == 'TARGET_THROW'
              and any(row['seq'] == check['seq'] + 1 for check in checks)]
    log = (folder / 'junit.log').read_text(errors='replace')
    expected = (trial['effective'] and trial['target_exception']
                and bool(live_nodes) and live_nodes == failed_nodes
                and len(failed_nodes) == len(applied)
                and len(throws) == 1
                and detail(checks[-1]).get('failed') == 'true'
                and throws[0]['detail'] == 'expected_all_live_nodes_failed'
                and 'SOLR01_JUNIT_FAILURE testAliasHandling' in log
                and 'Tried fetching aliases using all the node names we knew of' in log)
    return {
        'trial': trial['number'], 'source_callsite': 'BaseHttpClusterStateProvider.getAliases:267',
        'client_identity': raw_client, 'provider_identity': raw_provider,
        'call_ordinal': call, 'live_nodes': sorted(live_nodes),
        'faulted_nodes': sorted(failed_nodes), 'all_live_endpoints_faulted': expected,
        'fault_kinds': [detail(row).get('kind') for row in applied],
        'junit_exit': trial['junit_exit'],
    }


def main() -> None:
    state = json.loads(STATE.read_text())
    if not state.get('stopped'):
        raise RuntimeError('candidate review requires a completed campaign')
    source = SOURCE.read_text()
    if ('for (String nodeName: liveNodes)' not in source or
            'Tried fetching aliases using all the node names we knew of' not in source):
        raise RuntimeError('original source no longer has the reviewed fallback')
    candidates = [review(trial) for trial in state['trials']
                  if trial['effective'] and trial['target_exception']]
    non_target_failures = [trial['number'] for trial in state['trials']
                           if trial['junit_exit'] != 0 and not trial['target_exception']]
    report = {
        'case_id': 'SOLR-01', 'source_revision':
            json.loads((HERE / 'build-receipt.json').read_text())['source_revision'],
        'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'attempts': len(state['trials']), 'effective':
            sum(trial['effective'] for trial in state['trials']),
        'selected_throws': len(candidates),
        'expected_all_endpoints_failed': sum(item['all_live_endpoints_faulted']
                                             for item in candidates),
        'non_target_junit_failures': non_target_failures,
        'new_bug_confirmed': False,
        'classification': 'expected original all-live-endpoints-failed fallback'
            if all(item['all_live_endpoints_faulted'] for item in candidates)
            else 'unresolved candidate(s): inspect individually',
        'candidates': candidates,
    }
    temporary = OUTPUT.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    temporary.replace(OUTPUT)
    print(json.dumps({key: report[key] for key in
                      ('attempts', 'effective', 'selected_throws',
                       'expected_all_endpoints_failed', 'non_target_junit_failures',
                       'classification')}, sort_keys=True))
    if report['expected_all_endpoints_failed'] != report['selected_throws']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
