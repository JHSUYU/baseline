#!/usr/bin/env python3
"""Conservative read-only known-control differential oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

WORK = Path('/tmp/mallory-known-controls-adapted-v1')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name: str):
    output = WORK / name
    manifest = json.loads((output / 'manifest.json').read_text())
    log = (output / 'junit.log').read_text(errors='replace')
    return output, manifest, log


def hdfs54() -> dict:
    original, om, ol = run('hdfs54-original')
    fixed, fm, fl = run('hdfs54-fixed')
    if (om.get('returncode') != 1 or fm.get('returncode') != 0 or
            'CONTROL outcome=known_bug_reproduced' not in ol or
            'HDFS-17897: original striped checksum failed' not in ol or
            'CONTROL post_expiry_exception=org.apache.hadoop.fs.PathIOException' not in ol or
            'CONTROL repeated_failure=org.apache.hadoop.fs.PathIOException' not in ol or
            'CONTROL outcome=fixed_recovered' not in fl or
            'CONTROL patched_clear_and_retry_bg=' not in fl):
        raise RuntimeError('HDFS-54 JUnit failure/recovery differential incomplete')
    cached = re.search(r'CONTROL cached_key_id=(-?\d+)', ol)
    healthy = re.search(r'CONTROL healthy_checksum=(.+)', ol)
    recovered = re.search(r'CONTROL post_expiry_checksum=(.+)', fl)
    dn = re.findall(r'CONTROL dn_identity=([^\n]+?) managerIdentity=(\d+) cachedKeyId=(-?\d+) keyPresent=false', ol)
    if (not cached or not healthy or not recovered or
            healthy.group(1) != recovered.group(1) or len({row[1] for row in dn}) != 3 or
            any(row[2] != cached.group(1) for row in dn)):
        raise RuntimeError('HDFS-54 key ID, three DN maps, or checksum equality missing')
    trace = [json.loads(line) for line in (original / 'runtime_trace.jsonl').read_text().splitlines()]
    selected = [row for row in trace if row.get('event') == 'TARGET_CHECK'
                and row.get('keyId') == int(cached.group(1)) and row.get('keyPresent') is False]
    errors = [row for row in trace if row.get('event') == 'STRIPED_IO_EXCEPTION'
              and row.get('exception', '').endswith('InvalidEncryptionKeyException')]
    false_checks = [row for row in trace if row.get('event') == 'STRIPED_CHECK'
                    and row.get('completed') is False]
    if (len({row.get('managerIdentity') for row in selected}) != 3 or
            len(errors) < 3 or not false_checks):
        raise RuntimeError('HDFS-54 exact DN guard, IKE catch, or selected false check missing')
    return {'case_id': 'HDFS-54', 'known_issue': 'HDFS-17897',
            'status': 'known_control_differential_passed',
            'original_manifest_sha256': sha(original / 'manifest.json'),
            'fixed_manifest_sha256': sha(fixed / 'manifest.json'),
            'cached_key_id': int(cached.group(1)), 'dn_guard_managers': 3,
            'exact_invalid_key_catches': len(errors), 'selected_false_checks': len(false_checks),
            'new_bug': False}


def hdfs55() -> dict:
    healthy, hm, hl = run('hdfs55-healthy')
    original, om, ol = run('hdfs55-fault-original')
    fixed, fm, fl = run('hdfs55-fault-fixed')
    if (hm.get('returncode') != 0 or om.get('returncode') != 1 or
            fm.get('returncode') != 0 or
            'CASE55 dn_wire_error_response=INVALID_KEY' not in ol or
            not re.search(r'NO_MOVE_PROGRESS|No block has been moved|expected:<0> but was:<-3>', ol) or
            'balancer_key_cache_cleared=true' in ol or
            'CASE55 dn_wire_error_response=INVALID_KEY' not in fl or
            'balancer_key_cache_cleared=true' not in fl or
            not re.search(r'CASE55 key_guard=.*refresh=true', fl)):
        raise RuntimeError('HDFS-55 Balancer/JUnit failure and fixed recovery differential incomplete')
    selected = re.search(r'CASE55 dn_wire_selected_manager=(\d+) key_id=(-?\d+) nonce_digest=([0-9a-f]+)', ol)
    missing = re.search(r'CASE55 dn_allkeys_forced_missing=\d+ role=target-datanode manager=(\d+)'
                        r' server_endpoint=([^ ]+) key_id=(-?\d+) nonce_digest=([0-9a-f]+)'
                        r' block_pool=([^ ]+) key_present_before_fault=true', ol)
    if (not selected or not missing or selected.group(1) != missing.group(1) or
            selected.group(2) != missing.group(3) or selected.group(3) != missing.group(4) or
            not re.search(r'CASE55 key_guard=.*cached_key_id=' + re.escape(selected.group(2))
                          + r'.*refresh=false', ol)):
        raise RuntimeError('HDFS-55 cached manager/key/nonce to exact DN allKeys linkage missing')
    return {'case_id': 'HDFS-55', 'known_issue': 'HDFS-17899',
            'status': 'synthetic_missing_key_diagnostic_passed',
            'healthy_manifest_sha256': sha(healthy / 'manifest.json'),
            'original_manifest_sha256': sha(original / 'manifest.json'),
            'fixed_manifest_sha256': sha(fixed / 'manifest.json'),
            'cached_key_id': int(selected.group(2)),
            'nonce_digest': selected.group(3),
            'dn_endpoint': missing.group(2),
            'synthetic_allkeys_missing': True,
            'mechanism_faithful': False, 'detection_claim': False,
            'new_bug': False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('HDFS-54', 'HDFS-55'), required=True)
    args = parser.parse_args()
    print(json.dumps((hdfs54 if args.case == 'HDFS-54' else hdfs55)(), sort_keys=True))


if __name__ == '__main__':
    main()
