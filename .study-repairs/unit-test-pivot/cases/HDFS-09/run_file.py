#!/usr/bin/env python3
"""Run original JUnit with direct committed-txid write probe (no graph operations)."""
from __future__ import annotations
import argparse,json,os,shutil
from pathlib import Path
from run_original import HERE,HADOOP,GRAPH,JDK,TARGET,classpath,logged

def run(name,node=None,ordinal=None,exception='IOException',ipc_trial=None,file_plan=None):
    out=HERE/name;scratch=out/'scratch';trace=out/'trace'
    for directory in (scratch,trace):
        if directory.exists():shutil.rmtree(directory)
    for directory in (scratch/'data',scratch/'tmp',trace):directory.mkdir(parents=True,exist_ok=True)
    cp=classpath();test_classes=HERE/'test-classes';test_classes.mkdir(exist_ok=True)
    compile_result=logged([str(JDK/'javac'),'-cp',str(GRAPH)+os.pathsep+cp,'-d',str(test_classes),str(HERE/'OriginalHdfs09Test.java')],out/'compile.log',60)
    if compile_result['exit']!=0:raise RuntimeError('JUnit wrapper compile failed')
    command=[str(JDK/'java'),'-ea','-Xmx3g','-Djava.awt.headless=true','-Djava.net.preferIPv4Stack=true',
        '-Dorg.slf4j.simpleLogger.defaultLogLevel=warn',
        '-Dtest.build.data='+str(scratch/'data'),'-Djava.io.tmpdir='+str(scratch/'tmp'),
        '-Dcausynth.trace.mode=discovery','-Dcausynth.trace.start.paused=true',
        '-Dcausynth.trace.test='+TARGET+'#testSingleWriter','-Dhdfs09.test.method=testSingleWriter',
        '-Dcausynth.junit.record.test.body=true',
        '-Dhdfs09.file.events='+str(out/'file-events.tsv')]
    if ipc_trial is not None:
        command.append('-Dcausynth.fault.trial='+str(Path(ipc_trial).resolve()))
    if file_plan:
        command.append('-Dhdfs09.file.plan='+file_plan)
    if node is not None:
        command.extend(['-Dhdfs09.file.node='+str(node),'-Dhdfs09.file.ordinal='+str(ordinal),
                        '-Dhdfs09.file.exception='+exception])
    command.extend(['-cp',os.pathsep.join((str(test_classes),str(HERE/'file-overlay'),
        str(HERE/'control-overlay'),str(HERE/'instrumented-control-door'),str(GRAPH),cp)),
        'edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner','OriginalHdfs09Test','originalSingleWriter'])
    env=dict(os.environ,JAVA_HOME=str(JDK.parent),CAUSYNTH_TRACE_OUTPUT_DIR=str(trace))
    runtime=logged(command,out/'runtime.log',360,cwd=scratch,env=env)
    result={'test':TARGET+'#testSingleWriter','file_fault':{'node':node,'ordinal':ordinal,'exception':exception} if node is not None else None,
            'file_plan':file_plan,'ipc_trial':str(ipc_trial) if ipc_trial else None,
            'compile':compile_result,'runtime':runtime,'trace':str(trace/'runtime_trace.jsonl'),
            'file_events':str(out/'file-events.tsv')}
    (out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-name',required=True)
    parser.add_argument('--node',type=int);parser.add_argument('--ordinal',type=int)
    parser.add_argument('--exception',choices=('IOException','FileNotFoundException'),default='IOException')
    parser.add_argument('--ipc-trial',type=Path);parser.add_argument('--file-plan')
    args=parser.parse_args();run(args.run_name,args.node,args.ordinal,args.exception,args.ipc_trial,args.file_plan)
