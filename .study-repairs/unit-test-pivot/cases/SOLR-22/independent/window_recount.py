#!/usr/bin/env python3
"""Audit the exact onCommit latest-to-known interval from raw case-local events.

Directory events have no policyId, so they join a window by its writer thread.
Target checks join by policyId and logical core even on a different thread: that
concurrent read is the suspected coordination window. Incomplete windows only
establish that a fault fired before unwinding; later events are excluded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def recount(path: Path) -> dict:
    active: dict[tuple[int, str], dict] = {}
    complete: list[dict] = []
    incomplete: list[dict] = []
    for text in path.open():
        if not text.strip():
            continue
        event = json.loads(text)
        kind = event['event']
        key = (event['threadId'], event.get('policyId'))
        if kind == 'ONCOMMIT_WINDOW_START':
            if key in active:
                incomplete.append(active.pop(key))
            active[key] = {'start': event['seq'], 'end': None, 'threadId': key[0],
                           'policyId': key[1], 'sourceKey': event.get('sourceKey'),
                           'io': [], 'applied': [], 'checks': []}
        elif kind in ('ONCOMMIT_WINDOW_END', 'ONCOMMIT_RETURN'):
            window = active.pop(key, None)
            if window is not None:
                window['end'] = event['seq']
                (complete if kind == 'ONCOMMIT_WINDOW_END' else incomplete).append(window)
        elif kind == 'FAULT_POINT_OBSERVED':
            for (thread, _), window in active.items():
                if thread == event['threadId']:
                    window['io'].append(event['seq'])
                    if event.get('applied'):
                        window['applied'].append(event['seq'])
        elif kind == 'TARGET_CHECK':
            for (_, policy), window in active.items():
                if (policy is not None and policy == event.get('policyId')
                    and window['sourceKey'] == event.get('sourceKey')):
                    window['checks'].append(event['seq'])
    incomplete.extend(active.values())
    return {
        'trace': str(path),
        'rule': 'writer thread for Directory; same policy and logical core across threads for target; '
                'incomplete windows count applied faults only',
        'complete_windows': len(complete),
        'incomplete_windows': len(incomplete),
        'directory_io_in_complete_windows': len({x for w in complete for x in w['io']}),
        'applied_faults_in_window': len({x for w in complete + incomplete for x in w['applied']}),
        'target_checks_in_complete_windows': len({x for w in complete for x in w['checks']}),
        'incomplete_window_applied_faults': len({x for w in incomplete for x in w['applied']}),
        'window_details': complete + incomplete,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('traces', nargs='+', type=Path)
    args = parser.parse_args()
    for path in args.traces:
        result = recount(path)
        result['window_details'] = [w for w in result['window_details']
                                    if w['applied'] or w['checks'] or w['io']]
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
