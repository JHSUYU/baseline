#!/usr/bin/env python3
"""Run unchanged Hadoop 3.4.3 JUnit with prebuilt call/I/O runtime probes.

This runner performs no static analysis, graph aggregation, or closure checks.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
HADOOP = Path.home() / ".baseline-deps/hadoop-3.4.3"
GRAPH = HERE / "deps/unit-test-hdfs-c41dc5ee3-273672a0053c.jar"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
TARGET = "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager"


def classpath() -> str:
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"], env=env, text=True).strip()
    tools = os.pathsep.join(str(x) for x in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))
    extra = [HERE / "deps/mockito-core-4.9.0.jar", HERE / "deps/byte-buddy-1.12.16.jar",
             HERE / "deps/byte-buddy-agent-1.12.16.jar", HERE / "deps/objenesis-3.3.jar"]
    for item in extra:
        if not item.is_file(): raise FileNotFoundError(item)
    return os.pathsep.join((str(HERE / "hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources"),
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        *(str(x) for x in extra), base, tools))


def logged(command: list[str], output: Path, timeout: int, *, cwd: Path | None = None,
           env: dict[str,str] | None = None) -> dict:
    started=time.monotonic(); output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('w') as stream:
        try:
            result=subprocess.run(command,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout,check=False)
            code=result.returncode
        except subprocess.TimeoutExpired: code=124
    return {'exit':code,'elapsed_seconds':round(time.monotonic()-started,3),'log':str(output)}


def run(name: str, trial: Path | None, method: str) -> dict:
    out=HERE/name; scratch=out/'scratch'; trace=out/'trace'
    for directory in (scratch,trace):
        if directory.exists(): shutil.rmtree(directory)
    for directory in (scratch/'data',scratch/'tmp',trace): directory.mkdir(parents=True,exist_ok=True)
    cp=classpath(); test_classes=HERE/'test-classes';test_classes.mkdir(exist_ok=True)
    class_file=test_classes/'OriginalHdfs10Test.class'
    if class_file.exists() and class_file.stat().st_mtime >= (HERE/'OriginalHdfs10Test.java').stat().st_mtime:
        (out/'compile.log').write_text('Reused unchanged case-local JUnit wrapper class.\n')
        compile_result={'exit':0,'elapsed_seconds':0.0,'log':str(out/'compile.log'),'cached':True}
    else:
        compile_result=logged([str(JDK/'javac'),'-cp',str(GRAPH)+os.pathsep+cp,'-d',str(test_classes),str(HERE/'OriginalHdfs10Test.java')],out/'compile.log',60)
    if compile_result['exit']!=0: raise RuntimeError('JUnit wrapper compile failed')
    command=[str(JDK/'java'),'-ea','-Xmx3g','-Djava.awt.headless=true','-Djava.net.preferIPv4Stack=true',
        '-Dorg.slf4j.simpleLogger.defaultLogLevel=warn',
        '-Dtest.build.data='+str(scratch/'data'),'-Djava.io.tmpdir='+str(scratch/'tmp'),
        '-Dcausynth.trace.mode=discovery','-Dcausynth.trace.start.paused=true',
        '-Dcausynth.trace.test='+TARGET+'#'+method,'-Dhdfs10.test.method='+method,
        '-Dcausynth.junit.record.test.body=true']
    if trial: command.append('-Dcausynth.fault.trial='+str(trial.resolve()))
    command.extend(['-cp',os.pathsep.join((str(test_classes),str(HERE/'control-overlay'),
        str(HERE/'instrumented-control-door'),str(GRAPH),cp)),
        'edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner','OriginalHdfs10Test','originalSingleWriter'])
    env=dict(os.environ,JAVA_HOME=str(JDK.parent),CAUSYNTH_TRACE_OUTPUT_DIR=str(trace))
    runtime=logged(command,out/'runtime.log',360,cwd=scratch,env=env)
    result={'test':TARGET+'#'+method,'trial':str(trial) if trial else None,
            'compile':compile_result,'runtime':runtime,'trace':str(trace/'runtime_trace.jsonl')}
    (out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--run-name',required=True);ap.add_argument('--trial',type=Path)
    ap.add_argument('--test-method',default='testSingleWriter');args=ap.parse_args()
    run(args.run_name,args.trial,args.test_method)
