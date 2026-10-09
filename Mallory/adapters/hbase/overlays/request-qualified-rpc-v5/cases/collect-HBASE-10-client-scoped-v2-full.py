#!/usr/bin/env python3
"""Preserve a terminal HBASE-10 campaign without changing the canonical table."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import time

BASE = Path('/users/ZhenyuLi/baseline')
RELEASE_ID = '4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4'
RELEASE = BASE / 'Mallory/dispatch/releases' / RELEASE_ID
CASE = BASE / 'data/mallory/HBASE-10/campaigns/client-bound-v2-full'
ARCHIVE = BASE / 'data/mallory/evidence_archives/hbase10_client_bound_v2/HBASE-10.tar.gz'
COMPACT = CASE.parent / 'client-bound-v2-full-compact'
MANIFEST = CASE.parent / 'client-bound-v2-full-member-manifest.json'
RECEIPT = CASE.parent / 'client-bound-v2-full-archive-receipt.json'
REMOTE = 'ZhenyuLi@node1'
SSH = ['ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', REMOTE]
SCP = ['scp', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes']
FLOOR = 5 * 1024**3
SAFETY = 128 * 1024**2


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run(args, *, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} exit {result.returncode}: {result.stderr[-1000:]}')
    return result


def remote(command, *, check=True):
    return run(SSH + [command], check=check)


def remote_file(path):
    return remote('cat ' + shlex.quote(str(path))).stdout.encode()


def terminal():
    output = remote('cat ' + shlex.quote(str(CASE / 'result.json')), check=False)
    if output.returncode:
        return False
    try:
        status = json.loads(output.stdout)['status']
    except (KeyError, ValueError):
        return False
    if status == 'running':
        return False
    return remote('tmux has-session -t mallory-hbase10-client-bound-v2-full '
                  '2>/dev/null', check=False).returncode != 0


def copy_compact():
    COMPACT.mkdir(parents=True, exist_ok=True)
    for name in ('result.json', 'config.json', 'checkpoint.json',
                 'offline-causal-audit.json'):
        path = COMPACT / name
        payload = remote_file(CASE / name)
        if path.exists():
            if path.read_bytes() != payload:
                raise RuntimeError(f'existing compact evidence differs: {path}')
            continue
        if shutil.disk_usage(BASE).free < FLOOR + len(payload) + SAFETY:
            raise RuntimeError('node0 disk reserve prevents compact evidence transfer')
        temporary = Path(str(path) + '.tmp')
        temporary.write_bytes(payload)
        os.replace(temporary, path)


def remote_members():
    command = ('cd ' + shlex.quote(str(CASE)) +
               ' && find . -type f ! -name .campaign.lock -print0 '
               '| sort -z | xargs -0 sha256sum')
    text = remote(command).stdout
    result = {}
    for line in text.splitlines():
        digest, name = line.split('  ', 1)
        if (not name.startswith('./') or '..' in Path(name).parts
                or name[2:] in result):
            raise RuntimeError('invalid or duplicate remote archive member')
        result[name[2:]] = digest
    if not result or 'result.json' not in result or 'offline-causal-audit.json' not in result:
        raise RuntimeError('remote campaign manifest is incomplete')
    return result


def check_archive(expected):
    actual = {}
    with tarfile.open(ARCHIVE, 'r:gz') as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if (not parts or parts[0] != CASE.name or '..' in parts
                    or not (member.isdir() or member.isfile())):
                raise RuntimeError(f'unsafe archive member: {member.name}')
            if not member.isfile():
                continue
            name = str(Path(*parts[1:]))
            source = archive.extractfile(member)
            if source is None or name in actual:
                raise RuntimeError(f'duplicate or unreadable archive member: {name}')
            actual[name] = hashlib.sha256(source.read()).hexdigest()
    if actual != expected:
        raise RuntimeError('archive content differs from remote member SHAs')
    return actual


def main():
    while not terminal():
        time.sleep(30)
    if RECEIPT.exists():
        print(json.dumps({'receipt': str(RECEIPT), 'sha256': sha(RECEIPT),
                          'already_collected': True}), flush=True)
        return
    run(['python3', '-m', 'Mallory.dispatch.core_release', '--verify',
         str(RELEASE / 'manifest.json')])
    remote('cd ' + shlex.quote(str(BASE)) + ' && python3 -m '
           'Mallory.dispatch.core_release --verify ' +
           shlex.quote(str(RELEASE / 'manifest.json')))
    audit = remote('cd ' + shlex.quote(str(BASE)) + ' && PYTHONPATH=' +
                   shlex.quote(str(RELEASE) + ':' + str(BASE)) +
                   ' python3 -m Mallory.core.audit --campaign ' +
                   shlex.quote(str(CASE)) + ' --out ' +
                   shlex.quote(str(CASE / 'offline-causal-audit.json')),
                   check=False)
    if audit.returncode not in (0, 2):
        raise RuntimeError(f'remote offline audit failed: {audit.stderr[-1000:]}')
    copy_compact()
    members = remote_members()
    remote('mkdir -p ' + shlex.quote(str(ARCHIVE.parent)) +
           ' && if test ! -f ' + shlex.quote(str(ARCHIVE)) +
           '; then tar --exclude=.campaign.lock -C ' +
           shlex.quote(str(CASE.parent)) + ' -czf ' +
           shlex.quote(str(ARCHIVE) + '.tmp') + ' ' +
           shlex.quote(CASE.name) + ' && mv ' +
           shlex.quote(str(ARCHIVE) + '.tmp') + ' ' +
           shlex.quote(str(ARCHIVE)) + '; fi')
    archive_sha = remote('sha256sum ' + shlex.quote(str(ARCHIVE))).stdout.split()[0]
    archive_size = int(remote('stat -c %s ' + shlex.quote(str(ARCHIVE))).stdout.strip())
    while shutil.disk_usage(BASE).free < FLOOR + SAFETY + (0 if ARCHIVE.exists() else archive_size):
        print(json.dumps({'status': 'held_for_node0_disk',
                          'free_bytes': shutil.disk_usage(BASE).free,
                          'required_bytes': FLOOR + SAFETY + archive_size}), flush=True)
        time.sleep(60)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        temporary = Path(str(ARCHIVE) + '.tmp')
        run(SCP + [REMOTE + ':' + str(ARCHIVE), str(temporary)])
        if sha(temporary) != archive_sha:
            raise RuntimeError('remote archive SHA differs after transfer')
        os.replace(temporary, ARCHIVE)
    if sha(ARCHIVE) != archive_sha:
        raise RuntimeError('existing archive differs from node1')
    check_archive(members)
    MANIFEST.write_text(json.dumps({'schema_version': 1, 'case_id': 'HBASE-10',
                                    'member_sha256': members}, indent=2,
                                   sort_keys=True) + '\n')
    summary = json.loads((COMPACT / 'result.json').read_text())
    quality = json.loads((COMPACT / 'offline-causal-audit.json').read_text())
    receipt = {
        'schema_version': 1, 'case_id': 'HBASE-10',
        'campaign': 'client-bound-v2-full',
        'terminal_status': summary['status'],
        'duration_seconds': summary['duration_seconds'],
        'fault_trials_completed': summary['fault_trials_completed'],
        'strict_injected_trials': summary['strict_injected_trials'],
        'strict_target_trials': summary['strict_target_trials'],
        'exact_exception_trials': summary['exact_exception_trials'],
        'core_release_id': RELEASE_ID,
        'core_manifest_sha256': sha(RELEASE / 'manifest.json'),
        'archive_path': str(ARCHIVE), 'archive_sha256': archive_sha,
        'archive_member_count': len(members),
        'member_manifest_sha256': sha(MANIFEST),
        'result_sha256': sha(COMPACT / 'result.json'),
        'audit_sha256': sha(COMPACT / 'offline-causal-audit.json'),
        'audit_report_gate_passed': quality.get('report_gate_passed'),
        'audit_guidance_consistent': quality.get('guidance_consistent'),
        'canonical_promoted': False, 'new_bug_claim': False,
    }
    temporary = Path(str(RECEIPT) + '.tmp')
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    os.replace(temporary, RECEIPT)
    print(json.dumps({'receipt': str(RECEIPT), 'sha256': sha(RECEIPT),
                      'archive_sha256': archive_sha}), flush=True)


if __name__ == '__main__':
    main()
