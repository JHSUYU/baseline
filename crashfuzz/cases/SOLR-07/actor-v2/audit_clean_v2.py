#!/usr/bin/env python3
"""Audit the two unchanged, uninstrumented original cluster JUnits."""

import hashlib
import json
import re
import socket
from pathlib import Path

from build_v2 import HERE
from run_v2 import verify_build


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    build = verify_build()
    host = (HERE / 'clean-node2.host').read_text().strip()
    if host != socket.gethostname() or not host.startswith('node2.'):
        raise RuntimeError('clean JUnit host mismatch')
    if (HERE / 'clean-node2.exit').read_text().strip() != '0':
        raise RuntimeError('clean JUnit tmux exit not zero')
    if build['classpath_contains_graphchecker']:
        raise RuntimeError('GraphChecker artifact in original JUnit classpath')
    seeds = []
    for name in ('clean-01', 'clean-02'):
        directory = HERE / name
        receipt = json.loads((directory / 'run.json').read_text())
        log = directory / 'junit.log'
        if (receipt['exit_code'] != 0 or receipt['instrumented'] or
                receipt['agent_sha256'] is not None or receipt['plan'] is not None or
                not receipt['assertions_enabled'] or
                receipt['source_revision'] != build['source_revision'] or
                not re.search(r'SOLR05_JUNIT_RESULT run=1 failures=0 ignored=0',
                              log.read_text()) or
                (directory / 'events.jsonl').exists() or
                (directory / 'jacoco.exec').exists()):
            raise RuntimeError(f'clean original-JUnit gate failed: {name}')
        seeds.append({'seed': name, 'elapsed_seconds': receipt['elapsed_seconds'],
                      'exit_code': receipt['exit_code'],
                      'original_junit': 'run=1 failures=0 ignored=0',
                      'run_sha256': sha(directory / 'run.json'),
                      'log_sha256': sha(log)})
    audit = {'case_id': 'SOLR-07', 'test': build['test'], 'host': host,
             'started_utc': (HERE / 'clean-node2.started').read_text().strip(),
             'finished_utc': (HERE / 'clean-node2.finished').read_text().strip(),
             'source_revision': build['source_revision'],
             'original_test_source_sha256': build['test_source_sha256'],
             'original_test_class_sha256': build['test_class_sha256'],
             'original_core_sha256': build['original_core_sha256'],
             'classpath_contains_graphchecker': False,
             'instrumented': False, 'fault_trials': 0,
             'clean_original_junit_passes': len(seeds), 'seeds': seeds,
             'resource_overlap_observation': {
                 'during_seed_2_load_1m': 14.36,
                 'other_junit_jvm_classes': [
                     'baseline.solr06.RunSingleJUnit',
                     'baseline.solr103940.RunSingleJUnit',
                     'independent.OriginalJUnitRunner (2)',
                     'research.solrforce.OriginalJUnit',
                     'research.solrsubshard.OriginalJUnit'],
                 'disk_available_gib_approx': 8.9,
                 'port_collision_observed': False,
                 'note': 'Observed during the first-to-second seed handoff; '
                         'seeds ran sequentially and had no latency over 2x.'}}
    (HERE / 'node2-clean-audit.json').write_text(
        json.dumps(audit, indent=2, sort_keys=True) + '\n')
    print(json.dumps(audit, sort_keys=True))


if __name__ == '__main__':
    main()
