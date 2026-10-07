#!/usr/bin/env python3
"""Recount same-core Directory I/O and same-policy checks in each onCommit interval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def audit(trace: Path) -> dict:
    active: dict[tuple[int, str], dict] = {}
    completed = []
    incomplete = []
    for line in trace.open():
        if not line.strip():
            continue
        event = json.loads(line)
        kind = event['event']
        key = (event['threadId'], event.get('policyId'))
        if kind == 'ONCOMMIT_WINDOW_START':
            active[key] = {'threadId': key[0], 'policyId': key[1],
                           'sourceKey': event['sourceKey'], 'start': event['seq'],
                           'writer_io': 0, 'same_core_io': 0,
                           'same_core_other_thread_io': 0, 'same_policy_checks': 0,
                           'io_families': {}, 'io_sites': {}}
        elif kind in ('ONCOMMIT_WINDOW_END', 'ONCOMMIT_RETURN'):
            window = active.pop(key, None)
            if window is not None:
                window['end'] = event['seq']
                (completed if kind == 'ONCOMMIT_WINDOW_END' else incomplete).append(window)
        elif kind == 'FAULT_POINT_OBSERVED':
            source = event['sourceKey']
            for window in active.values():
                if event['threadId'] == window['threadId']:
                    window['writer_io'] += 1
                path = window['sourceKey']
                if path.startswith('UNRESOLVED:'):
                    continue
                if source == path or source.startswith(path + '/'):
                    window['same_core_io'] += 1
                    if event['threadId'] != window['threadId']:
                        window['same_core_other_thread_io'] += 1
                    family = event['marker']
                    window['io_families'][family] = window['io_families'].get(family, 0) + 1
                    site = event['siteId']
                    window['io_sites'][site] = window['io_sites'].get(site, 0) + 1
        elif kind == 'TARGET_CHECK':
            for window in active.values():
                if event.get('policyId') == window['policyId'] and (
                    event['sourceKey'] == window['sourceKey']
                    or window['sourceKey'].startswith('UNRESOLVED:')):
                    window['same_policy_checks'] += 1
    incomplete.extend(active.values())
    return {
        'trace': str(trace), 'complete_windows': len(completed),
        'incomplete_windows': len(incomplete),
        'resolved_complete_windows': sum(
            not w['sourceKey'].startswith('UNRESOLVED:') for w in completed),
        'writer_io_in_complete_windows': sum(w['writer_io'] for w in completed),
        'same_core_io_in_complete_windows': sum(w['same_core_io'] for w in completed),
        'same_core_other_thread_io_in_complete_windows': sum(
            w['same_core_other_thread_io'] for w in completed),
        'same_policy_checks_in_complete_windows': sum(
            w['same_policy_checks'] for w in completed),
        'complete_windows_with_same_core_io': sum(w['same_core_io'] > 0 for w in completed),
        'complete_windows_with_same_policy_checks': sum(
            w['same_policy_checks'] > 0 for w in completed),
        'overlap_windows': [w for w in completed if w['same_core_io'] or w['same_policy_checks']],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit(args.trace)
    encoded = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded)


if __name__ == '__main__':
    main()
