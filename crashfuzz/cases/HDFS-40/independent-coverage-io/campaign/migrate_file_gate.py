#!/usr/bin/env python3
"""Clean-boundary queue migration: exclude no-op edit-log method entry faults."""
from __future__ import annotations
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'checkpoint.json'
PAUSE=ROOT/'pause.request'
BEFORE=ROOT/'checkpoint.before-file-gate.json.gz'
REPORT=ROOT/'file-gate-change.json'


def atomic(path:Path, data:bytes)->None:
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)


def main()->None:
    raw=STATE.read_bytes()
    state=json.loads(raw)
    if state['active'] is not None or state['stop_reason']!='paused_by_case_owner':
        raise RuntimeError('campaign has not paused on a completed-trial boundary')
    if state.get('selection_policy_version')=='rpc_semantic_v2':
        raise RuntimeError('migration already applied')
    if not PAUSE.exists():
        raise RuntimeError('pause marker missing')
    packed=gzip.compress(raw,mtime=0)
    atomic(BEFORE,packed)
    if hashlib.sha256(gzip.decompress(BEFORE.read_bytes())).hexdigest()!=hashlib.sha256(raw).hexdigest():
        raise RuntimeError('checkpoint backup checksum mismatch')
    old=len(state['queue'])
    kept=[item for item in state['queue']
          if all(point['marker']!='FILE_FLUSH' for point in item['sequence'])]
    state['queue']=kept
    state['stop_reason']=None
    state['selection_policy_version']='rpc_semantic_v2'
    state['file_marker_status']='observed_only_method_entry_can_return_without_write'
    report={'case_id':'HDFS-40','changed_at_utc':datetime.now(timezone.utc).isoformat(),
            'completed_trials_preserved':len(state['completed']),
            'before_checkpoint_sha256':hashlib.sha256(raw).hexdigest(),
            'queue_before':old,'queue_after':len(kept),'file_sequences_removed':old-len(kept),
            'rule':'No FILE_FLUSH method-entry exception selection; it precedes the no-op doubleBuf.isFlushed() return. Keep all completed RPC results and exact coverage evidence.',
            'backup':str(BEFORE)}
    atomic(REPORT,(json.dumps(report,indent=2,sort_keys=True)+'\n').encode())
    atomic(STATE,(json.dumps(state,indent=2,sort_keys=True)+'\n').encode())
    PAUSE.unlink()
    print(json.dumps(report))

if __name__=='__main__': main()
