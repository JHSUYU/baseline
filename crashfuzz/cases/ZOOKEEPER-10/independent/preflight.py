#!/usr/bin/env python3
"""Check the true parameterized JUnit invocation before fault instrumentation."""

import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET


ROOT = Path('/users/ZhenyuLi/zk10-independent')
SOURCE = ROOT / 'source'
REPORT = SOURCE / 'zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml'
OLD = '/users/ZhenyuLi/baseline/crashfuzz/cases/ZOOKEEPER-05/source'
RUN = ROOT / 'preflight'


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / 'temp').mkdir(exist_ok=True)
    xml = ET.parse(REPORT).getroot()
    cp = next(p.get('value') for p in xml.findall('./properties/property')
              if p.get('name') == 'java.class.path')
    cp = os.pathsep.join((cp.replace(OLD, str(SOURCE)),
                          str(ROOT / 'tools/runner/zk10-runner.jar')))
    if 'graphchecker' in cp.lower() or 'skeleton' in cp.lower():
        raise RuntimeError('legacy instrumentor in classpath')
    command = ['/usr/lib/jvm/java-8-openjdk-amd64/bin/java', '-ea', '-Xmx1g',
               '-Djava.awt.headless=true',
               '-Djava.io.tmpdir=' + str(RUN / 'temp'),
               '-Dbuild.test.dir=' + str(RUN / 'test-data'),
               '-Dtest.junit.threads=24', '-Dzookeeper.junit.threadid=25',
               '-cp', cp, 'zk10.OriginalJUnitRunner']
    started = time.monotonic()
    with (RUN / 'junit.log').open('w') as out:
        result = subprocess.run(command, cwd=SOURCE / 'zookeeper-server',
                                stdout=out, stderr=subprocess.STDOUT, timeout=300)
    elapsed = round(time.monotonic() - started, 3)
    (RUN / 'result.txt').write_text('exit={} elapsed={}\n'.format(result.returncode, elapsed))
    print((RUN / 'result.txt').read_text().strip(), flush=True)


if __name__ == '__main__':
    main()
