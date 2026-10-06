#!/usr/bin/env python3
"""Independently recheck campaign claims against raw JVM outputs."""

import json
import os
from pathlib import Path
import re

from campaign import CHECKPOINT, HERE, ROOT, events, selector


def main():
    state = json.loads(CHECKPOINT.read_text())
    findings = []
    for trial in state['trials']:
        trace = events(trial['run_id'])
        matches = [x for x in trace if x[1] == 'FAULT_MATCHED']
        applied = [x for x in trace if x[1] == 'FAULT_APPLIED']
        observed_matches = [selector(x) for x in matches]
        observed_applied = [selector(x) for x in applied]
        exact = observed_matches == trial['plan'] and observed_applied == trial['plan']
        last_fault = applied[-1][0] if applied else 0
        guards = [x for x in trace if x[1] == 'TARGET_GUARD' and x[0] > last_fault]
        throws = [x for x in trace if x[1] == 'TARGET_THROW' and x[0] > last_fault]
        entries = [x for x in trace if x[1] == 'TARGET_ENTRY']
        log = (ROOT / trial['run_id'] / 'junit.log').read_text(errors='replace')
        created = re.search(r'global session created 0x([0-9a-f]+)', log)
        created_session = created.group(1) if created else None
        contexts = []
        for x in throws:
            entry = next((e for e in reversed(entries) if e[0] < x[0] and e[2] == x[2]), None)
            session = entry[3][0] if entry and entry[3] else None
            contexts.append({
                'event_seq': x[0], 'thread': x[2],
                'exception_class': x[3][1] if len(x[3]) > 1 else None,
                'disconnect_reason_from_exception': x[3][2] if len(x[3]) > 3 else None,
                'message': x[3][3] if len(x[3]) > 3 else (x[3][2] if len(x[3]) > 2 else None),
                'session_id_hex': session,
                'same_created_global_session': session == created_session if session and created_session else None,
                'remote_at_entry': entry[3][1] if entry and len(entry[3]) > 1 else None,
            })
        findings.append({
            'run_id': trial['run_id'], 'plan': trial['plan'],
            'matched': observed_matches, 'applied': observed_applied,
            'strict_recomputed': exact,
            'target_after_final_fault_recomputed': bool(exact and guards),
            'target_throw_after_fault_count_recomputed': len(throws),
            'healthy_target_throw_count': 9,
            'created_global_session_id_hex': created_session,
            'target_exception_contexts': contexts,
            'all_observed_target_exceptions_match_source': all(
                x['exception_class'] == 'org.apache.zookeeper.server.ServerCnxn$CloseRequestException'
                and x['disconnect_reason_from_exception'] in (None, 'RENEW_GLOBAL_SESSION_IN_RO_MODE')
                for x in contexts),
            'ledger_consistent': exact == trial['strict_injection']
            and bool(exact and guards) == trial['target_after_final_fault'],
        })
    result = {
        'source_check': 'ReadOnlyZooKeeperServer.validateSession:123-126',
        'source_exception': 'ServerCnxn.CloseRequestException(RENEW_GLOBAL_SESSION_IN_RO_MODE)',
        'healthy_exception_expected': True,
        'completed_trials': len(findings),
        'all_ledger_claims_consistent': all(x['ledger_consistent'] for x in findings),
        'findings': findings,
    }
    path = HERE / 'source-audit.json'
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)
    print('audited', len(findings), 'trials; ledger consistent:', result['all_ledger_claims_consistent'])


if __name__ == '__main__':
    main()
