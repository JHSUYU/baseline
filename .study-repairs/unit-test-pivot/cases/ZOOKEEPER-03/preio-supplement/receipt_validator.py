#!/usr/bin/env python3
"""Offline ordered-plan and target-actor/relation validation for V2 TSV events."""

import argparse
import json
from pathlib import Path


class ReceiptError(ValueError):
    pass


def parse_events(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        fields = line.split('\t')
        if len(fields) < 3:
            raise ReceiptError('short event')
        rows.append((int(fields[0]), fields[1], fields[2:]))
    return sorted(rows)


def fault_selector(fields):
    if len(fields) < 7 or not fields[1] or not fields[2]:
        raise ReceiptError('fault lacks bound actor/resource')
    return '@@'.join(fields[:4])


def relation_holds(fault, target, relation):
    # fault: site, actor, resource, ordinal, local peer, counterparty peer, session tag
    # target: check, actor, role, peer, session tag, branch
    if relation in ('same_peer', 'epoch_file_owner'):
        return bool(fault[4]) and fault[4] == target[3]
    if relation in ('client_to_peer', 'counterparty_to_peer'):
        return bool(fault[5]) and fault[5] == target[3]
    if relation == 'same_session':
        return bool(fault[6]) and fault[6] == target[4]
    raise ReceiptError('unknown relation ' + relation)


def validate_rows(rows, contract):
    plan = contract['plan']
    relations = contract['fault_relations']
    if len(plan) != len(relations):
        raise ReceiptError('plan and relation lengths differ')
    applied = [(seq, fields) for seq, kind, fields in rows if kind == 'FAULT_APPLIED']
    matched = [(seq, fields) for seq, kind, fields in rows if kind == 'FAULT_MATCHED']
    if [fault_selector(fields) for _, fields in applied] != plan:
        raise ReceiptError('applied ordered actor-aware plan differs')
    if [fault_selector(fields) for _, fields in matched] != plan:
        raise ReceiptError('matched ordered actor-aware plan differs')
    if any(a[0] <= m[0] for m, a in zip(matched, applied)):
        raise ReceiptError('fault applied before matching event')
    if not applied:
        raise ReceiptError('empty plan')
    last_fault = applied[-1][0]
    intended = contract['target']
    candidates = []
    for seq, kind, fields in rows:
        if seq <= last_fault or kind != 'TARGET_GUARD' or len(fields) < 6:
            continue
        if fields[0] != intended['check'] or fields[2] != intended['role']:
            continue
        if intended.get('actor', '*') not in ('*', fields[1]):
            continue
        if intended.get('peer', '*') not in ('*', fields[3]):
            continue
        if intended.get('session_tag', '*') not in ('*', fields[4]):
            continue
        if all(relation_holds(fault, fields, relation)
               for (_, fault), relation in zip(applied, relations)):
            candidates.append((seq, fields))
    if not candidates:
        raise ReceiptError('no postfault guard with selected logical actor and fault relation')
    return {'strict': True, 'target_after_final_fault': True,
            'faults': len(applied), 'target_sequence': candidates[0][0],
            'target_actor': candidates[0][1][1]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('events')
    parser.add_argument('contract')
    args = parser.parse_args()
    print(json.dumps(validate_rows(parse_events(args.events),
                                   json.loads(Path(args.contract).read_text())),
                     sort_keys=True))


if __name__ == '__main__':
    main()
