#!/usr/bin/env python3
"""Publish the two counted stages with per-trial duration and raw hashes."""

import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGES = (
    ('client_after_write', Path('/users/ZhenyuLi/zk02-actor-v2-afterio-runs'),
     'afterio-campaign.json'),
    ('server_after_sync_response',
     Path('/users/ZhenyuLi/zk02-actor-v2-after-response-runs'),
     'after-response-campaign.json'),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rows = []
    for stage, root, checkpoint in STAGES:
        state = json.loads((root / checkpoint).read_text())
        for item in state['results']:
            dest = root / item['run_id']
            log_archive = dest / 'junit.log.gz'
            manifest = dest / 'junit-log-compression.json'
            if not log_archive.is_file() or not manifest.is_file():
                raise RuntimeError('completed trial lacks compressed JUnit log: ' + str(dest))
            compressed = json.loads(manifest.read_text())
            if sha(log_archive) != compressed['archive_sha256']:
                raise RuntimeError('compressed original JUnit log hash mismatch: ' + str(dest))
            rows.append({
                'case_id': 'ZOOKEEPER-02', 'stage': stage, 'run_id': item['run_id'],
                'original_test': 'org.apache.zookeeper.test.QuorumTest#testSessionMoved',
                'target_file': 'zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java',
                'target_function': 'SessionTrackerImpl.checkSession(long,Object)',
                'target_line': 323, 'fault_depth': len(item['plan']),
                'plan_json': json.dumps(item['plan'], separators=(',', ':')),
                'all_faults_applied': bool(item['strict_receipt']),
                'same_session_owner_target_after_fault': item['effective'],
                'selected_target_throw_count': item['selected_target_throw_count'],
                'junit_exit': item['junit_exit'],
                'non_target_junit_failure': item['junit_exit'] != 0
                                            and not item['selected_target_throw_count'],
                'elapsed_seconds': item['elapsed_seconds'],
                'new_coverage_lines': item['new_coverage_lines'],
                'new_io_families': item['new_io_families'],
                'bug_mark': item['bug_mark'],
                'run_root': str(dest),
                'run_sha256': sha(dest / 'run.json'),
                'events_sha256': sha(dest / 'events.tsv'),
                'coverage_sha256': sha(dest / 'coverage.tsv'),
                'junit_log_gz_sha256': sha(log_archive),
                'junit_log_raw_sha256': compressed['raw_sha256'],
            })
    path = HERE / 'trial-summary.csv'
    with path.open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({'rows': len(rows), 'output': str(path),
                      'sha256': sha(path)}, sort_keys=True))


if __name__ == '__main__':
    main()
