#!/usr/bin/env python3
"""Independently replay trial classification from saved HDFS JUnit evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tarfile

import campaign

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
STATE = HERE / 'evidence/campaign-state.json'
AUDIT = HERE / 'evidence/final-audit.json'
MANIFEST = CASE / 'independent-archive-manifest.json'
ARCHIVE = CASE / (CASE.name + '-independent-evidence.tar.gz')


def save_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def main() -> None:
    state = json.loads(STATE.read_text())
    assert state['stop_reason'] is not None, 'Campaign is still live'
    raw_files = {STATE, HERE / 'trial-ledger.csv'}
    raw_files.update(path for path in campaign.HEALTHY.iterdir() if path.is_file())
    audited = []
    for trial in state['completed']:
        directory = CASE / trial['run_dir']
        assert (directory / 'manifest.json').is_file(), trial['trial']
        reread = campaign.run_trial({'plan': trial['plan']}, trial['trial'])
        fields = ('elapsed_seconds', 'fault_count', 'matched_faults',
                  'applied_faults', 'exact_order_applied', 'target_after_fault',
                  'selected_target_throw', 'junit_exit', 'plan',
                  'last_applied_sequence') + tuple(
                      field for field in ('target_bpid', 'target_path')
                      if field in trial)
        for field in fields:
            assert reread[field] == trial[field], (trial['trial'], field,
                                                    reread[field], trial[field])
        audited.append({field: trial[field] for field in fields} |
                       {'trial': trial['trial']})
        raw_files.update(path for path in directory.iterdir() if path.is_file())
        driver = directory.parent / (directory.name + '-driver.log')
        if driver.is_file():
            raw_files.add(driver)
    assert len(audited) == len(state['completed'])
    valid = [row for row in audited if row['exact_order_applied']
             and row['target_after_fault']]
    summary = {'case_id': CASE.name,
               'stop_reason': state['stop_reason'],
               'completed_attempts': len(audited),
               'strict_trials': sum(row['exact_order_applied'] for row in audited),
               'target_retaining_trials': len(valid),
               'selected_target_throws': sum(row['selected_target_throw'] for row in valid),
               'trials': audited}
    save_json(AUDIT, summary)
    raw_files.add(AUDIT)
    temporary = ARCHIVE.with_suffix(ARCHIVE.suffix + '.tmp')
    with tarfile.open(temporary, 'w:gz') as output:
        for path in sorted(raw_files):
            assert path.is_file() and path.is_relative_to(CASE)
            output.add(path, arcname=str(path.relative_to(CASE)), recursive=False)
    os.replace(temporary, ARCHIVE)
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    save_json(MANIFEST, {'archive': ARCHIVE.name, 'sha256': digest,
                         'bytes': ARCHIVE.stat().st_size,
                         'file_count': len(raw_files),
                         'contents': 'Saved original JUnit traces, raw JaCoCo, logs, plans, checkpoint, and per-trial classification audit; active interrupted trial excluded'})
    print({key: summary[key] for key in ('completed_attempts', 'strict_trials',
                                          'target_retaining_trials',
                                          'selected_target_throws')})


if __name__ == '__main__':
    main()
