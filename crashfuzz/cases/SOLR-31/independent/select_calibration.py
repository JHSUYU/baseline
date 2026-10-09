#!/usr/bin/env python3
"""Select a reproducible original ZK I/O inside the force-leader check window."""

from __future__ import annotations

import json
from pathlib import Path

from build import HERE


FIELDS = ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal')


def key(point: dict) -> tuple:
    return tuple(point[field] for field in FIELDS)


def main() -> None:
    audits = [json.loads((HERE / name / 'seed-audit.json').read_text())
              for name in ('healthy-04', 'healthy-05')]
    assert all(audit['original_test_passed'] and audit['target_guard_count'] == 1
               and audit['target_throw_count'] == 0
               and audit['leader_observations'][0]['detail'] == 'leader=null'
               for audit in audits)
    assert audits[0]['agent_sha256'] == audits[1]['agent_sha256']
    points = [{key(point): point for point in audit['target_window_points']}
              for audit in audits]
    common = set(points[0]) & set(points[1])
    preferred = [identity for identity in common
                 if identity[0] == 'FAULT:ZK_NATIVE:exists'
                 and 'ZkShardTerms.registerWatcher' in identity[1]
                 and identity[3].endswith('/terms/shard1')]
    assert len(preferred) == 1, preferred
    identity = preferred[0]
    selected = [points[0][identity], points[1][identity]]
    root = HERE / 'calibration'
    root.mkdir(exist_ok=True)
    report = {
        'reason': 'Same original ZkShardTerms.registerWatcher retry-internal exists before the exact guard in two passing JUnit seeds.',
        'agent_sha256': audits[0]['agent_sha256'],
        'logical_identity': {field: value for field, value in zip(FIELDS, identity)},
        'healthy_observations': selected,
        'physical_node_is_evidence_not_selector': True,
    }
    (root / 'selection.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    plan = ['count=1']
    for field in ('siteId', 'sourceKey', 'resource', 'hitOrdinal'):
        plan.append('step.1.' + field + '=' + str(report['logical_identity'][field]))
    (root / 'fault.properties').write_text('\n'.join(plan) + '\n')
    print(json.dumps({'identity': report['logical_identity'],
                      'healthy_sequences': [point['seq'] for point in selected]}, sort_keys=True))


if __name__ == '__main__':
    main()
