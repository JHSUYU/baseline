#!/usr/bin/env python3
"""Bounded direct committed-txid file-write IOException trials."""
from __future__ import annotations
import csv,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
from campaign import HERE,parse,atomic

OUT=HERE/'file-trials';CHECKPOINT=OUT/'checkpoint.json'
APPLIED='<org.apache.hadoop.hdfs.util.BestEffortLongFile: void set(long)>#u100000'
SELECTORS=[(0,1,'IOException'),(1,2,'FileNotFoundException'),(0,3,'IOException'),(1,4,'FileNotFoundException')]

def file_events(path):
    result=[]
    for line in path.read_text().splitlines():
        nano,tid,kind,node,ordinal,suffix=line.split('\t',5)
        result.append({'nano':int(nano),'tid':int(tid),'event':kind,'node':int(node),
                       'hitOrdinal':int(ordinal),'pathSuffix':suffix})
    return result

def main():
    OUT.mkdir(exist_ok=True)
    healthy_manifest=json.loads((HERE/'file-healthy/manifest.json').read_text())
    if healthy_manifest['runtime']['exit']!=0:raise RuntimeError('file healthy JUnit failed')
    healthy=parse(HERE/'file-healthy/trace/runtime_trace.jsonl')
    if len(healthy['target'])!=1 or healthy['target'][0].get('condition')!='true':
        raise RuntimeError('file healthy exact target absent')
    observed=file_events(HERE/'file-healthy/file-events.tsv')
    source={(e['node'],e['hitOrdinal'],e['pathSuffix']) for e in observed if e['event']=='OBSERVED'}
    for node,ordinal,_ in SELECTORS:
        if not any(n==node and o==ordinal for n,o,_ in source):raise RuntimeError('selector absent in file healthy seed')
    state=json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {
        'case_id':'HDFS-09','methodology':'coverage_io_no_graph',
        'healthy_file_events':len(observed),'healthy_coverage_ids':len(healthy['coverage']),
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'results':[],'stop_reason':None}
    if state.get('stop_reason'):
        print('checkpoint already stopped:',state['stop_reason']);return
    union=set(healthy['coverage'])
    for result in state['results']:
        trace=HERE/result['trace']
        if trace.exists():union|=parse(trace)['coverage']
    for index,(node,ordinal,exception) in enumerate(SELECTORS[len(state['results']):],len(state['results'])+1):
        name=f'file-trial-{index:02d}';out=HERE/name;started=time.monotonic()
        if not (out/'manifest.json').exists():
            with (OUT/(name+'.log')).open('w') as log:
                subprocess.run([sys.executable,str(HERE/'run_file.py'),'--run-name',name,
                    '--node',str(node),'--ordinal',str(ordinal),'--exception',exception],
                    cwd=HERE,stdout=log,stderr=subprocess.STDOUT,check=False)
        manifest=json.loads((out/'manifest.json').read_text());feedback=parse(out/'trace/runtime_trace.jsonl')
        fe=file_events(out/'file-events.tsv')
        selected=[e for e in fe if e['node']==node and e['hitOrdinal']==ordinal]
        matched=[e for e in selected if e['event']=='MATCHED'];applied=[e for e in selected if e['event']=='APPLIED']
        marker=[e for e in feedback['events'] if e.get('event')=='BRANCH' and e.get('siteId')==APPLIED and e.get('outcome') is True]
        strict=(len(matched)==1 and len(applied)==1 and len(marker)==1 and
                len([e for e in fe if e['event']=='APPLIED'])==1)
        last=marker[0]['seq'] if marker else -1
        target_after=[t for t in feedback['target'] if t['seq']>last>=0]
        fatal=[t for t in target_after if t.get('condition')=='false' and t.get('outcome')=='CALL_SITE_THROW' and
               t.get('exceptionType')=='java.lang.IllegalArgumentException']
        coverage={x for x in feedback['coverage'] if APPLIED not in x}
        gain=coverage-union;union|=coverage
        status='unmatched' if not strict else 'lost_target' if not target_after else 'target_exception_candidate' if fatal else 'checked'
        result={'trial':name,'status':status,'selector':{'method':'BestEffortLongFile.set(long)',
            'call':'IOUtils.writeFully(FileChannel,ByteBuffer,long)','marker':'FAULT:HDFS_COMMITTED_FILE:WRITE_FULLY',
            'node':node,'hitOrdinal':ordinal,'pathSuffix':f'journalnode-{node}/test-journal/current/committed-txid',
            'exception':exception},'matched_count':len(matched),'applied_count':len(applied),
            'strict_injection':strict,'target_reached_after_fault':bool(target_after),
            'target_condition_after_fault':[x.get('condition') for x in target_after],
            'target_call_outcome_after_fault':[x.get('outcome') for x in target_after],
            'target_fatal_exception_count':len(fatal),'junit_exit':manifest['runtime']['exit'],
            'junit_seconds':manifest['runtime']['elapsed_seconds'],
            'trial_wall_seconds':round(time.monotonic()-started,3),
            'method_branch_coverage_ids':len(coverage),'new_coverage_ids':len(gain),
            'new_coverage_id_list':sorted(gain),'observed_file_events':len(fe),
            'trace':str((out/'trace/runtime_trace.jsonl').relative_to(HERE)),
            'completed_at_utc':datetime.now(timezone.utc).isoformat()}
        state['results'].append(result);state['coverage_union_ids']=len(union)
        if status=='lost_target':state['stop_reason']='selected_target_lost_after_file_fault'
        elif status=='target_exception_candidate':state['stop_reason']='exact_target_exception_requires_source_replay'
        atomic(CHECKPOINT,state)
        print(json.dumps({k:result[k] for k in ('trial','status','strict_injection','target_reached_after_fault','target_fatal_exception_count','new_coverage_ids','junit_seconds')}),flush=True)
        if state['stop_reason']:break
    if not state['stop_reason']:state['stop_reason']='bounded_file_trial_budget_reached'
    state['finished_at_utc']=datetime.now(timezone.utc).isoformat();atomic(CHECKPOINT,state)
    columns=['trial','status','selector','matched_count','applied_count','strict_injection',
             'target_reached_after_fault','target_condition_after_fault','target_call_outcome_after_fault',
             'target_fatal_exception_count','junit_exit','junit_seconds','trial_wall_seconds',
             'method_branch_coverage_ids','new_coverage_ids','observed_file_events']
    with (HERE/'file-trial-ledger.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for result in state['results']:
            w.writerow({k:json.dumps(result[k],separators=(',',':')) if isinstance(result[k],(dict,list)) else result[k] for k in columns})
    print('stop_reason',state['stop_reason'],flush=True)

if __name__=='__main__':main()
