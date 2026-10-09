#!/usr/bin/env python3
"""Reconcile the single node1 HDFS-54 pilot onto node2 without replaying it.

Run from node0. The default is a read-only preflight. ``--stage-only`` copies
and verifies evidence without altering node2's 1/80 state or pause marker;
it is safe while another case uses the node2 JVM slot. Apply only after the
node2 JVM-slot owner explicitly releases it. The pause marker stays in place
until all copied data and the 2/80 checkpoint are verified.
"""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path('/users/ZhenyuLi/hdfs54-original-campaign/runs')
TRIAL = 'trial-0002-09a99b3dfe331261-r0'
PLAN_ID = '09a99b3dfe331261'
FIRST_ID = '01f09073125e7810'
OLD_SHA = '8728827521d8d650325f9801add8d15ba32dd38e3b458860f0ce1029ed256cf8'
NEW_SHA = 'ecf48f4d5912c5b55045a8895e300ab4e6c4c5bb873eb993d5d4d70829af05f8'
TRIAL_HASHES = {
    'manifest.json': '3866b76d3bacbee89b40293186eaf25b5120549da18b53403d6983accdd052fb',
    'runtime_trace.jsonl': 'c9ab46255bce3d5853cd019ebe67483a5dd4da1c8771ed07b8acd1df03013eed',
    'jacoco.exec': '8b10e347cf4c10f4d1f174510c40722af0482902c0d6fbd151e95fc376bc6ccb',
    'junit.log': 'd9899a07d1e011bb9c275bdf634634018148e51c956651d21991cee43b3272e4',
}
SSH_KEY = str(Path.home() / '.ssh/id_ed25519_nodes')
SSH_ARGS = ['-i', SSH_KEY, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes']


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def remote_python(node, script):
    proc = subprocess.run(
        ['ssh', *SSH_ARGS, f'ZhenyuLi@{node}', 'python3 -'],
        input=script, text=True, capture_output=True,
    )
    if proc.returncode:
        raise RuntimeError(f'{node}: {proc.stderr.strip()}')
    return json.loads(proc.stdout)


def scp(source, destination, recursive=False):
    command = ['scp', *SSH_ARGS]
    if recursive:
        command.append('-r')
    subprocess.run([*command, source, destination], check=True)


def status_script():
    return '''
import hashlib,json,pathlib,shutil,subprocess
r=pathlib.Path(%r)
s=r/'campaign-state.json'
state=json.loads(s.read_text())
sessions=subprocess.run(['tmux','list-sessions','-F','#S'],capture_output=True,text=True).stdout.splitlines()
jps=subprocess.run(['/usr/lib/jvm/java-8-openjdk-amd64/bin/jps','-l'],capture_output=True,text=True).stdout.splitlines()
jvms=[line for line in jps if not line.endswith('sun.tools.jps.Jps')]
marker=r/'.node1-pilot-active'
lease=r/'.node1-pilot-lease.json'
print(json.dumps({'sha':hashlib.sha256(s.read_bytes()).hexdigest(),
 'effective':state['effective'],'attempts':[a['id'] for a in state['attempts']],
 'queue':len(state['queue']),'in_flight':state['in_flight'],
 'marker':json.loads(marker.read_text()) if marker.exists() else None,
 'lease':json.loads(lease.read_text()) if lease.exists() else None,
 'sessions':sessions,'jvms':jvms,'free_gib':round(shutil.disk_usage(r).free/2**30,2)}))
''' % str(ROOT)


def verify_state(path):
    assert sha256(path) == NEW_SHA, 'node1 updated checkpoint SHA mismatch'
    state = json.loads(path.read_text())
    assert state['effective'] == 2 and len(state['attempts']) == 2
    assert [x['id'] for x in state['attempts']] == [FIRST_ID, PLAN_ID]
    assert state['in_flight'] is None and len(state['queue']) == 46
    assert state['attempts'][1]['result'] == 'effective'
    assert state['attempts'][1]['requested'] == 2
    assert state['attempts'][1]['matched'] == state['attempts'][1]['applied'] == 2
    assert state['attempts'][1]['target_after_final_fault'] == 1
    assert not {FIRST_ID, PLAN_ID} & {x['id'] for x in state['queue']}


def finalize_script(hashes):
    payload = {
        'root': str(ROOT), 'trial': TRIAL, 'plan_id': PLAN_ID,
        'first_id': FIRST_ID, 'old_sha': OLD_SHA, 'new_sha': NEW_SHA,
        'trial_hashes': TRIAL_HASHES, 'transfer_hashes': hashes,
    }
    return '''
import csv,hashlib,json,os,pathlib,shutil,subprocess,uuid
p=json.loads(%r)
r=pathlib.Path(p['root']); stage=r/'.node1-trial2-handoff'
def digest(f): return hashlib.sha256(f.read_bytes()).hexdigest()
def slot_clear():
 sessions=subprocess.run(['tmux','list-sessions','-F','#S'],capture_output=True,text=True).stdout.splitlines()
 jps=subprocess.run(['/usr/lib/jvm/java-8-openjdk-amd64/bin/jps','-l'],capture_output=True,text=True).stdout.splitlines()
 assert not [x for x in jps if not x.endswith('sun.tools.jps.Jps')], 'node2 JVM slot occupied'
 assert not [x for x in sessions if x.startswith('solr36_37') or x.startswith('hdfs54_original')], 'node2 tmux slot occupied'
slot_clear()
marker=r/'.node1-pilot-active'
state=r/'campaign-state.json'; current=digest(state)
assert current in (p['old_sha'],p['new_sha']), 'node2 checkpoint changed unexpectedly'
if current==p['new_sha'] and not marker.exists():
 print(json.dumps({'result':'already_reconciled','effective':2})); raise SystemExit(0)
assert marker.exists() and json.loads(marker.read_text())['checkpoint_sha256']==p['old_sha']
assert stage.is_dir(), 'staged transfer missing'
for name,h in p['transfer_hashes'].items():
 assert digest(stage/name)==h, 'staged transfer mismatch: '+name
source=stage/p['trial']
for name,h in p['trial_hashes'].items():
 assert digest(source/name)==h, 'trial evidence mismatch: '+name
manifest=json.loads((source/'manifest.json').read_text())
assert manifest['requested_faults']==manifest['matched_faults']==manifest['applied_faults']==2
assert manifest['target_after_final_fault']==1 and manifest['target_false_after_final_fault']==0
assert manifest['junit_exit']==0 and manifest['junit']['failures']==0
new_state=json.loads((stage/'checkpoint.new.json').read_text())
assert new_state['effective']==2 and [a['id'] for a in new_state['attempts']]==[p['first_id'],p['plan_id']]
assert len(new_state['queue'])==46 and new_state['in_flight'] is None
with (stage/'ledger.new.csv').open() as f: rows=list(csv.DictReader(f))
assert len(rows)==2 and [x['id'] for x in rows]==[p['first_id'],p['plan_id']]
assert rows[1]['result']=='effective' and rows[1]['applied']=='2'
assert (stage/'plan2.tsv').read_text().count('\\n')==2
target=r/p['trial']
if target.exists():
 for name,h in p['trial_hashes'].items(): assert digest(target/name)==h
else:
 temp=r/('.copying-'+p['trial']+'-'+uuid.uuid4().hex)
 shutil.copytree(source,temp); os.replace(temp,target)
def atomic_copy(source,destination):
 temp=destination.with_name('.'+destination.name+'.handoff-'+uuid.uuid4().hex)
 shutil.copy2(source,temp); os.replace(temp,destination)
plan=r/'plans'/(p['plan_id']+'.tsv')
if plan.exists(): assert digest(plan)==p['transfer_hashes']['plan2.tsv']
else: atomic_copy(stage/'plan2.tsv',plan)
atomic_copy(stage/'ledger.new.csv',r/'trial-ledger.csv')
atomic_copy(stage/'checkpoint.new.json',state)
assert digest(state)==p['new_sha'] and digest(target/'runtime_trace.jsonl')==p['trial_hashes']['runtime_trace.jsonl']
slot_clear()
marker.unlink()
print(json.dumps({'result':'reconciled','effective':2,'queue':46,'trial':str(target),'checkpoint_sha256':digest(state)}))
''' % json.dumps(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--owner-released', action='store_true',
                        help='explicit confirmation from the node2 JVM-slot owner')
    args = parser.parse_args()
    one = remote_python('node1', status_script())
    two = remote_python('node2', status_script())
    assert one['sha'] == NEW_SHA and one['effective'] == 2
    assert one['attempts'] == [FIRST_ID, PLAN_ID] and one['in_flight'] is None
    assert one['lease'] and one['lease']['checkpoint_sha256'] == OLD_SHA
    assert two['sha'] in (OLD_SHA, NEW_SHA)
    assert two['marker'] and two['marker']['checkpoint_sha256'] == OLD_SHA
    print(json.dumps({'node1': one, 'node2': two}, sort_keys=True))
    assert not (args.apply and args.stage_only)
    if not (args.apply or args.stage_only):
        return
    if args.apply:
        assert args.owner_released, '--apply requires --owner-released'
        assert not two['jvms'], 'node2 JVM slot occupied'
        assert not [x for x in two['sessions'] if x.startswith(('solr36_37', 'hdfs54_original'))]
    else:
        assert not [x for x in two['sessions'] if x.startswith('hdfs54_original')]
    assert two['free_gib'] >= 8, 'node2 disk headroom below 8 GiB'
    assert not [x for x in one['sessions'] if x.startswith('hdfs54_original')]
    with tempfile.TemporaryDirectory(prefix='hdfs54-trial2-handoff-') as temp_name:
        temp = Path(temp_name)
        scp(f'ZhenyuLi@node1:{ROOT / "campaign-state.json"}', str(temp / 'checkpoint.new.json'))
        scp(f'ZhenyuLi@node1:{ROOT / "trial-ledger.csv"}', str(temp / 'ledger.new.csv'))
        scp(f'ZhenyuLi@node1:{ROOT / "plans" / (PLAN_ID + ".tsv")}', str(temp / 'plan2.tsv'))
        scp(f'ZhenyuLi@node1:{ROOT / TRIAL}', str(temp), recursive=True)
        verify_state(temp / 'checkpoint.new.json')
        with (temp / 'ledger.new.csv').open() as file:
            rows = list(csv.DictReader(file))
        assert len(rows) == 2 and [x['id'] for x in rows] == [FIRST_ID, PLAN_ID]
        for name, expected in TRIAL_HASHES.items():
            assert sha256(temp / TRIAL / name) == expected, name
        hashes = {name: sha256(temp / name) for name in
                  ('checkpoint.new.json', 'ledger.new.csv', 'plan2.tsv')}
        remote_python('node2', f'import json,pathlib; p=pathlib.Path({str(ROOT / ".node1-trial2-handoff")!r}); p.mkdir(exist_ok=True); print(json.dumps({{"stage":str(p)}}))')
        for name in hashes:
            scp(str(temp / name), f'ZhenyuLi@node2:{ROOT / ".node1-trial2-handoff" / name}')
        scp(str(temp / TRIAL), f'ZhenyuLi@node2:{ROOT / ".node1-trial2-handoff"}', recursive=True)
        if args.stage_only:
            expected = {**hashes, **{TRIAL + '/' + k: v for k, v in TRIAL_HASHES.items()}}
            stage_status = remote_python('node2', '''
import hashlib,json,pathlib
r=pathlib.Path('/users/ZhenyuLi/hdfs54-original-campaign/runs')
p=r/'.node1-trial2-handoff'
expected=json.loads(%r)
actual={name:hashlib.sha256((p/name).read_bytes()).hexdigest() for name in expected}
assert actual==expected, 'node2 staged artifact hash mismatch'
print(json.dumps({'result':'staged_only','trial_dir':str(p/'trial-0002-09a99b3dfe331261-r0'),
 'checkpoint_sha256':actual['checkpoint.new.json'],
 'verified_files':len(actual),
 'node2_effective':json.loads((r/'campaign-state.json').read_text())['effective'],
 'pause_marker_present':(r/'.node1-pilot-active').exists()}))
''' % json.dumps(expected))
            assert stage_status['checkpoint_sha256'] == NEW_SHA
            assert stage_status['node2_effective'] == 1 and stage_status['pause_marker_present']
            print(json.dumps(stage_status, sort_keys=True))
            return
        print(json.dumps(remote_python('node2', finalize_script(hashes)), sort_keys=True))


if __name__ == '__main__':
    main()
