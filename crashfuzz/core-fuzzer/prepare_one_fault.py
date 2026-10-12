#!/usr/bin/env python3
"""Choose one observed static I/O event before the first target check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fuzzer import point_from_event, write_trial


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trace', required=True, type=Path)
    parser.add_argument('--selection', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text())
    events = [json.loads(line) for line in args.trace.open() if line.strip()]
    check = next((row for row in events if row.get('event') == 'CHECK_REACHED'
                  and row.get('siteId') == selection.get('target_site_id')), None)
    if check is None:
        raise ValueError('healthy trace did not reach the exact selected check')
    candidates = [row for row in events if row.get('event') == 'FAULT_POINT_OBSERVED'
                  and row.get('seq', -1) < check['seq'] and point_from_event(row)]
    if not candidates:
        raise ValueError('no observed I/O before the first target check')
    preferred = ('ClientProtocol:', 'DatanodeProtocol:', 'SolrZkClient:',
                 'ZooKeeper:', 'hbase.ipc.', 'java.io.FileInputStream:')
    candidates.sort(key=lambda row: (
        any(value in row.get('sourceKey', '') for value in preferred),
        row.get('seq', -1)))
    selected = candidates[-1]
    point = point_from_event(selected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_trial(args.output, [point], {'method': selection['target_method'],
                                      'site_id': selection['target_site_id']})
    print(json.dumps({'trial': str(args.output), 'point': point,
                      'observed_seq': selected['seq'], 'first_check_seq': check['seq']}),
          flush=True)


if __name__ == '__main__':
    main()
