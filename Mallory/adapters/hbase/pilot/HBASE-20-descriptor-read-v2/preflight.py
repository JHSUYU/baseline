#!/usr/bin/env python3
"""Fail-closed, JVM-free HBASE-20 v2 successor preflight."""
from pathlib import Path
import hashlib,json,subprocess,sys
BASE=Path('/users/ZhenyuLi/baseline')
HERE=Path(__file__).resolve().parent
OLD=BASE/'Mallory/adapters/hbase/pilot/HBASE-19-20-descriptor-read-v1'
RELEASE=BASE/'Mallory/dispatch/releases/224e15f3a987faab681ec46278650cca80ee3bc34b75ea2f68c87b911f9928f1 '
RELEASE=Path(str(RELEASE).strip())
CONFIG=HERE/'HBASE-20.descriptor-read-v2.full.json'
CONFIG_SHA='ff6f8bb4f61ef02311fc64007387eeb94a67975c06aee96b83029f0644dad0c0'
RELEASE_MANIFEST_SHA='76529af210390ebaea94685d46e66cccf168c61e144903137aeaca0767dd636c'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok,msg):
 if not ok: raise RuntimeError(msg)
def main():
 subprocess.run([sys.executable,str(OLD/'preflight.py'),'20'],check=True)
 manifest=json.loads((HERE/'package-manifest.json').read_text())
 for name,digest in manifest['files'].items():
  path=HERE/name;require(path.is_file() and sha(path)==digest,'package SHA mismatch: '+name)
 require(sha(CONFIG)==CONFIG_SHA,'config SHA mismatch')
 require(sha(RELEASE/'manifest.json')==RELEASE_MANIFEST_SHA,'release manifest SHA mismatch')
 require(manifest['scheduler_policy_commit']=='12018488','scheduler provenance changed')
 subprocess.run([sys.executable,'-m','Mallory.dispatch.core_release','--verify',str(RELEASE/'manifest.json')],cwd=BASE,check=True,stdout=subprocess.DEVNULL)
 old=json.loads((OLD/'HBASE-20.descriptor-read-v1.full.json').read_text())
 new=json.loads(CONFIG.read_text())
 expected=json.loads(json.dumps(old))
 expected['core_release']={'path':str(RELEASE),'release_id':RELEASE.name,'manifest_sha256':RELEASE_MANIFEST_SHA}
 expected['mapping']['scheduler_policy_commit']='12018488'
 expected['mapping']['scheduler_policy']='default_multi_fault_exploration_interval_4'
 require(new==expected,'scientific config differs beyond versioned scheduler metadata')
 sys.path.insert(0,str(RELEASE))
 from Mallory.core.campaign import validate_config
 validate_config(new)
 print(json.dumps({'status':'preflight_pass','case_id':'HBASE-20','config_sha256':CONFIG_SHA,'core_release':RELEASE.name,'scheduler_policy_commit':'12018488'},sort_keys=True))
if __name__=='__main__': main()
