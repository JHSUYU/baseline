#!/usr/bin/env python3
"""Build this case's ASM recorder and plain JUnit launcher from local source."""

from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
REPORT = Path('/tmp/zk387-unit-smoke-20261006/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml')
JAVA_BIN = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar')


def main():
    agent = BASE / 'agent'
    runner = BASE / 'runner'
    (agent / 'classes').mkdir(parents=True, exist_ok=True)
    (runner / 'classes').mkdir(parents=True, exist_ok=True)
    subprocess.run([str(JAVA_BIN / 'javac'), '-cp', str(ASM), '-d', str(agent / 'classes'),
                    str(agent / 'src/independent/CoverageAgent.java'),
                    str(agent / 'src/independent/Probe.java')], check=True)
    manifest = agent / 'manifest.mf'
    manifest.write_text('Premain-Class: independent.CoverageAgent\nClass-Path: ' + str(ASM) + '\n')
    subprocess.run([str(JAVA_BIN / 'jar'), 'cfm', str(agent / 'independent-agent.jar'),
                    str(manifest), '-C', str(agent / 'classes'), '.'], check=True)
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    cp = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    assert 'graphchecker' not in cp.lower() and 'skeleton' not in cp.lower()
    subprocess.run([str(JAVA_BIN / 'javac'), '-cp', cp, '-d', str(runner / 'classes'),
                    str(runner / 'src/independent/OriginalJUnitRunner.java')], check=True)
    subprocess.run([str(JAVA_BIN / 'jar'), 'cf', str(runner / 'independent-runner.jar'),
                    '-C', str(runner / 'classes'), '.'], check=True)


if __name__ == '__main__':
    main()
