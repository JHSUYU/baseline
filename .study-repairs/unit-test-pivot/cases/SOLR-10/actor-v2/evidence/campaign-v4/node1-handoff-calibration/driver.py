#!/usr/bin/env python3
import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import handoff_calibrate as h
import migrate as m
from feedback import atomic_json


def java_count():
    pids = []
    for name in glob.glob('/proc/[0-9]*/comm'):
        try:
            if Path(name).read_text().strip() == 'java':
                pids.append(int(Path(name).parts[2]))
        except OSError:
            continue
    return sorted(pids)


def main():
    manifest = json.loads(m.MANIFEST.read_text())
    m.verify_manifest(manifest)
    if h.OUTPUT.exists():
        raise RuntimeError('handoff calibration evidence already exists')
    if m.active_campaign():
        raise RuntimeError('same-case campaign/JUnit already active')
    before = m.digest(m.CAMPAIGN / 'state.json')
    h.OUTPUT.mkdir()
    results = {}
    preflight = {}
    for name, flags in (('original', ['--original']), ('actor', ['--coverage'])):
        pids = java_count()
        if len(pids) >= 5:
            raise RuntimeError(f'JVM slot unavailable before {name}: {pids}')
        free = shutil.disk_usage(m.CASE).free
        if free < 8 * 1024**3:
            raise RuntimeError(f'node1 below 8 GiB before {name}')
        preflight[name] = {'java_jvm_count_before': len(pids), 'java_pids_before': pids,
                           'free_gib_before': round(free / 2**30, 2)}
        directory = h.OUTPUT / name
        subprocess.run([sys.executable, str(h.RUN), str(directory), *flags], check=False)
        results[name] = h.check_junit(directory, original=name == 'original')
        scratch = directory / 'scratch'
        if scratch.exists():
            shutil.rmtree(scratch)
    after = m.digest(m.CAMPAIGN / 'state.json')
    if after != before:
        raise RuntimeError('fault campaign state changed during no-fault calibration')
    result = {'calibration_pass': True, 'fault_budget_increment': 0,
              'checkpoint_state_sha256': before,
              'migration_manifest_sha256': m.digest(m.MANIFEST),
              'build_receipt_sha256': m.digest(m.CASE / 'build-receipt.json'),
              'driver_sha256': m.digest(Path(__file__)),
              'preflight': preflight, 'original': results['original'],
              'actor': results['actor']}
    atomic_json(h.OUTPUT / 'handoff-calibration.json', result)
    shutil.copy2(__file__, h.OUTPUT / 'driver.py')
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
