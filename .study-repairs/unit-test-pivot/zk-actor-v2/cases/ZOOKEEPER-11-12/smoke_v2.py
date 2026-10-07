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
    print('ZK1112_V2_OFFLINE_CAMPAIGN_OK wrong_peer_wrong_file_target_fail_closed')


if __name__ == '__main__':
    main()
