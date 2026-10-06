#!/usr/bin/env python3
"""Checkpointed CrashFuzz-style exact I/O sequence mutation for HDFS-09.

Each new sequence extends a successful observed sequence by one later I/O
selector. No static analysis, graph planning, or closure gate is used.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
import csv,json,os,re,subprocess,sys,time
from pathlib import Path
from campaign import HERE,SITE,CALLEE,parse,point,token,phase as ipc_phase

OUT=HERE/'expansion';CHECKPOINT=OUT/'checkpoint.json'
TARGET_BUDGET=48;EXPANDED_BUDGET=96
START_DEPTH=4;EXPANDED_DEPTH=6
FILE_METHOD='<org.apache.hadoop.hdfs.util.BestEffortLongFile: void set(long)>'
FILE_APPLIED=FILE_METHOD+'#u100000'
ORIGINAL_COUNT=16
SYNTH_IPC={44,49,54}

def now():return datetime.now(timezone.utc).isoformat()

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.tmp.'+str(os.getpid()))
    with tmp.open('w') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def prod(ids):
    return {x for x in ids if not ('BRANCH:'+FILE_METHOD+'#u100' in x) and
            not ('getRpcResponse(' in x and any(f'#u{n}:' in x for n in SYNTH_IPC))}

def fault_token(fault):
    if fault['kind']=='ipc':return 'I:'+token(fault['selector'])
    return 'F:'+str(fault['node'])+':'+str(fault['ordinal'])+':'+fault['exception']

def physical_key(fault):
    if fault['kind']=='file':return 'F:'+str(fault['node'])+':'+str(fault['ordinal'])
    p=fault['selector'];return 'I:'+token({k:p.get(k) for k in ('siteId','occurrence','hitOrdinal','sourceKey')})

def channel_index(fault):
    if fault['kind']=='file':return fault['node']
    address=fault['selector']['occurrence']
    found=re.search(r'/<org\.apache\.hadoop\.hdfs\.qjournal\.client\.IPCLoggerChannel:[^>]*>@([0-9]+)',address)
    return int(found.group(1))%3 if found else None

def loss_equiv(parent_name,fault):
    # All exception variants at one exact I/O occurrence are equivalent
    # for scheduling after an observed target loss or no feedback gain.
    return (parent_name,physical_key(fault))

def file_fault(node,ordinal,exception):
    return {'kind':'file','node':int(node),'ordinal':int(ordinal),'exception':exception,
            'pathSuffix':f'journalnode-{node}/test-journal/current/committed-txid'}

def ipc_fault(selector):return {'kind':'ipc','selector':selector}

def branch_file_observation(event):
    if event.get('event')!='BRANCH' or event.get('outcome') is not False:return None
    site=event.get('siteId','')
    if not site.startswith(FILE_METHOD+'#u'):return None
    try:unit=int(site.rsplit('#u',1)[1])
    except ValueError:return None
    if unit<100100 or unit>=100500:return None
    code=unit-100100;node=code//100;ordinal=code%100
    if node not in (0,1,2) or ordinal<1:return None
    return node,ordinal

def candidate_events(parsed):
    candidates=[]
    for selector,event in parsed['observed']:
        candidates.append((event['seq'],ipc_fault(selector),ipc_phase(event)))
    for event in parsed['events']:
        decoded=branch_file_observation(event)
        if decoded:
            node,ordinal=decoded
            for exception in ('IOException','FileNotFoundException'):
                candidates.append((event['seq'],file_fault(node,ordinal,exception),
                                   f'committed-write:jn{node}'))
    return candidates

def io_family(fault,stage=''):
    if fault['kind']=='file':return f"file:{fault['node']}:{fault['ordinal']}:{fault['exception']}"
    p=fault['selector'];address=p['occurrence']
    event={'occurrenceAddress':address}
    return 'ipc:'+ipc_phase(event)+':'+p['marker'].split(':')[-1]

def read_file_applied(path):
    found=[]
    if not path.exists():return found
    for line in path.read_text().splitlines():
        fields=line.split('\t',5)
        if len(fields)!=6 or fields[2]!='APPLIED':continue
        found.append((int(fields[3]),int(fields[4])))
    return found

def applied_events(parsed,run):
    ipc=[]
    for e in parsed['applied']:
        p=point(e)
        if p:ipc.append((e['seq'],ipc_fault(p),e.get('faultId')))
    file_rows=read_file_applied(run/'file-events.tsv')
    markers=[e for e in parsed['events'] if e.get('event')=='BRANCH' and
             e.get('siteId')==FILE_APPLIED and e.get('outcome') is True]
    file=[]
    for index,(node,ordinal) in enumerate(file_rows):
        if index<len(markers):file.append((markers[index]['seq'],node,ordinal))
    return ipc,file,len(markers),len(file_rows)

def legacy_parents():
    ipc_state=json.loads((HERE/'trials/checkpoint.json').read_text())
    file_state=json.loads((HERE/'file-trials/checkpoint.json').read_text())
    parents=[]
    for result in ipc_state['results']:
        parents.append({'name':result['trial'],'sequence':[ipc_fault(p) for p in result['selectors']],
                        'trace':result['trace'],'run_dir':result['trial'],
                        'strict':result['strict_injection'],'target_after':result['target_reached_after_fault'],
                        'junit_exit':result['junit_exit'],'production_gain':result.get('new_coverage_ids',0)})
    for result in file_state['results']:
        s=result['selector']
        parents.append({'name':result['trial'],'sequence':[file_fault(s['node'],s['hitOrdinal'],s['exception'])],
                        'trace':result['trace'],'run_dir':result['trial'],
                        'strict':result['strict_injection'],'target_after':result['target_reached_after_fault'],
                        'junit_exit':result['junit_exit'],'production_gain':result.get('new_coverage_ids',0)})
    return parents

def select_next(parents,attempted,negative_equiv,parent_use,baseline_io,seen_families,seen_coverage,budget_index,max_depth):
    if budget_index<8:desired=2
    elif budget_index<16:desired=3
    elif budget_index<24:desired=4
    else:desired=2+(budget_index%3)
    if max_depth>4 and budget_index>=32:desired=5+(budget_index%2)
    options=[];audited=0
    injected_physical=Counter(physical_key(f) for parent in parents for f in parent['sequence'])
    injected_family=Counter(io_family(f) for parent in parents for f in parent['sequence'])
    injected_file_node=Counter(f['node'] for parent in parents for f in parent['sequence']
                               if f['kind']=='file')
    for parent in parents:
        if (not parent['strict'] or not parent['target_after'] or parent['junit_exit']!=0 or
            len(parent['sequence'])>=max_depth):continue
        parsed=parse(HERE/parent['trace']);target_seq=min((t['seq'] for t in parsed['target']),default=-1)
        if target_seq<0:continue
        ipc_applied,file_applied,marker_count,file_count=applied_events(parsed,HERE/parent['run_dir'])
        last=max([e['seq'] for e in parsed['applied']]+[x[0] for x in file_applied],default=-1)
        if last<0:continue
        current_physical={physical_key(f) for f in parent['sequence']}
        parent_families={io_family(f) for f in parent['sequence']}
        for seq,fault,phase in candidate_events(parsed):
            if not last<seq<target_seq:continue
            if physical_key(fault) in current_physical:continue
            if loss_equiv(parent['name'],fault) in negative_equiv:continue
            new_sequence=parent['sequence']+[fault]
            key=token(new_sequence)
            if key in attempted:continue
            audited+=1
            depth=len(new_sequence)
            family=io_family(fault)
            score=0.0
            score+=35 if depth==desired else 10 if abs(depth-desired)==1 else 0
            score+=12 if fault_token(fault) not in baseline_io else 0
            score+=8 if family not in seen_families else 0
            score+=45 if injected_physical[physical_key(fault)]==0 else max(
                0,12-4*injected_physical[physical_key(fault)])
            score+=12 if injected_family[family]==0 else 0
            if fault['kind']=='file':
                score+=35 if injected_file_node[fault['node']]==0 else max(
                    0,12-2*injected_file_node[fault['node']])
            score+=5 if family not in parent_families else 0
            score+=7 if fault['kind']=='file' and all(x['kind']!='file' for x in parent['sequence']) else 0
            score+=7 if fault['kind']=='ipc' and all(x['kind']!='ipc' for x in parent['sequence']) else 0
            score+=min(6,parent.get('production_gain',0))
            score-=20*parent_use.get(parent['name'],0)
            active_channels={channel_index(x) for x in parent['sequence']}
            next_channel=channel_index(fault)
            if next_channel is not None and next_channel in active_channels:score+=30
            elif next_channel is not None and any(x is not None for x in active_channels):score-=15
            score+=2 if phase not in {io_family(x) for x in parent['sequence']} else 0
            score-=seq/1000000
            options.append((score,key,parent,fault,new_sequence,phase))
    if not options:return None,audited
    options.sort(key=lambda o:(-o[0],o[1]))
    return options[0],audited

def write_ipc_trial(path,sequence):
    faults=[{'faultId':token(f['selector']),**f['selector'],'value':True}
            for f in sequence if f['kind']=='ipc']
    if faults:atomic(path,{'schemaVersion':1,'faults':faults})
    return bool(faults)

def parse_result(run,sequence,base_coverage,seed_io,wall):
    parsed=parse(run/'trace/runtime_trace.jsonl')
    ipc_applied,file_applied,marker_count,file_count=applied_events(parsed,run)
    # The file probe reports its own matched and applied rows. Match each file
    # trace marker to the correspondingly ordered APPLIED row in the TSV.
    file_faults=[f for f in sequence if f['kind']=='file']
    file_actual=[]
    for i,(seq,node,ordinal) in enumerate(file_applied):
        match=next((f for f in file_faults if f['node']==node and f['ordinal']==ordinal),None)
        if match:file_actual.append((seq,match))
    combined=sorted([(seq,f) for seq,f,_ in ipc_applied]+file_actual,key=lambda x:x[0])
    expected=[fault_token(f) for f in sequence]
    actual=[fault_token(f) for _,f in combined]
    ipc_expected=[fault_token(f) for f in sequence if f['kind']=='ipc']
    ipc_actual=[fault_token(f) for _,f,_ in ipc_applied]
    ipc_ids=[fid for _,_,fid in ipc_applied]
    strict=(actual==expected and len(actual)==len(expected) and ipc_actual==ipc_expected and
            ipc_ids==[token(f['selector']) for f in sequence if f['kind']=='ipc'] and
            len(parsed['matched'])>=len(ipc_expected) and marker_count==file_count==len(file_faults))
    last=max((seq for seq,_ in combined),default=-1)
    after=[t for t in parsed['target'] if t['seq']>last>=0]
    fatal=[t for t in after if t.get('condition')=='false' and t.get('outcome')=='CALL_SITE_THROW' and
           t.get('exceptionType')=='java.lang.IllegalArgumentException']
    allcov=prod(parsed['coverage']);gain=allcov-base_coverage
    observed=candidate_events(parsed)
    exact_io={fault_token(f) for _,f,_ in observed}
    new_io=exact_io-seed_io
    families={io_family(f) for _,f,_ in observed}
    status=('unmatched' if not strict else 'lost_target' if not after else
            'target_exception_candidate' if fatal else 'junit_failure_non_target' if
            json.loads((run/'manifest.json').read_text())['runtime']['exit']!=0 else 'checked')
    manifest=json.loads((run/'manifest.json').read_text())
    return {'status':status,'strict_injection':strict,'matched_count':len(parsed['matched'])+len(file_applied),
            'applied_count':len(combined),'target_reached_after_fault':bool(after),
            'target_condition_after_fault':[x.get('condition') for x in after],
            'target_call_outcome_after_fault':[x.get('outcome') for x in after],
            'target_fatal_exception_count':len(fatal),'junit_exit':manifest['runtime']['exit'],
            'junit_seconds':manifest['runtime']['elapsed_seconds'],'trial_wall_seconds':round(wall,3),
            'coverage_production_ids':len(allcov),'production_gain_ids':len(gain),
            'production_gain_id_list':sorted(gain),'observed_io_selectors':len(exact_io),
            'new_exact_io_selectors':len(new_io),'new_exact_io_selector_ids':sorted(new_io),
            'observed_io_families':sorted(families),'last_applied_seq':last,
            'target_seq_after_fault':[x['seq'] for x in after]}

def summarize_seen(parents):
    coverage=set();families=set()
    for parent in parents:
        trace=HERE/parent['trace']
        if trace.exists():
            parsed=parse(trace);coverage|=prod(parsed['coverage'])
        for f in parent['sequence']:families.add(io_family(f))
    return coverage,families

def main():
    OUT.mkdir(exist_ok=True)
    legacy=legacy_parents()
    if len(legacy)!=ORIGINAL_COUNT:raise RuntimeError('old trial count changed')
    healthy=parse(HERE/'expansion-healthy/trace/runtime_trace.jsonl')
    if len(healthy['target'])!=1 or healthy['target'][0].get('condition')!='true':
        raise RuntimeError('expansion healthy target absent')
    seed_io={fault_token(f) for _,f,_ in candidate_events(healthy)}
    seed_families={io_family(f) for _,f,_ in candidate_events(healthy)}
    checkpoint=json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {
        'case_id':'HDFS-09','methodology':'coverage_io_no_graph','existing_trials':ORIGINAL_COUNT,
        'trial_budget':TARGET_BUDGET,'max_faults_per_trial':START_DEPTH,
        'started_at_utc':now(),'results':[],'stop_reason':None}
    if checkpoint.get('stop_reason'):
        print('already stopped:',checkpoint['stop_reason'],flush=True);return
    initial_count=len(checkpoint['results'])
    max_new=int(os.environ.get('HDFS09_MAX_NEW_TRIALS','0'))
    parents=list(legacy)
    for result in checkpoint['results']:
        parents.append({'name':result['trial'],'sequence':result['sequence'],'trace':result['trace'],
                        'run_dir':result['trial'],'strict':result['strict_injection'],
                        'target_after':result['target_reached_after_fault'],
                        'junit_exit':result['junit_exit'],'production_gain':result['production_gain_ids']})
    attempted={token(parent['sequence']) for parent in parents}
    negative_equiv={loss_equiv(r['parent_trial'],r['appended_selector']) for r in checkpoint['results']
                    if r['status']=='lost_target' or
                    (r['production_gain_ids']==0 and r['new_exact_io_selectors']==0)}
    parent_use=Counter(r['parent_trial'] for r in checkpoint['results'])
    baseline_coverage,seen_families=summarize_seen(parents)
    seen_families|=seed_families
    for index in range(len(checkpoint['results'])+1,EXPANDED_BUDGET-ORIGINAL_COUNT+1):
        total_before=ORIGINAL_COUNT+len(checkpoint['results'])
        if total_before>=checkpoint['trial_budget']:
            recent=checkpoint['results'][-8:]
            late=any(r['production_gain_ids']>0 or r.get('new_io_families',0)>0 for r in recent)
            if checkpoint['trial_budget']==TARGET_BUDGET and late:
                checkpoint['trial_budget']=EXPANDED_BUDGET
                checkpoint['max_faults_per_trial']=EXPANDED_DEPTH
                checkpoint['expansion_reason']='production coverage or I/O family novelty in last eight trials'
                atomic(CHECKPOINT,checkpoint)
                print('expanded budget to 96 trials / depth 6 for late novelty',flush=True)
            else:
                checkpoint['stop_reason']='authorized_trial_budget_reached'
                break
        pick,audited=select_next(parents,attempted,negative_equiv,parent_use,seed_io,seen_families,baseline_coverage,
                                 len(checkpoint['results']),checkpoint['max_faults_per_trial'])
        if pick is None:
            checkpoint['stop_reason']='equivalence_exhaustion_no_new_observed_extension'
            checkpoint['equivalence_audit']={'eligible_parents':sum(p['strict'] and p['target_after'] and
                p['junit_exit']==0 and len(p['sequence'])<checkpoint['max_faults_per_trial'] for p in parents),
                'unattempted_observed_extensions':audited,'attempted_sequences':len(attempted)}
            break
        score,key,parent,fault,sequence,phase=pick
        attempted.add(key)
        name=f'expand-{index:02d}';run=HERE/name;ipc_trial=OUT/(name+'-ipc.json')
        has_ipc=write_ipc_trial(ipc_trial,sequence)
        file_plan=';'.join(f"{f['node']}:{f['ordinal']}:{f['exception']}" for f in sequence if f['kind']=='file')
        cmd=[sys.executable,str(HERE/'run_file.py'),'--run-name',name]
        if has_ipc:cmd+=['--ipc-trial',str(ipc_trial)]
        if file_plan:cmd+=['--file-plan',file_plan]
        started=time.monotonic()
        if not (run/'manifest.json').exists():
            with (OUT/(name+'.log')).open('w') as log:
                subprocess.run(cmd,cwd=HERE,stdout=log,stderr=subprocess.STDOUT,check=False)
        if not (run/'manifest.json').exists():raise RuntimeError(f'{name} lacks manifest')
        feedback=parse_result(run,sequence,baseline_coverage,seed_io,time.monotonic()-started)
        newfamilies=set(feedback['observed_io_families'])-seen_families
        feedback.update({'trial':name,'phase':'sequence_expansion','sequence':sequence,
            'sequence_ids':[fault_token(f) for f in sequence],'depth':len(sequence),
            'parent_trial':parent['name'],'appended_phase':phase,
            'appended_selector':fault,'selection_score':round(score,3),
            'selection_candidates_audited':audited,
            'new_io_families':len(newfamilies),'new_io_family_list':sorted(newfamilies),
            'trace':str((run/'trace/runtime_trace.jsonl').relative_to(HERE)),
            'file_events':str((run/'file-events.tsv').relative_to(HERE)),
            'completed_at_utc':now()})
        checkpoint['results'].append(feedback)
        atomic(CHECKPOINT,checkpoint)
        from publish_progress import publish
        publish()
        print(json.dumps({k:feedback[k] for k in ('trial','depth','parent_trial','appended_phase',
            'status','strict_injection','target_reached_after_fault','applied_count',
            'production_gain_ids','new_exact_io_selectors','new_io_families','junit_seconds')}),flush=True)
        if max_new and len(checkpoint['results'])-initial_count>=max_new:
            print('checkpoint_paused_after_new_trials',max_new,flush=True)
            return
        if feedback['status']=='target_exception_candidate':
            checkpoint['stop_reason']='exact_target_exception_requires_source_replay'
            break
        parent_use[parent['name']]+=1
        if feedback['status']=='lost_target' or (feedback['production_gain_ids']==0 and
                                                 feedback['new_exact_io_selectors']==0):
            negative_equiv.add(loss_equiv(parent['name'],fault))
        if feedback['status']=='checked':
            parents.append({'name':name,'sequence':sequence,'trace':feedback['trace'],
                'run_dir':name,'strict':True,'target_after':True,'junit_exit':0,
                'production_gain':feedback['production_gain_ids']})
            baseline_coverage|=prod(parse(run/'trace/runtime_trace.jsonl')['coverage'])
            seen_families|=set(feedback['observed_io_families'])
    if not checkpoint.get('stop_reason'):checkpoint['stop_reason']='authorized_trial_budget_reached'
    checkpoint['finished_at_utc']=now()
    atomic(CHECKPOINT,checkpoint)
    from publish_progress import publish
    publish()
    columns=['trial','parent_trial','depth','appended_phase','status','sequence_ids','matched_count',
        'applied_count','strict_injection','target_reached_after_fault','target_condition_after_fault',
        'target_call_outcome_after_fault','target_fatal_exception_count','junit_exit','junit_seconds',
        'trial_wall_seconds','coverage_production_ids','production_gain_ids','new_exact_io_selectors',
        'new_io_families','trace']
    with (OUT/'trial-ledger.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for result in checkpoint['results']:
            writer.writerow({k:json.dumps(result[k],separators=(',',':')) if isinstance(result[k],list)
                             else result[k] for k in columns})
    print('stop_reason',checkpoint['stop_reason'],'total_trials',ORIGINAL_COUNT+len(checkpoint['results']),flush=True)

if __name__=='__main__':main()
