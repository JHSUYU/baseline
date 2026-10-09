#!/usr/bin/env python3
"""Exec the unchanged ZK11 cluster JUnit in one Mallory core trial JVM."""

import hashlib
import os
from pathlib import Path
import xml.etree.ElementTree as ET

BASELINE = Path(__file__).resolve().parents[4]
SOURCE = Path(os.environ.get('MALLORY_ZK11_SOURCE', '/users/ZhenyuLi/zk11-independent-unit'))
REPORT = Path(os.environ.get('MALLORY_ZK11_REPORT',
    '/tmp/zk387-unit-smoke-20261006/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml'))
RUNNER = BASELINE / 'crashfuzz/vendor/0e00f21aa9596261-independent-runner.jar'
TEST = 'org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest'
METHOD = 'testReadCurrentEpochFromAcceptedEpochTmpFile'
PEER_CLASS_SHA = 'cdcb7a67d5905fef27a8e36824b5d504c8df2c907dfac1a3cb8af6e3abbb6052'
TEST_CLASS_SHA = '05cb4b39fee9ae7c48313d9d0cef08ce6e1b929f57ba480cf98cbe2af7fa8f85'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    peer = SOURCE / 'zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/QuorumPeer.class'
    test = SOURCE / 'zookeeper-server/target/test-classes/org/apache/zookeeper/server/quorum/CurrentEpochWriteFailureTest.class'
    if digest(peer) != PEER_CLASS_SHA or digest(test) != TEST_CLASS_SHA:
        raise RuntimeError('ZooKeeper compiled workload classes changed since healthy calibration')
    if not RUNNER.is_file():
        raise FileNotFoundError(RUNNER)
    properties = ET.parse(REPORT).getroot().findall('./properties/property')
    raw = next(p.get('value') for p in properties if p.get('name') == 'java.class.path')
    cp = raw.replace('/tmp/zk387-unit-smoke-20261006', str(SOURCE))
    missing = [entry for entry in cp.split(os.pathsep) if not Path(entry).exists()]
    if missing:
        raise RuntimeError('JUnit classpath has missing entries: ' + repr(missing[:4]))
    trial = Path(os.environ['MALLORY_EVENT_FILE']).resolve().parent
    (trial / 'temp').mkdir(exist_ok=True)
    (trial / 'test-data').mkdir(exist_ok=True)
    slot = int(os.environ.get('MALLORY_ZK11_SLOT', '15'))
    argv = [
        '/usr/lib/jvm/java-8-openjdk-amd64/bin/java', '-Xverify:all', '-ea', '-Xmx1g',
        '-Djava.awt.headless=true', '-Dsun.reflect.noInflation=true',
        '-Djava.io.tmpdir=' + str(trial / 'temp'),
        '-Dbuild.test.dir=' + str(trial / 'test-data'),
        '-Dtest.junit.threads=16', '-Dzookeeper.junit.threadid=' + str(slot),
        '-cp', str(RUNNER) + os.pathsep + cp,
        'independent.OriginalJUnitRunner', TEST, METHOD,
    ]
    os.execvpe(argv[0], argv, os.environ)


if __name__ == '__main__':
    main()
