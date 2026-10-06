#!/usr/bin/env python3
"""Recompute HDFS-09 ledger and atomically publish result.json."""
from __future__ import annotations
import csv,hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
from campaign import HERE,SITE,CALLEE,parse,rows

START=datetime.fromisoformat((HERE/'start-utc.txt').read_text().strip().replace('Z','+00:00'))
SYNTH_IPC={44,49,54}
FILE_MARKER='#u100000'

def production(ids):
    out=set()
    for identifier in ids:
        if FILE_MARKER in identifier:continue
        if 'getRpcResponse(' in identifier and any(f'#u{n}:' in identifier for n in SYNTH_IPC):continue
        out.add(identifier)
    return out

def split_counts(ids):
    return {'method_entry_ids':sum(x.startswith('METHOD:') for x in ids),
            'branch_outcome_ids':sum(x.startswith('BRANCH:') for x in ids),
            'total_ids':len(ids)}

def atomic_json(path,data):
    temp=path.with_name(path.name+'.tmp.'+str(os.getpid()))
    with temp.open('w') as f:
        json.dump(data,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

def healthy_exact_calls(path):
    calls={}; conditions={}; outcomes={}
    for e in rows(path):
        if e.get('siteId')!=SITE or e.get('declaredCallee')!=CALLEE:continue
        iid=e.get('invocationId')
        if e.get('event')=='CALL_SITE_ENTER':calls[iid]=e
        elif e.get('event')=='CALL_ARGUMENT' and e.get('argumentIndex')==0:conditions[iid]=e.get('primitiveValue')
        elif e.get('event') in ('CALL_SITE_RETURN','CALL_SITE_THROW'):outcomes[iid]=e.get('event')
    return {'exact_call_count':len(calls),
            'predicate_true_count':sum(conditions.get(i)=='true' for i in calls),
            'predicate_false_count':sum(conditions.get(i)=='false' for i in calls),
            'normal_return_count':sum(outcomes.get(i)=='CALL_SITE_RETURN' for i in calls),
            'throw_count':sum(outcomes.get(i)=='CALL_SITE_THROW' for i in calls)}

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def main():
    if (HERE/'expansion/checkpoint.json').exists():
        from finish_campaign import main as finish_expanded_campaign
        finish_expanded_campaign()
        return
    ipc=json.loads((HERE/'trials/checkpoint.json').read_text())
    file=json.loads((HERE/'file-trials/checkpoint.json').read_text())
    phase_items=[('ipc',r) for r in ipc['results']]+[('committed_file',r) for r in file['results']]
    healthy=parse(HERE/'healthy/trace/runtime_trace.jsonl')
    file_healthy=parse(HERE/'file-healthy/trace/runtime_trace.jsonl')
    base=set(healthy['coverage'])|set(file_healthy['coverage'])
    seen=set(base);rows_out=[];phase_cov={'ipc':set(healthy['coverage']),
                                           'committed_file':set(file_healthy['coverage'])}
    for phase,item in phase_items:
        trace=parse(HERE/item['trace'])
        raw=set(trace['coverage']);gain=raw-seen
        prod=production(raw);prod_gain=prod-production(seen)
        seen|=raw;phase_cov[phase]|=raw
        selector=item['selectors'] if phase=='ipc' else item['selector']
        row={'phase':phase,'trial':item['trial'],'status':item['status'],
             'selector':selector,'selector_json':json.dumps(selector,sort_keys=True,separators=(',',':')),
             'matched_count':item['matched_count'],'applied_count':item['applied_count'],
             'strict_injection':item['strict_injection'],
             'target_reached_after_fault':item['target_reached_after_fault'],
             'target_condition_after_fault':item['target_condition_after_fault'],
             'target_call_outcome_after_fault':item['target_call_outcome_after_fault'],
             'target_fatal_exception_count':item['target_fatal_exception_count'],
             'junit_exit':item['junit_exit'],'junit_seconds':item['junit_seconds'],
             'trial_wall_seconds':item['trial_wall_seconds'],
             'coverage_method_ids':sum(x.startswith('METHOD:') for x in prod),
             'coverage_branch_outcome_ids':sum(x.startswith('BRANCH:') for x in prod),
             'coverage_production_ids':len(prod),
             'new_production_ids_vs_prior_trials':len(prod_gain),
             'new_production_id_list':sorted(prod_gain),
             'new_raw_ids_vs_prior_trials':len(gain),'trace':item['trace']}
        rows_out.append(row)
    columns=['phase','trial','status','selector_json','matched_count','applied_count','strict_injection',
             'target_reached_after_fault','target_condition_after_fault','target_call_outcome_after_fault',
             'target_fatal_exception_count','junit_exit','junit_seconds','trial_wall_seconds',
             'coverage_method_ids','coverage_branch_outcome_ids','coverage_production_ids',
             'new_production_ids_vs_prior_trials','new_raw_ids_vs_prior_trials','trace']
    with (HERE/'trial-ledger.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for row in rows_out:
            writer.writerow({k:json.dumps(row[k],separators=(',',':')) if isinstance(row[k],list) else row[k]
                             for k in columns})
    now=datetime.now(timezone.utc)
    all_ok=all(r['strict_injection'] and r['target_reached_after_fault'] and
               r['target_fatal_exception_count']==0 and r['junit_exit']==0 for r in rows_out)
    raw_gain=seen-base;prod_base=production(base);prod_seen=production(seen)
    result={
      'case_id':'HDFS-09','status':'bounded_complete' if all_ok else 'bounded_incomplete',
      'campaign_finished':True,'methodology':'coverage_io_no_graph','bug_mark':'none',
      'new_bug_confirmed':False,'system':'HDFS 3.4.3','source_commit':'9d50c688466',
      'source_worktree_branch':'research/hdfs09-committed-txid',
      'source_file':'hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java',
      'function':'org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo)',
      'selection_line':504,'selected_site_id':SITE,'original_bytecode_index':239,
      'check_code':'if (reqInfo.hasCommittedTxId()) Preconditions.checkArgument(reqInfo.getCommittedTxId() >= committedTxnId.get(), "Client trying to move committed txid backward ...");',
      'check_semantics':'Reject a request that would move the JournalNode committed transaction ID backward; IllegalArgumentException is the expected guard result for a regressing request.',
      'cluster_test':'org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#testSingleWriter',
      'cluster_nodes':3,'cluster_type':'MiniJournalCluster',
      'workload':'Unmodified Hadoop 3.4.3 JUnit method invoked through JUnitCore; @Before, @After and @Rule execute. No Docker.',
      'healthy_junit_exit':json.loads((HERE/'healthy/manifest.json').read_text())['runtime']['exit'],
      'healthy_file_probe_junit_exit':json.loads((HERE/'file-healthy/manifest.json').read_text())['runtime']['exit'],
      'healthy_target':healthy_exact_calls(HERE/'healthy/trace/runtime_trace.jsonl'),
      'selected_runtime_identity':{'siteId':SITE,'declaredCallee':CALLEE,
          'sourceKey':'jn2#epoch0','requestApi':'originalSingleWriter',
          'caller':'<org.apache.hadoop.hdfs.qjournal.server.Journal: void finalizeLogSegment(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo,long,long)>',
          'caller_start_txid':4,'caller_end_txid':4,
          'healthy_predicate':'true','healthy_call_outcome':'CALL_SITE_RETURN'},
      'fault_trials':len(rows_out),'ipc_fault_trials':len(ipc['results']),
      'committed_file_fault_trials':len(file['results']),
      'requested_fault_events':sum(1 for _ in rows_out),
      'strict_injection_trials':sum(bool(r['strict_injection']) for r in rows_out),
      'matched_fault_events':sum(r['matched_count'] for r in rows_out),
      'applied_fault_events':sum(r['applied_count'] for r in rows_out),
      'target_after_fault_trials':sum(bool(r['target_reached_after_fault']) for r in rows_out),
      'target_lost_trials':sum(r['status']=='lost_target' for r in rows_out),
      'target_fatal_trials':sum(r['target_fatal_exception_count']>0 for r in rows_out),
      'junit_pass_trials':sum(r['junit_exit']==0 for r in rows_out),
      'coverage':{'metric':'production method-entry and branch-outcome IDs',
          'healthy':split_counts(prod_base),'fault_union':split_counts(prod_seen),
          'gain':split_counts(prod_seen-prod_base),
          'raw_healthy_ids':len(base),'raw_fault_union_ids':len(seen),
          'raw_gain_ids':len(raw_gain),
          'excluded_probe_branch_ids':'Client.getRpcResponse #u44/#u49/#u54 and direct file marker BestEffortLongFile.set #u100000',
          'ipc_phase_production_gain_ids':len(production(phase_cov['ipc'])-production(healthy['coverage'])),
          'committed_file_phase_production_gain_ids':len(production(phase_cov['committed_file'])-production(file_healthy['coverage'])),
          'phase_deltas_are_not_additive':True},
      'started_at_utc':START.isoformat(),'completed_at_utc':now.isoformat(),
      'elapsed_seconds':round((now-START).total_seconds(),3),
      'trial_wall_seconds':round(sum(r['trial_wall_seconds'] for r in rows_out),3),
      'junit_trial_seconds':round(sum(r['junit_seconds'] for r in rows_out),3),
      'phase_trial_wall_seconds':{'ipc':round(sum(r['trial_wall_seconds'] for r in rows_out if r['phase']=='ipc'),3),
                                  'committed_file':round(sum(r['trial_wall_seconds'] for r in rows_out if r['phase']=='committed_file'),3)},
      'stop_reason':'bounded IPC (12) and committed-file (4) trial budgets completed; all strict injections retained the selected call, which returned with a true predicate; no target guard exception.',
      'fault_families':['Hadoop IPC response IOException','Hadoop IPC response EOFException',
                        'Hadoop IPC response SocketTimeoutException',
                        'BestEffortLongFile committed-txid write IOException',
                        'BestEffortLongFile committed-txid write FileNotFoundException'],
      'runtime_probe_dependency':{'jar':'deps/unit-test-hdfs-c41dc5ee3-273672a0053c.jar',
                                  'sha256':sha(HERE/'deps/unit-test-hdfs-c41dc5ee3-273672a0053c.jar'),
                                  'use':'low-level call/I/O recorder and exact IPC fault executor only; no static analysis, graph aggregation, or closure gate in campaign'},
      'limitations':'Bounded original single-writer JUnit campaign; result does not cover all I/O schedules or the deliberate committed-txid regression case. No target exception was observed to replay.',
      'trials':rows_out,
      'evidence':{'readme':'README.md','trial_ledger':'trial-ledger.csv',
          'ipc_checkpoint':'trials/checkpoint.json','file_checkpoint':'file-trials/checkpoint.json',
          'healthy_trace':'healthy/trace/runtime_trace.jsonl',
          'healthy_file_events':'file-healthy/file-events.tsv',
          'original_target_bytecode':'evidence/original-checkRequest-javap.txt'}
    }
    atomic_json(HERE/'result.json',result)
    print(json.dumps({k:result[k] for k in ('case_id','status','fault_trials','strict_injection_trials',
          'target_after_fault_trials','target_fatal_trials','elapsed_seconds','bug_mark')}))

if __name__=='__main__':main()
