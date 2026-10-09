#!/usr/bin/env python3
"""Verify and archive only completed HDFS-40 case-local raw evidence."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
CAMPAIGN=ROOT/'campaign'
ARCHIVE=ROOT/'raw-evidence.tar.gz'
RECEIPT=ROOT/'raw-evidence-receipt.json'


def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()


def main()->None:
    state=json.loads((CAMPAIGN/'checkpoint.json').read_text())
    audit=json.loads((ROOT/'audit.json').read_text())
    if state['active'] is not None or not state['stop_reason']:
        raise RuntimeError('campaign has not stopped at a completed-trial boundary')
    if audit.get('audited_trials')!=len(state['completed']) or not audit.get('all_checks_passed'):
        raise RuntimeError('independent final audit missing or stale')
    files=[]
    for pattern in ('README.md','source-provenance.json','source/main/**/*.java',
                    'source/test/**/*.java','source/test-resources/**/*',
                    'system-test/*.java','system-test/*.py',
                    'campaign/*.py','campaign/*.json','campaign/*.json.gz',
                    'campaign/*.csv','campaign/*.log','campaign/plans/*.tsv',
                    'campaign/trial-*/manifest.json',
                    'campaign/trial-*/trace/runtime_trace.jsonl',
                    'campaign/trial-*/jacoco.exec',
                    'campaign/trial-*/coverage.tsv',
                    'campaign/trial-*/junit.log.gz',
                    'campaign/trial-*/trial-result.json',
                    'campaign/trial-*/driver.log',
                    'campaign/trial-*/coverage-driver.log',
                    'healthy/*/manifest.json',
                    'healthy/*/trace/runtime_trace.jsonl',
                    'healthy/*/jacoco.exec',
                    'healthy/*/coverage.tsv',
                    'healthy/*/junit.log.gz'):
        files.extend(p for p in ROOT.glob(pattern) if p.is_file())
    files.append(ROOT.parent/'README.md')
    files.append(ROOT.parent/'result.json')
    files=list(dict.fromkeys(files))
    if not files:
        raise RuntimeError('no files to archive')
    hashes={}
    fd,temp=tempfile.mkstemp(prefix='.raw-evidence.',suffix='.tar.gz',dir=ROOT)
    os.close(fd)
    try:
        with tarfile.open(temp,'w:gz') as tar:
            for p in sorted(files):
                name=('case/'+str(p.relative_to(ROOT)) if p.is_relative_to(ROOT)
                      else 'summary/'+p.name)
                data=p.read_bytes()
                hashes[name]=sha(data)
                tar.add(p,arcname=name,recursive=False)
        with tarfile.open(temp,'r:gz') as tar:
            members={m.name:m for m in tar.getmembers() if m.isfile()}
            if set(members)!=set(hashes):
                raise RuntimeError('archive member set mismatch')
            for name,digest in hashes.items():
                stream=tar.extractfile(members[name])
                if stream is None or sha(stream.read())!=digest:
                    raise RuntimeError('archive hash mismatch: '+name)
        os.replace(temp,ARCHIVE)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    cleanup=sorted(ROOT.glob('campaign/trial-*/coverage.tsv'))
    cleanup+=sorted(ROOT.glob('healthy/*/coverage.tsv'))
    # JaCoCo is raw. Derived text is archived and can be regenerated.
    receipt={'case_id':'HDFS-40','completed_attempts':len(state['completed']),
             'stop_reason':state['stop_reason'],'verified_entries':len(hashes),
             'archive':str(ARCHIVE),'archive_sha256':sha(ARCHIVE.read_bytes()),
             'raw_file_sha256':hashes,
             'removed_regenerable_coverage_exports':[str(p.relative_to(ROOT)) for p in cleanup],
             'raw_traces_jacoco_junit_logs_preserved':True}
    output=(json.dumps(receipt,indent=2,sort_keys=True)+'\n').encode()
    fd,temp=tempfile.mkstemp(prefix='.receipt.',dir=ROOT)
    with os.fdopen(fd,'wb') as stream:
        stream.write(output);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,RECEIPT)
    for p in cleanup:p.unlink()
    print(json.dumps({'verified_entries':len(hashes),'archive_sha256':receipt['archive_sha256'],
                      'removed_derived_coverage':len(cleanup)}))

if __name__=='__main__':main()
