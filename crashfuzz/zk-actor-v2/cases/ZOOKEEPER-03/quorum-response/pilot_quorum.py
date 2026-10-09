#!/usr/bin/env python3
"""Resumable, bounded ZK03 quorum-response experiment on original JUnit."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get('ZK03_SOURCE', '/users/ZhenyuLi/zk03-quorum-independent'))
BUILD = Path(os.environ.get('ZK03_QUORUM_BUILD', '/users/ZhenyuLi/zk03-quorum-response-build'))
ROOT = Path(os.environ.get('ZK03_QUORUM_RUN_ROOT', '/users/ZhenyuLi/zk03-quorum-response-runs'))
REPORT = Path(os.environ.get('ZK03_REPORT', '/users/ZhenyuLi/zk03-quorum-classpath.xml'))
RUNNER = Path(os.environ.get('ZK03_RUNNER', '/users/ZhenyuLi/zk03-quorum-runner.jar'))
AGENT = BUILD / 'zk03-quorum-response-agent.jar'
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin/java')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar')
START_LOCK = Path('/users/ZhenyuLi/baseline/crashfuzz/jvm-start.lock')
CHECK = 'SessionTrackerImpl#setOwner:329:missingOrClosing'
SITE_SUFFIX = 'BufferedOutputStream#flush()V'
MIN_FREE = 10 * 1024 ** 3
MAX_JAVA = 5
MAX_PILOT = 10


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def verify_assets():
    receipt = json.loads((BUILD / 'build-receipt.json').read_text())
    if receipt['status'] != 'offline_pass' or sha(AGENT) != receipt['agent_sha256']:
        raise RuntimeError('isolated agent changed after offline build')
    for name, digest in receipt['original_classes_sha256'].items():
        base = SOURCE / 'zookeeper-server/target/test-classes' if name.endswith('/QuorumTest') \
            else SOURCE / 'zookeeper-server/target/classes'
        if sha(base / (name + '.class')) != digest:
            raise RuntimeError('original compiled class changed: ' + name)
    if sha(SOURCE / 'zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java') != \
            receipt['original_test_source_sha256'] or \
            sha(SOURCE / 'zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java') != \
            receipt['original_target_source_sha256']:
        raise RuntimeError('original JUnit or target source changed')
    for item in (REPORT, RUNNER, ASM, JAVA):
        if not item.is_file():
            raise FileNotFoundError(item)
    return receipt


def classpath():
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    original = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    original = original.replace('/tmp/zk387-unit-smoke-20261006', str(SOURCE))
    cp = ':'.join((str(ASM), original, str(RUNNER), str(AGENT)))
    if 'graphchecker' in cp.lower() or 'skeleton' in cp.lower():
        raise RuntimeError('non-original graph runtime on classpath')
    for item in cp.split(':'):
        if item and '*' not in item and not Path(item).exists():
            raise FileNotFoundError('classpath entry ' + item)
    return cp


def parse_events(path):
    rows = []
    for line in path.read_text().splitlines():
        cells = line.split('\t')
        if len(cells) < 3:
            raise RuntimeError('short event row')
        rows.append((int(cells[0]), cells[1], cells[2:-1], cells[-1]))
    return sorted(rows)


def port_window(slot, slots):
    span = (32767 - 11221) // slots
    low = 11221 + (slot - 1) * span
    return low, low + span - 1


def preflight(slot, slots):
    free = shutil.disk_usage(ROOT.parent).free
    java_count = len(subprocess.check_output(['ps', '-C', 'java', '-o', 'pid='], text=True).splitlines())
    if free < MIN_FREE or java_count >= MAX_JAVA:
        raise RuntimeError('resource gate: free=' + str(free) + ' java=' + str(java_count))
    low, high = port_window(slot, slots)
    occupied = []
    for line in subprocess.check_output(['ss', '-H', '-ltn'], text=True).splitlines():
        try:
            port = int(line.split()[3].rsplit(':', 1)[1])
        except (IndexError, ValueError):
            continue
        if low <= port <= high:
            occupied.append(port)
    if occupied:
        raise RuntimeError('reserved ZooKeeper slot occupied: ' + str((low, high, occupied)))
    return {'free_bytes': free, 'java_before': java_count, 'port_range': [low, high]}


def run_one(run_id, plan, slot, slots, timeout):
    dest = ROOT / run_id
    if dest.exists():
        if (dest / 'run.json').is_file():
            old = json.loads((dest / 'run.json').read_text())
            if old['plan'] != plan:
                raise RuntimeError('existing immutable run has different plan: ' + run_id)
            return old
        raise RuntimeError('incomplete run directory requires manual audit: ' + str(dest))
    build = verify_assets()
    cp = classpath()
    START_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with START_LOCK.open('a+') as gate:
        fcntl.flock(gate, fcntl.LOCK_EX)
        check = preflight(slot, slots)
        dest.mkdir(parents=True)
        (dest / 'temp').mkdir()
        cmd = [str(JAVA), '-Xverify:all', '-ea', '-Xmx1g', '-Djava.awt.headless=true',
               '-Dsun.reflect.noInflation=true',
               '-Djava.io.tmpdir=' + str(dest / 'temp'),
               '-Dbuild.test.dir=' + str(dest / 'test-data'),
               '-Dtest.junit.threads=' + str(slots),
               '-Dzookeeper.junit.threadid=' + str(slot),
               '-Dzk.actor.plan=' + '|||'.join(plan),
               '-Dzk.actor.events.output=' + str(dest / 'events.tsv'),
               '-Dzk.actor.coverage.output=' + str(dest / 'coverage.tsv'),
               '-javaagent:' + str(AGENT), '-cp', cp,
               'independent.OriginalJUnitRunner',
               'org.apache.zookeeper.test.QuorumTest', 'testSessionMoved']
        log = (dest / 'junit.log').open('w')
        started = time.monotonic()
        try:
            process = subprocess.Popen(cmd, cwd=SOURCE / 'zookeeper-server',
                                       stdout=log, stderr=subprocess.STDOUT)
        finally:
            fcntl.flock(gate, fcntl.LOCK_UN)
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        code = 124
    finally:
        log.close()
    receipt = {
        'run_id': run_id, 'plan': plan, 'exit_code': code,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'resource_preflight': check, 'worker_slot': slot, 'worker_count': slots,
        'agent_sha256': build['agent_sha256'],
        'original_source_commit': build['source_commit'],
        'original_test_class_sha256': build['original_classes_sha256']['org/apache/zookeeper/test/QuorumTest'],
        'runner_sha256': sha(RUNNER),
        'classpath_sha256': hashlib.sha256(cp.encode()).hexdigest(),
        'original_test': 'org.apache.zookeeper.test.QuorumTest#testSessionMoved',
    }
    write_json(dest / 'run.json', receipt)
    shutil.rmtree(dest / 'temp', ignore_errors=True)
    shutil.rmtree(dest / 'test-data', ignore_errors=True)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return receipt


def healthy_audit(run_id):
    dest = ROOT / run_id
    receipt = json.loads((dest / 'run.json').read_text())
    rows = parse_events(dest / 'events.tsv')
    peers = [fields for _, kind, fields, _ in rows if kind == 'PEER_BIND']
    leaders = [fields[0] for _, kind, fields, _ in rows if kind == 'LEADER_BIND']
    binds = [fields for _, kind, fields, _ in rows if kind == 'SESSION_BIND']
    owners = [(seq, fields) for seq, kind, fields, _ in rows if kind == 'OWNER_BIND']
    guards = [(seq, fields) for seq, kind, fields, _ in rows if kind == 'TARGET_GUARD'
              and fields[0] == CHECK]
    raw = {x[0] for x in binds if x[2] == 'movedSession'}
    if receipt['exit_code'] or receipt['plan'] or len(peers) != 5 or len(leaders) != 1 \
            or len(raw) != 1 or len(guards) < 10:
        raise RuntimeError(run_id + ' original healthy actor calibration failed')
    leader = leaders[0]
    for seq, guard in guards:
        if guard[1:6] != ['peer:' + leader, 'leader', leader, 'movedSession', 'present-open']:
            raise RuntimeError(run_id + ' target actor/branch changed')
        if not any(owner_seq < seq and owner[0:2] == [leader, next(iter(raw))]
                   and owner[3] == 'present-open' for owner_seq, owner in owners):
            raise RuntimeError(run_id + ' target lacks raw owner receipt')
    written = [(seq, f, th) for seq, kind, f, th in rows
               if kind == 'QUORUM_REVALIDATE_WRITTEN' and len(f) >= 3]
    flushed = [(seq, f, th) for seq, kind, f, th in rows
               if kind == 'QUORUM_FLUSH_COMPLETE' and len(f) >= 4]
    bound = [(seq, f, th) for seq, kind, f, th in rows
             if kind == 'QUORUM_RESPONSE_BIND' and len(f) >= 7]
    candidates = []
    for seq, kind, f, thread in rows:
        if kind != 'IO' or len(f) < 7 or not f[0].endswith(SITE_SUFFIX):
            continue
        site, actor, resource, ordinal, local, remote, tag = f[:7]
        if actor != 'peer:' + leader + ':session:movedSession' or local != leader \
                or tag != 'movedSession' or not remote or \
                ('follower:' + remote + ':owner:forwarder:' + remote + ':generation:') not in resource:
            continue
        binding = [(bseq, bf) for bseq, bf, bth in bound if bth == thread and bseq < seq
                   and bf[0] == site and bf[1:4] == [leader, remote, next(iter(raw))]
                   and bf[5:7] == [actor, resource]]
        if not binding:
            continue
        bseq, bf = binding[-1]
        flush = [(fs, ff) for fs, ff, fth in flushed if fth == thread and fs < bseq
                 and ff[1] == site and ff[2] == next(iter(raw)) and ff[3] == 'true']
        if not flush:
            continue
        fs, ff = flush[-1]
        if not any(ws < fs and wt == thread and wf[0] == ff[0]
                   and wf[1] == next(iter(raw)) and wf[2] == 'true'
                   for ws, wf, wt in written):
            continue
        later = [gseq for gseq, gf in guards if gseq > seq and gf[1] == 'peer:' + leader]
        if not later:
            continue
        candidates.append({'selector': '@@'.join(f[:4]), 'seq': seq,
                           'leader_sid': leader, 'follower_sid': remote,
                           'raw_session_id': next(iter(raw)), 'owner_key': bf[4],
                           'later_guard_seq': later[0], 'family': '@@'.join(f[:3])})
    if not candidates:
        raise RuntimeError(run_id + ' has no observed complete REVALIDATE write/flush before later target')
    return {'run_id': run_id, 'raw_session_id': next(iter(raw)),
            'leader_sid': leader, 'target_guards': len(guards),
            'written': len(written), 'flushed': len(flushed), 'bound': len(bound),
            'candidates': candidates, 'events_sha256': sha(dest / 'events.tsv'),
            'coverage_sha256': sha(dest / 'coverage.tsv')}


def calibrate():
    first = healthy_audit('healthy-a')
    second = healthy_audit('healthy-b')
    if json.loads((ROOT / 'healthy-a/run.json').read_text())['agent_sha256'] != \
            json.loads((ROOT / 'healthy-b/run.json').read_text())['agent_sha256']:
        raise RuntimeError('healthy seeds used different agents')
    stable = {x['family'] for x in first['candidates']} & \
             {x['family'] for x in second['candidates']}
    if not stable:
        raise RuntimeError('no post-flush quorum response family stable across two healthy JUnits')
    result = {'status': 'pass', 'healthy': [first, second],
              'common_families': sorted(stable), 'old_stages_pooled': False,
              'pilot_budget': MAX_PILOT}
    write_json(ROOT / 'calibration.json', result)
    return result


def audit_trial(run_id, plan, seen):
    dest = ROOT / run_id
    receipt = json.loads((dest / 'run.json').read_text())
    rows = parse_events(dest / 'events.tsv')
    matches = [f for _, k, f, _ in rows if k == 'FAULT_MATCHED']
    applied = [(s, f, th) for s, k, f, th in rows if k == 'FAULT_APPLIED']
    exact = ['@@'.join(f[:4]) for f in matches] == plan and \
            ['@@'.join(f[:4]) for _, f, _ in applied] == plan
    raw = {f[0] for _, k, f, _ in rows if k == 'SESSION_BIND' and len(f) >= 3
           and f[2] == 'movedSession'}
    leaders = [f[0] for _, k, f, _ in rows if k == 'LEADER_BIND']
    bound = False
    last = applied[-1][0] if applied else 0
    if exact and len(raw) == 1 and len(leaders) == 1:
        for seq, f, thread in applied:
            if len(f) < 7 or f[1] != 'peer:' + leaders[0] + ':session:movedSession' \
                    or f[4] != leaders[0] or f[6] != 'movedSession':
                break
            prior = [(bs, bf) for bs, k, bf, bt in rows if k == 'QUORUM_RESPONSE_BIND'
                     and bt == thread and bs < seq and len(bf) >= 7 and
                     bf[0] == f[0] and bf[1] == leaders[0] and bf[2] == f[5] and
                     bf[3] == next(iter(raw)) and bf[5:7] == f[1:3]]
            if not prior:
                break
            binding_seq = prior[-1][0]
            flushes = [(fs, ff) for fs, k, ff, ft in rows if k == 'QUORUM_FLUSH_COMPLETE'
                       and ft == thread and fs < binding_seq and len(ff) >= 4
                       and ff[1] == f[0] and ff[2] == next(iter(raw)) and ff[3] == 'true']
            if not flushes:
                break
            flush_seq, flush_fields = flushes[-1]
            if not any(ws < flush_seq and wt == thread and len(wf) >= 3
                       and wf[0] == flush_fields[0] and wf[1] == next(iter(raw))
                       and wf[2] == 'true' for ws, k, wf, wt in rows
                       if k == 'QUORUM_REVALIDATE_WRITTEN'):
                break
        else:
            bound = True
    guards = [(s, f) for s, k, f, _ in rows if s > last and k == 'TARGET_GUARD'
              and len(f) >= 6 and f[0] == CHECK and len(leaders) == 1
              and f[1:5] == ['peer:' + leaders[0], 'leader', leaders[0], 'movedSession']]
    owner_after = [(s, f) for s, k, f, _ in rows if s > last and k == 'OWNER_BIND'
                   and len(f) >= 4 and len(raw) == 1 and len(leaders) == 1
                   and f[0:2] == [leaders[0], next(iter(raw))]
                   and f[2].startswith(('local:', 'forwarder:'))]
    witnessed_guard = [gseq for gseq, _ in guards
                       if any(last < oseq < gseq for oseq, _ in owner_after)]
    effective = exact and bound and bool(witnessed_guard)
    throws = [(s, f) for s, k, f, _ in rows if effective and s > last
              and k == 'TARGET_THROW' and len(f) >= 6 and f[0] == CHECK
              and f[1] == 'peer:' + leaders[0] and f[4] == 'movedSession']
    coverage = set((dest / 'coverage.tsv').read_text().splitlines())
    new = coverage - seen if effective else set()
    return {'run_id': run_id, 'plan': plan, 'exact': exact, 'bound_response': bound,
            'effective': effective, 'target_after_fault': bool(guards),
            'owner_after_fault': bool(owner_after), 'selected_target_throws': len(throws),
            'new_coverage_lines': len(new), 'elapsed_seconds': receipt['elapsed_seconds'],
            'junit_exit': receipt['exit_code'], 'events_sha256': sha(dest / 'events.tsv'),
            'coverage_sha256': sha(dest / 'coverage.tsv'), 'receipt_sha256': sha(dest / 'run.json'),
            'coverage': sorted(coverage)}


def pilot(slot, slots, timeout, limit):
    calibration = calibrate()
    initial = calibration['healthy'][0]['candidates']
    stable = set(calibration['common_families'])
    # Distinct follower/owner response families first, then later ordinals.
    queue = [x['selector'] for x in sorted(initial,
             key=lambda x: (x['follower_sid'], x['seq'])) if x['family'] in stable]
    queue = list(dict.fromkeys(queue))[:MAX_PILOT]
    checkpoint = ROOT / 'pilot-checkpoint.json'
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state['queue'] != queue or state['agent_sha256'] != sha(AGENT):
            raise RuntimeError('resumed pilot queue/agent differs')
    else:
        state = {'status': 'running', 'queue': queue, 'next_index': 0, 'results': [],
                 'agent_sha256': sha(AGENT), 'budget_selected': MAX_PILOT,
                 'old_stage_plan_overlap': 0, 'old_stages_pooled': False}
        write_json(checkpoint, state)
    seen = set().union(*(set((ROOT / x / 'coverage.tsv').read_text().splitlines())
                         for x in ('healthy-a', 'healthy-b')))
    for row in state['results']:
        if row['effective']:
            seen.update(row['coverage'])
    to_run = min(len(queue), state['next_index'] + limit)
    for index in range(state['next_index'], to_run):
        run_id = 'pilot-{:02d}'.format(index + 1)
        run_one(run_id, [queue[index]], slot, slots, timeout)
        result = audit_trial(run_id, [queue[index]], seen)
        if result['effective']:
            seen.update(result['coverage'])
        state['results'].append(result)
        state['next_index'] = index + 1
        write_json(checkpoint, state)
        print(json.dumps({k: result[k] for k in ('run_id', 'exact', 'bound_response',
              'effective', 'selected_target_throws', 'new_coverage_lines')}, sort_keys=True), flush=True)
    if state['next_index'] == len(queue):
        state['status'] = 'pilot_complete'
        write_json(checkpoint, state)
    print(json.dumps({'status': state['status'], 'selected': state['next_index'],
                      'effective': sum(r['effective'] for r in state['results']),
                      'target_throws': sum(r['selected_target_throws'] for r in state['results'])},
                     sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('healthy', 'audit', 'pilot'))
    parser.add_argument('--worker-id', type=int, default=14)
    parser.add_argument('--worker-count', type=int, default=16)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--max-new-trials', type=int, default=MAX_PILOT)
    args = parser.parse_args()
    if not 1 <= args.worker_id <= args.worker_count or not 0 <= args.max_new_trials <= MAX_PILOT:
        parser.error('invalid slot or pilot bound')
    verify_assets()
    if args.mode == 'healthy':
        for name in ('healthy-a', 'healthy-b'):
            run_one(name, [], args.worker_id, args.worker_count, args.timeout)
        print(json.dumps(calibrate(), sort_keys=True), flush=True)
    elif args.mode == 'audit':
        print(json.dumps(calibrate(), sort_keys=True), flush=True)
    else:
        pilot(args.worker_id, args.worker_count, args.timeout, args.max_new_trials)


if __name__ == '__main__':
    main()
