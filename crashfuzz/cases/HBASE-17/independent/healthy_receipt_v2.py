#!/usr/bin/env python3
"""Validate the two unchanged original-JUnit V2 seeds before mutation."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from campaign_v2 import LOGS, available_io, eligible_selector, parse_log, site


def seed_receipt(name):
    log = LOGS / (name + '.log')
    raw = log.read_bytes()
    trace = parse_log(log)
    assert trace['junit'] == {'found': 1, 'succeeded': 1, 'failed': 0}, name
    assert trace['b5'] and all(event['outcome'] for event in trace['b5']), name
    assert not trace['matched'] and not trace['applied'], name
    assert len(trace['role_maps']) == len(trace['initial_owner']) == 1, name
    source, destination, third, region, verified = trace['role_maps'][0]
    assert len({source, destination, third}) == 3, name
    assert region == 'Report_ROOT_r0' and verified == 'true', name
    assert trace['initial_owner'][0] == (source, region), name
    before_b5 = [event for event in trace['io']
                 if event['line'] < trace['b5'][-1]['line']]
    candidate_events = available_io(trace)
    assert any('#OPEN_Report_ROOT_r0~' in event['selector']
               for event in candidate_events), name
    assert any('#CLOSE_Report_ROOT_r0~' in event['selector']
               for event in candidate_events), name
    lines = raw.decode(errors='replace').splitlines()
    identity_errors = []
    role_peers = {'INITIAL_OWNER': source, 'SOURCE_RS': source,
                  'MOVE_DEST_RS': destination, 'THIRD_RS': third}
    for event in candidate_events:
        selector = event['selector']
        if not selector.startswith('RPC_'):
            continue
        role = selector.rsplit('~', 2)[-2].rsplit('@', 1)[-1]
        peer_match = re.search(r' peer=(\S+)', lines[event['line'] - 1])
        peer = peer_match.group(1) if peer_match else None
        if role in role_peers and peer != role_peers[role]:
            identity_errors.append({'selector': selector, 'peer': peer,
                                    'expected': role_peers[role]})
        if role == 'MASTER' and not ('MasterService.' in selector
                                     or 'RegionServerStatusService.' in selector):
            identity_errors.append({'selector': selector,
                                    'reason': 'MASTER role without master RPC descriptor'})
        if role not in (*role_peers, 'MASTER'):
            identity_errors.append({'selector': selector,
                                    'reason': 'unsupported actor role'})
    assert not identity_errors, json.dumps(identity_errors)
    excluded = Counter()
    for event in before_b5:
        selector = event['selector']
        if '@PREMOVE' in selector:
            excluded['premove'] += 1
        if '@UNKNOWN_PEER' in selector:
            excluded['unknown_peer'] += 1
        if 'UNKNOWN' in selector and '@UNKNOWN_PEER' not in selector:
            excluded['unknown_resource_or_operation'] += 1
        if not eligible_selector(selector):
            excluded['not_candidate'] += 1
    sites = sorted({site(event['selector']) for event in candidate_events})
    selectors = sorted({event['selector'] for event in candidate_events})
    return {'name': name, 'sha256': hashlib.sha256(raw).hexdigest(),
            'elapsed_seconds': trace['elapsed_seconds'], 'junit': trace['junit'],
            'exact_b5': trace['b5'],
            'region_plan': {'source': source, 'move_destination': destination,
                            'third': third, 'target_region_resource': region,
                            'initial_owner': trace['initial_owner'][0][0],
                            'initial_owner_is_source': verified == 'true',
                            'rs_addresses_distinct': True},
            'before_b5_io_events': len(before_b5),
            'candidate_io_events': len(candidate_events),
            'candidate_stable_sites': sites,
            'candidate_exact_selectors': selectors,
            'candidate_event_types': dict(Counter(
                event['selector'].split('~', 1)[0] for event in candidate_events)),
            'excluded_before_b5_event_counts': dict(excluded),
            'validated_actor_peers': len(candidate_events) - sum(
                not event['selector'].startswith('RPC_') for event in candidate_events),
            'identity_errors': identity_errors}


def main():
    a, b = seed_receipt('seed_v2c'), seed_receipt('seed_v2d')
    common_sites = sorted(set(a['candidate_stable_sites']) &
                          set(b['candidate_stable_sites']))
    common_selectors = sorted(set(a['candidate_exact_selectors']) &
                              set(b['candidate_exact_selectors']))
    assert common_sites and common_selectors
    out = {'source_junit':
           'org.apache.hadoop.hbase.master.assignment.'
           'TestReportRegionStateTransitionFromDeadServer.test',
           'probe': 'case-local ByteBuddy HBase17FuzzAgentV2; no GraphChecker skeleton',
           'target': 'TransitRegionStateProcedure.confirmClosed B5 '
                     'assert regionNode.isInState(ABNORMALLY_CLOSED)',
           'seeds': [a, b],
           'common_stable_sites': common_sites,
           'common_stable_site_count': len(common_sites),
           'common_exact_selectors': common_selectors,
           'common_exact_selector_count': len(common_selectors),
           'master_role_rule': 'RPC service descriptor MasterService or '
                               'RegionServerStatusService',
           'unknown_peer_rule': 'UNKNOWN_PEER is observed but excluded from candidate queue',
           'premove_rule': 'PREMOVE excluded except exact target-region first OPEN '
                           'validated as INITIAL_OWNER==SOURCE_RS by RegionPlan',
           'unknown_resource_rule': 'UNKNOWN resource or operation excluded from candidate queue',
           'candidate_fault_types': ['RPC_REQUEST: IO, CONNECT',
                                     'RPC_RESPONSE: IO, TIMEOUT', 'META_PUT: IO'],
           'valid_for_v2_seed': True}
    (Path(__file__).parent / 'healthy_receipt_v2.json').write_text(
        json.dumps(out, indent=2) + '\n')
    print('HEALTHY_RECEIPT common_sites=%d common_selectors=%d '
          'candidate_events=%d,%d' %
          (len(common_sites), len(common_selectors),
           a['candidate_io_events'], b['candidate_io_events']))


if __name__ == '__main__':
    main()
