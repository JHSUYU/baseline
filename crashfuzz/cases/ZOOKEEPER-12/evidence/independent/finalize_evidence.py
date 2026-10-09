#!/usr/bin/env python3
"""Seal the completed case-local JUnit records and update this case's result."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile

from campaign import CASE, CHECKPOINT, HERE, RESULT, candidates, events
from run_native import ROOT


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def main():
    state = json.loads(CHECKPOINT.read_text())
    audit = json.loads((HERE / 'audit.json').read_text())
    provenance = json.loads((HERE / 'provenance.json').read_text())
    assert state['finished'] and len(state['trials']) == audit['trials_reaudited']
    assert provenance['trial_jvms_verified'] == len(state['trials'])

    fields = ['run_id', 'parent', 'fault_count', 'elapsed_seconds', 'junit_exit',
              'strict_injection', 'target_after_final_fault',
              'target_guard_after_fault_count', 'target_throw_after_fault_count',
              'new_production_coverage_lines', 'new_pretarget_io_count',
              'plan', 'matched', 'applied']
    path = HERE / 'trial-summary.csv'
    with path.open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        for item in state['trials']:
            writer.writerow({key: json.dumps(item[key]) if key in ('plan', 'matched', 'applied')
                             else item.get(key) for key in fields})

    reviews = []
    for item in state['trials']:
        if item['junit_exit'] == 0:
            continue
        log = (ROOT / item['run_id'] / 'junit.log').read_text(errors='replace')
        failure = log.rsplit('Failures (', 1)[-1]
        summary = re.search(r'=> ([^\n]+)', failure)
        first_frame = re.search(r'\n\s+(org\.apache\.zookeeper\.[^\n]+)',
                                failure[summary.end():] if summary else '')
        reviews.append({
            'run_id': item['run_id'], 'plan': item['plan'],
            'strict_injection': item['strict_injection'],
            'target_after_final_fault': item['target_after_final_fault'],
            'target_guard_peers_after_fault': item['target_guard_sessions_after_fault'],
            'selected_target_exception_after_fault': item['target_throw_after_fault_count'],
            'junit_failure': summary.group(1) if summary else 'unparsed',
            'first_zookeeper_frame': first_frame.group(1).strip() if first_frame else None,
            'injected_fault_logged': 'selected independent I/O fault' in log,
        })
    atomic_json(HERE / 'failure-review.json', reviews)

    run_names = ['healthy-01'] + [item['run_id'] for item in state['trials']]
    archive = HERE / 'raw-runs.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        for name in run_names:
            for filename in ('run.json', 'events.tsv', 'coverage.tsv', 'junit.log'):
                source = ROOT / name / filename
                assert source.exists(), source
                output.add(source, arcname=name + '/' + filename, recursive=False)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    healthy_families = {x.split('@@')[0] for x in candidates(events('healthy-01'))}
    observed_families = {x.split('@@')[0] for x in state['seen_pretarget_io']}

    result = json.loads(RESULT.read_text())
    assert result['status'] == 'quality_complete'
    result.update({
        'quality_complete': True,
        'production_coverage_gain': result['coverage_gain'],
        'io_family_gain': len(observed_families - healthy_families),
        'target_exception_after_fault_trials':
            sum(item['target_throw_after_fault_count'] > 0
                for item in state['trials'] if item['target_after_final_fault']),
        'junit_nonzero_trials': len(reviews),
        'target_retaining_junit_nonzero_trials':
            sum(item['target_after_final_fault'] for item in reviews),
        'independent_recording': {
            'healthy_run': str(ROOT / 'healthy-01'),
            'trial_csv': str(path.relative_to(CASE)),
            'audit': str((HERE / 'audit.json').relative_to(CASE)),
            'provenance': str((HERE / 'provenance.json').relative_to(CASE)),
            'failure_review': str((HERE / 'failure-review.json').relative_to(CASE)),
            'raw_archive': str(archive.relative_to(CASE)),
            'raw_archive_sha256': sha,
            'raw_archive_jvms': len(run_names),
        },
    })
    atomic_json(RESULT, result)
    print(json.dumps({'case_id': result['case_id'], 'trials': len(state['trials']),
                      'strict': audit['strict'], 'target_retaining': audit['target_retaining'],
                      'target_exception': audit['target_throw_after_fault'],
                      'junit_nonzero': len(reviews),
                      'target_retaining_junit_nonzero':
                          result['target_retaining_junit_nonzero_trials'],
                      'production_coverage_gain': result['coverage_gain'],
                      'io_family_gain': result['io_family_gain'],
                      'elapsed_seconds': result['elapsed_seconds'],
                      'archive_sha256': sha}, indent=2))


if __name__ == '__main__':
    main()
