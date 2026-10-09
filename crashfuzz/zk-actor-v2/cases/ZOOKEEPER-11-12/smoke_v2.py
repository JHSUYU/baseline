#!/usr/bin/env python3
"""Offline receipts regress old wrong-peer and wrong-file selector drift."""

from pathlib import Path

from build_adapter import BUILD
from calibrate_v2 import CHECKS, rows, selector
from campaign_v2 import audit_actors, selected_target, strict_plan


def main():
    trace = rows(BUILD / 'offline-events.tsv')
    audit = audit_actors(trace)
    site = 'QuorumPeer#readLongFromFile:2186:FileReader'
    plan = [site + '@@peer:0@@file:currentEpoch:op:read@@1']
    if strict_plan(trace, plan) != (True, ''):
        raise AssertionError('selected original receiver/file did not apply once')
    matched = [(seq, fields) for seq, kind, fields in trace if kind == 'FAULT_APPLIED']
    if len(matched) != 1 or selector(matched[0][1]) != plan[0]:
        raise AssertionError('wrong peer or file consumed the fault')
    earlier = [(seq, fields) for seq, kind, fields in trace if kind == 'IO' and seq < matched[0][0]]
    if not any(fields[1] == 'peer:1' and fields[2] == 'file:currentEpoch:op:read'
               for _, fields in earlier):
        raise AssertionError('wrong-peer call was not exercised before selected peer0')
    if not any(fields[1] == 'peer:0' and fields[2] in (
            'file:acceptedEpoch:op:read', 'file:currentEpoch.tmp:op:read')
               for _, fields in earlier):
        raise AssertionError('wrong-file calls were not exercised before selected file')
    for case in CHECKS:
        if len(selected_target(trace, case, '0', matched[0][0])) != 1 or \
                selected_target(trace, case, '1', matched[0][0]):
            raise AssertionError(case + ' accepted a sibling target guard')
    if audit['bound_io'] != 4:
        raise AssertionError('raw file-owner audit missed a bound I/O')
    # Three peers can emit between the selected I/O and its controller receipt.
    # Validate the same-thread order, rather than global adjacent sequence IDs.
    selected = [site, 'peer:0', 'file:currentEpoch:op:read', '1', '0', '', '', 'peer0-thread']
    sibling = [site, 'peer:1', 'file:currentEpoch:op:read', '1', '1', '', '', 'peer1-thread']
    interleaved = [(1, 'IO', selected), (2, 'IO', sibling),
                   (3, 'FAULT_MATCHED', selected), (4, 'FAULT_APPLIED', selected)]
    if strict_plan(interleaved, plan) != (True, ''):
        raise AssertionError('interleaved peer broke exact same-thread fault receipt')
    wrong_thread = interleaved[:-1] + [(4, 'FAULT_APPLIED', selected[:-1] + ['peer1-thread'])]
    if strict_plan(wrong_thread, plan)[0]:
        raise AssertionError('wrong-thread applied receipt was accepted')
    print('ZK1112_V2_OFFLINE_CAMPAIGN_OK wrong_peer_wrong_file_target_fail_closed')


if __name__ == '__main__':
    main()
