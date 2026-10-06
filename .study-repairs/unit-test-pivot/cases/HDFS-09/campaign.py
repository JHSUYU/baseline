#!/usr/bin/env python3
"""Bounded coverage/I/O guided HDFS-09 fault campaign. No graph operations."""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import datetime,timezone
import csv,hashlib,json,subprocess,sys,time
from pathlib import Path

HERE=Path(__file__).resolve().parent
TRACE=HERE/'healthy/trace/runtime_trace.jsonl'
TRIALS=HERE/'trials'; CHECKPOINT=TRIALS/'checkpoint.json'
SITE='<org.apache.hadoop.hdfs.qjournal.server.Journal: void checkRequest(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo)>#u78'
CALLEE='<org.apache.hadoop.util.Preconditions: void checkArgument(boolean,java.lang.Object)>'
PARENT='<org.apache.hadoop.hdfs.qjournal.server.Journal: void finalizeLogSegment(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo,long,long)>'
MAX_TRIALS=12

def rows(path):
    with path.open() as f:
        for line in f:
            if line.strip():yield json.loads(line)

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n');f.flush()
    temp.replace(path)

def token(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]

def point(event):
    if event.get('event') not in ('FAULT_POINT_OBSERVED','FAULT_MATCHED','FAULT_APPLIED'):return None
    if not str(event.get('marker','')).startswith('FAULT:'):return None
    value={k:event[k] for k in ('marker','siteId')}
    value['occurrence']=event['occurrenceAddress'];value['hitOrdinal']=event['hitOrdinal']
    if event.get('sourceKey'):value['sourceKey']=event['sourceKey']
    return value

def phase(event):
    address=event['occurrenceAddress']
    for name in ('hasSomeData','format','recoverUnfinalizedSegments','startLogSegment','sendEdits','finalizeLogSegment'):
        if name in address:
            if name=='startLogSegment':
                return name+'@'+('1' if 'startLogSegment(long,int)>@1' in address else '0')
            if name=='sendEdits':
                for n in range(6):
                    if f'sendEdits(long,long,int,byte[])>@{n}' in address:return name+'@'+str(n)
            if name=='finalizeLogSegment':
                return name+'@'+('1' if 'finalizeLogSegment(long,long)>@1' in address else '0')
            return name
    return 'other'

def parse(path):
    events=list(rows(path)); calls={e.get('callId'):e for e in events if e.get('event')=='METHOD_ENTER'}
    args=defaultdict(dict)
    for e in events:
        if e.get('event')=='METHOD_ARGUMENT':args[e.get('callId')][e.get('argumentIndex')]=e.get('primitiveValue')
    applied=[e for e in events if e.get('event')=='FAULT_APPLIED']
    matched=[e for e in events if e.get('event')=='FAULT_MATCHED']
    last=max((e.get('seq',-1) for e in applied),default=-1)
    coverage=set(); points={};observed=[]
    inv={}; target=[]
    for e in events:
        kind=e.get('event')
        if kind=='METHOD_ENTER' and e.get('method'):coverage.add('METHOD:'+e['method'])
        if kind=='BRANCH' and e.get('siteId'):coverage.add('BRANCH:'+e['siteId']+':'+str(e.get('outcome')))
        if kind=='FAULT_POINT_OBSERVED':
            p=point(e)
            if p: points[token(p)]=(p,e);observed.append((p,e))
        if e.get('siteId')==SITE and e.get('declaredCallee')==CALLEE:
            iid=e.get('invocationId')
            if kind=='CALL_SITE_ENTER':inv[iid]={'seq':e['seq'],'callId':e.get('callId'),'enter':e}
            elif kind=='CALL_ARGUMENT' and iid in inv and e.get('argumentIndex')==0:inv[iid]['condition']=e.get('primitiveValue')
            elif kind in ('CALL_SITE_RETURN','CALL_SITE_THROW') and iid in inv:inv[iid]['outcome']=kind
    exit_throw={e.get('callId'):e for e in events if e.get('event')=='METHOD_EXIT_THROW'}
    for iid,call in inv.items():
        c=calls.get(call['callId'],{});parent=calls.get(c.get('parentCallId'),{})
        if (c.get('sourceKey')=='jn2#epoch0' and c.get('requestApi')=='originalSingleWriter'
            and parent.get('method')==PARENT and args.get(parent.get('callId'),{}).get(1)=='4'
            and args.get(parent.get('callId'),{}).get(2)=='4'):
            call['sourceKey']=c.get('sourceKey');call['parentArgs']=args.get(parent.get('callId'))
            thrown=exit_throw.get(call['callId'],{})
            call['exceptionType']=thrown.get('runtimeType')
            target.append(call)
    return {'events':events,'applied':applied,'matched':matched,'last_applied_seq':last,
            'points':points,'observed':observed,'coverage':coverage,'target':target,
            'target_all_calls':len(inv)}

def choose(pool,used,phase_seen,marker_seen,source_seen,last_gain):
    allowed={'startLogSegment@0','sendEdits@0','finalizeLogSegment@0',
             'startLogSegment@1','sendEdits@3','sendEdits@4','finalizeLogSegment@1'}
    options=[]
    for pid,(p,e,origin) in pool.items():
        if pid in used or phase(e) not in allowed:continue
        ph=phase(e);marker=p['marker'];source=p.get('sourceKey','')
        score=(12 if ph not in phase_seen else 0)+(8 if marker not in marker_seen else 0)
        score+= (4 if source not in source_seen else 0)
        score+= (5 if origin=='feedback' and last_gain>0 else 0)
        score+= {'startLogSegment@0':7,'sendEdits@0':6,'finalizeLogSegment@0':5,
                 'startLogSegment@1':4,'sendEdits@3':3,'sendEdits@4':2,'finalizeLogSegment@1':1}.get(ph,0)
        score-=e.get('seq',0)/100000
        options.append((score,pid,p,e,origin))
    if not options:return None
    options.sort(key=lambda x:(-x[0],x[1]))
    return options[0]

def main():
    TRIALS.mkdir(exist_ok=True)
    healthy=parse(TRACE)
    if len(healthy['target'])!=1 or healthy['target'][0].get('condition')!='true' or healthy['target'][0].get('outcome')!='CALL_SITE_RETURN':
        raise RuntimeError('healthy selected #u78 identity not uniquely true/returned')
    seed_target=healthy['target'][0]
    seed_limit=seed_target['seq']
    pool={}
    for p,e in healthy['observed']:
        if e.get('seq',0)<seed_limit:pool[token(p)]=(p,e,'healthy')
    state=json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {
        'case_id':'HDFS-09','test':'org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#testSingleWriter',
        'target_site':SITE,'target_selector':{'sourceKey':'jn2#epoch0','requestApi':'originalSingleWriter',
        'parentMethod':PARENT,'startTxId':4,'endTxId':4},
        'healthy_target':{'seq':seed_target['seq'],'condition':seed_target['condition'],'outcome':seed_target['outcome']},
        'healthy_fault_points':len(pool),'healthy_coverage_ids':len(healthy['coverage']),
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'results':[],'stop_reason':None}
    used={pid for result in state['results'] for pid in result['selector_ids']}
    phase_seen={result['phase'] for result in state['results']}
    marker_seen={m for result in state['results'] for m in result['markers']}
    source_seen={s for result in state['results'] for s in result['sources']}
    coverage_union=set(healthy['coverage']);last_gain=0
    for result in state['results']:
        trace=HERE/result['trace']
        if trace.exists():
            feedback=parse(trace);coverage_union|=feedback['coverage']
            for p,e in feedback['observed']:
                pid=token(p)
                if pid not in pool and e.get('seq',0)<max((t['seq'] for t in feedback['target']),default=10**10):
                    pool[pid]=(p,e,'feedback')
        last_gain=result.get('new_coverage_ids',0)
    if state.get('stop_reason'):
        print('checkpoint already stopped:',state['stop_reason'],flush=True);return
    for index in range(len(state['results'])+1,MAX_TRIALS+1):
        selected=choose(pool,used,phase_seen,marker_seen,source_seen,last_gain)
        if selected is None:
            state['stop_reason']='candidate_pool_exhausted';break
        _,pid,p,e,origin=selected
        selection=[p]
        name=f'trial-{index:02d}';trial=TRIALS/(name+'.json')
        atomic(trial,{'schemaVersion':1,'faults':[{'faultId':token(s),**s,'value':True} for s in selection]})
        out=HERE/name;started=time.monotonic()
        if not (out/'manifest.json').exists():
            with (TRIALS/(name+'.log')).open('w') as log:
                subprocess.run([sys.executable,str(HERE/'run_original.py'),'--run-name',name,'--trial',str(trial)],
                               cwd=HERE,stdout=log,stderr=subprocess.STDOUT,check=False)
        manifest=json.loads((out/'manifest.json').read_text());feedback=parse(out/'trace/runtime_trace.jsonl')
        applied=[point(x) for x in feedback['applied']]
        strict=(len(applied)==len(selection) and [token(x) for x in applied]==[token(x) for x in selection]
                and [x.get('faultId') for x in feedback['applied']]==[token(x) for x in selection]
                and len(feedback['matched'])>=len(selection))
        after=[x for x in feedback['target'] if x['seq']>feedback['last_applied_seq']>=0]
        fatal=[x for x in after if x.get('condition')=='false' and x.get('outcome')=='CALL_SITE_THROW'
               and x.get('exceptionType')=='java.lang.IllegalArgumentException']
        gain=feedback['coverage']-coverage_union;coverage_union|=feedback['coverage']
        new_points=[]
        for q,raw in feedback['observed']:
            qid=token(q)
            if qid not in pool and raw.get('seq',0)<max((t['seq'] for t in feedback['target']),default=10**10):
                pool[qid]=(q,raw,'feedback');new_points.append(qid)
        status=('unmatched' if not strict else 'lost_target' if not after else
                'target_exception_candidate' if fatal else 'checked')
        result={'trial':name,'status':status,'phase':phase(e),'markers':[p['marker']],
            'sources':[p.get('sourceKey','')],'selectors':selection,'selector_ids':[pid],
            'selected_from':origin,'matched_count':len(feedback['matched']),'applied_count':len(feedback['applied']),
            'strict_injection':strict,'target_reached_after_fault':bool(after),
            'target_condition_after_fault':[x.get('condition') for x in after],
            'target_call_outcome_after_fault':[x.get('outcome') for x in after],
            'target_fatal_exception_count':len(fatal),'junit_exit':manifest['runtime']['exit'],
            'junit_seconds':manifest['runtime']['elapsed_seconds'],
            'trial_wall_seconds':round(time.monotonic()-started,3),
            'method_branch_coverage_ids':len(feedback['coverage']),
            'new_coverage_ids':len(gain),'new_coverage_id_list':sorted(gain),
            'new_io_selectors':len(new_points),'trace':str((out/'trace/runtime_trace.jsonl').relative_to(HERE)),
            'completed_at_utc':datetime.now(timezone.utc).isoformat()}
        state['results'].append(result);used.add(pid);phase_seen.add(result['phase']);marker_seen.add(p['marker']);source_seen.add(p.get('sourceKey',''));last_gain=len(gain)
        state['coverage_union_ids']=len(coverage_union)
        if status=='lost_target':state['stop_reason']='selected_target_lost_after_fault'
        elif status=='target_exception_candidate':state['stop_reason']='exact_target_exception_requires_source_replay'
        atomic(CHECKPOINT,state)
        print(json.dumps({k:result[k] for k in ('trial','phase','markers','status','strict_injection','target_reached_after_fault','target_fatal_exception_count','new_coverage_ids','junit_seconds')}),flush=True)
        if state['stop_reason']:break
    if not state['stop_reason']:state['stop_reason']='bounded_trial_budget_reached'
    state['finished_at_utc']=datetime.now(timezone.utc).isoformat()
    atomic(CHECKPOINT,state)
    columns=['trial','phase','markers','status','strict_injection','matched_count','applied_count',
             'target_reached_after_fault','target_condition_after_fault','target_call_outcome_after_fault',
             'target_fatal_exception_count','junit_exit','junit_seconds','trial_wall_seconds',
             'method_branch_coverage_ids','new_coverage_ids','new_io_selectors','selector_ids','selectors']
    with (HERE/'trial-ledger.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for result in state['results']:
            w.writerow({k:json.dumps(result[k],separators=(',',':')) if isinstance(result[k],list) else result[k] for k in columns})
    print('stop_reason',state['stop_reason'],flush=True)

if __name__=='__main__':main()
