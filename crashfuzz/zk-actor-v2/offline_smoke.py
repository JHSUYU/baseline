#!/usr/bin/env python3
"""Compile and run the V2 registry/probe contract without starting ZooKeeper."""

import json
from pathlib import Path
import subprocess
import tempfile

from receipt_validator import ReceiptError, parse_events, validate_rows


ROOT = Path(__file__).resolve().parent
PLAN = [
    'site.client.write@@client:creatorCloser:session:original@@peer:0:channel:1:op:write@@1',
    'site.file.sync@@peer:0@@file:currentEpoch:op:sync@@1',
]
CONTRACT = {
    'plan': PLAN,
    'fault_relations': ['client_to_peer', 'epoch_file_owner'],
    'target': {'check': 'check.session', 'actor': 'peer:0', 'role': 'leader',
               'peer': '0', 'session_tag': 'original'},
}


def main():
    with tempfile.TemporaryDirectory(prefix='zk-actor-v2-smoke-') as scratch:
        scratch = Path(scratch)
        classes = scratch / 'classes'
        classes.mkdir()
        sources = sorted(str(path) for path in (ROOT / 'src').rglob('*.java'))
        subprocess.run(['javac', '-d', str(classes), *sources], check=True)
        events = scratch / 'events.tsv'
        subprocess.run(['java', '-cp', str(classes),
                        '-Dzk.actor.plan=' + '|||'.join(PLAN),
                        'research.zkactor.OfflineSmoke', str(events), str(scratch)],
                       check=True)
        rows = parse_events(events)
        result = validate_rows(rows, CONTRACT)
        assert result['faults'] == 2 and result['target_actor'] == 'peer:0'
        assert sum(kind == 'UNBOUND_IO' for _, kind, _ in rows) == 3
        assert sum(kind == 'FAULT_APPLIED' for _, kind, _ in rows) == 2

        bad_target = json.loads(json.dumps(CONTRACT))
        bad_target['target']['actor'] = 'peer:1'
        try:
            validate_rows(rows, bad_target)
        except ReceiptError:
            pass
        else:
            raise AssertionError('wrong target actor was accepted')

        bad_relation = json.loads(json.dumps(CONTRACT))
        bad_relation['fault_relations'][0] = 'same_peer'
        try:
            validate_rows(rows, bad_relation)
        except ReceiptError:
            pass
        else:
            raise AssertionError('wrong cross-peer relation was accepted')
        print(json.dumps({'status': 'pass', 'applied': 2, 'unbound_excluded': 3,
                          'wrong_target_rejected': True,
                          'wrong_relation_rejected': True}, sort_keys=True))


if __name__ == '__main__':
    main()
