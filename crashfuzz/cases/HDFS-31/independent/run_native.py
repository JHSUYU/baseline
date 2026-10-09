#!/usr/bin/env python3
"""Original Hadoop 3.4.3 JUnit with case-local exact-target ASM overlay."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build'
OVERLAY = BUILD / 'overlay'
HADOOP = Path('/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3')
SOURCE = Path('/users/ZhenyuLi/hdfs31-independent-source')
RUN_ROOT = Path('/users/ZhenyuLi/hdfs31-independent-runs')
JDK = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar')
ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.6/asm-tree-9.6.jar')
ASM_COMMONS = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-commons/9.6/asm-commons-9.6.jar')
JACOCO = Path('/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar')
JACOCO_CORE = Path('/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar')
HDFS = HADOOP / 'share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar'
CLIENT = HADOOP / 'share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar'
COMMON = HADOOP / 'share/hadoop/common/hadoop-common-3.4.3.jar'
TESTS = HADOOP / 'share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar'
CLASS = 'org.apache.hadoop.hdfs.server.datanode.TestDiskError'
METHOD = 'testDataTransferWhenBytesPerChecksumIsZero'
PATCHED = ('org/apache/hadoop/hdfs/server/datanode/DataNode',
           'org/apache/hadoop/hdfs/server/datanode/BlockPoolManager',
           'org/apache/hadoop/ipc/Client')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def filter_production_probes(path):
    """Exclude original JUnit/test-helper classes from JaCoCo probe feedback."""
    production = set()
    for jar_path in (HDFS, CLIENT, COMMON):
        with zipfile.ZipFile(jar_path) as jar:
            production.update(name[:-6] for name in jar.namelist() if name.endswith('.class'))
    lines = path.read_text().splitlines()
    retained = [line for line in lines if line.split('#', 1)[0] in production]
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text('\n'.join(retained) + ('\n' if retained else ''))
    os.replace(temp, path)
    return len(retained)


def build():
    source_files = sorted((HERE / 'src').glob('*.java'))
    marker = BUILD / 'built.json'
    if marker.exists() and marker.stat().st_mtime > max(p.stat().st_mtime for p in source_files):
        return
    classes = BUILD / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    junit = HADOOP / 'share/hadoop/tools/lib/junit-4.13.2.jar'
    cp = os.pathsep.join(map(str, (ASM, JACOCO_CORE, TESTS, HDFS, CLIENT, COMMON, junit)))
    subprocess.run([str(JDK / 'javac'), '-cp', cp, '-d', str(classes),
                    *(str(x) for x in source_files)], check=True)
    OVERLAY.mkdir(parents=True, exist_ok=True)
    shutil.copy2(classes / 'Hdfs31Probe.class', OVERLAY / 'Hdfs31Probe.class')
    original_hashes = {}
    for name in PATCHED:
        original = BUILD / 'input' / (name + '.class')
        original.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(COMMON if name == 'org/apache/hadoop/ipc/Client' else HDFS) as jar:
            original.write_bytes(jar.read(name + '.class'))
        original_hashes[name] = sha(original)
        subprocess.run([str(JDK / 'java'), '-cp', os.pathsep.join((str(classes), cp)),
                        'PatchHdfs31', str(original), name, str(OVERLAY)], check=True)
    marker.write_text(json.dumps({'original_class_sha256': original_hashes,
                                   'source_commit': '9d50c6884666e794e45102260a4017bb31802e1b'}, indent=2) + '\n')


def run(run_id='healthy-01', plan=(), timeout=360):
    build()
    out = RUN_ROOT / run_id
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / 'scratch'
    shutil.rmtree(scratch, ignore_errors=True)
    for suffix in ('data', 'tmp', 'logs'):
        (scratch / suffix).mkdir(parents=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / 'bin/hadoop'), 'classpath', '--glob'],
                                         env=env, text=True).strip()
    m2 = Path('/users/ZhenyuLi/.m2/repository')
    extra = [m2 / 'org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar',
             m2 / 'net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar',
             m2 / 'net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar',
             m2 / 'org/objenesis/objenesis/3.3/objenesis-3.3.jar']
    cp = os.pathsep.join((str(OVERLAY), str(BUILD / 'classes'),
                          str(SOURCE / 'hadoop-hdfs-project/hadoop-hdfs/src/test/resources'),
                          str(TESTS), str(HADOOP / 'share/hadoop/common/hadoop-common-3.4.3-tests.jar'),
                          hadoop_cp, *(str(x) for x in extra),
                          *(str(x) for x in sorted((HADOOP / 'share/hadoop/tools/lib').glob('*.jar')))))
    assert not any(x in cp.lower() for x in ('graphchecker', 'skeleton', 'causynth'))
    cmd = [str(JDK / 'java'), '-ea', '-Xmx3g', '-Djava.awt.headless=true',
           '-Djava.net.preferIPv4Stack=true',
           '-Dtest.build.data=' + str(scratch / 'data'),
           '-Djava.io.tmpdir=' + str(scratch / 'tmp'),
           '-Dhadoop.log.dir=' + str(scratch / 'logs'),
           '-Dhdfs31.trace=' + str(out / 'events.tsv'),
           '-Dhdfs31.plan=' + '|||'.join(plan),
           '-javaagent:' + str(JACOCO) + '=destfile=' + str(out / 'jacoco.exec')
           + ',includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false',
           '-cp', cp, 'RunJUnitMethod', CLASS, METHOD]
    start = time.monotonic()
    with (out / 'junit.log').open('w') as log:
        try:
            code = subprocess.run(cmd, cwd=scratch, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    manifest = {'case_id': 'HDFS-31', 'run_id': run_id, 'junit_exit': code,
                'elapsed_seconds': round(time.monotonic() - start, 3),
                'test': CLASS + '#' + METHOD, 'original_source_commit': '9d50c6884666e794e45102260a4017bb31802e1b',
                'original_test_jar_sha256': sha(TESTS), 'original_hdfs_jar_sha256': sha(HDFS), 'original_common_jar_sha256': sha(COMMON),
                'overlay_DataNode_sha256': sha(OVERLAY / (PATCHED[0] + '.class')),
                'overlay_BlockPoolManager_sha256': sha(OVERLAY / (PATCHED[1] + '.class')),
                'overlay_Client_sha256': sha(OVERLAY / (PATCHED[2] + '.class')),
                'classpath_sha256': hashlib.sha256(cp.encode()).hexdigest(),
                'classpath_has_graphchecker_or_skeleton': False, 'plan': list(plan)}
    if (out / 'jacoco.exec').exists() and (out / 'jacoco.exec').stat().st_size:
        with (out / 'covered_probes.txt').open('w') as stream:
            subprocess.run([str(JDK / 'java'), '-cp', os.pathsep.join((str(BUILD / 'classes'),
                            str(JACOCO_CORE), str(ASM), str(ASM_TREE), str(ASM_COMMONS))), 'CoverageHdfs31',
                            str(out / 'jacoco.exec'), str(OVERLAY), str(HDFS),
                            str(CLIENT), str(COMMON)], stdout=stream, check=True)
        manifest['covered_probes'] = filter_production_probes(out / 'covered_probes.txt')
        manifest['production_probe_filter'] = 'exact_class_membership_in_original_hdfs_client_common_jars'
    temp = out / 'run.json.tmp'
    temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    os.replace(temp, out / 'run.json')
    print(json.dumps(manifest))
    return manifest


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'healthy-01')
