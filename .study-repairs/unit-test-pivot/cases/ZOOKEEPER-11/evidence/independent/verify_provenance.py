#!/usr/bin/env python3
"""Verify all independent JVMs used original bytecode and case-local probes."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile
import xml.etree.ElementTree as ET

from run_native import (AGENT, ASM, BASE, BUILD, CLASSES, REPORT, ROOT, RUNNER,
                        SOURCE, TEST_CLASS, TEST_METHOD)

CHECKPOINT = BASE / 'checkpoint.json'
OUTPUT = BASE / 'provenance.json'
FORBIDDEN = (b'graphchecker', b'skeleton', b'causynth')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    state = json.loads(CHECKPOINT.read_text())
    assert state['finished'] and len(state['trials']) >= 80
    commit = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    assert commit == '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae'
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    original_cp = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    cp = os.pathsep.join([ASM, original_cp.replace(str(BUILD), str(SOURCE)), str(RUNNER)])
    assert not any(x.decode() in cp.lower() for x in FORBIDDEN)
    cp_sha = sha256(cp.encode())
    artifacts = {}
    for label, path in [('agent', AGENT), ('runner', RUNNER)]:
        with zipfile.ZipFile(path) as jar:
            names = jar.namelist()
            assert not any(any(token in jar.read(name).lower() for token in FORBIDDEN)
                           for name in names)
        artifacts[label] = {'path': str(path), 'sha256': sha256(path.read_bytes()),
                            'jar_entries_checked': len(names)}
    class_files = {}
    for class_name in CLASSES.split(','):
        relative = Path('zookeeper-server/target/classes') / (class_name + '.class')
        from_original_build = (BUILD / relative).read_bytes()
        from_case_source = (SOURCE / relative).read_bytes()
        assert from_original_build == from_case_source
        assert not any(token in from_case_source.lower() for token in FORBIDDEN)
        class_files[class_name] = sha256(from_case_source)
    for name in ('org/apache/zookeeper/server/quorum/CurrentEpochWriteFailureTest',):
        relative = Path('zookeeper-server/target/test-classes') / (name + '.class')
        assert (BUILD / relative).read_bytes() == (SOURCE / relative).read_bytes()
    for item in state['trials']:
        meta = json.loads((ROOT / item['run_id'] / 'run.json').read_text())
        assert meta['test_class'] == TEST_CLASS and meta['method'] == TEST_METHOD
        assert meta['plan'] == item['plan']
        assert meta['source_worktree'] == str(SOURCE)
        assert meta['original_source_commit'] == commit
        assert meta['classpath_sha256'] == cp_sha
        assert meta['agent_sha256'] == artifacts['agent']['sha256']
        assert meta['runner_sha256'] == artifacts['runner']['sha256']
        assert meta['classpath_has_graphchecker'] is False
        assert meta['classpath_has_skeleton'] is False
        assert (ROOT / item['run_id'] / 'events.tsv').exists()
        assert (ROOT / item['run_id'] / 'coverage.tsv').exists()
    sources = [*AGENT.parent.joinpath('src').rglob('*.java'),
               *RUNNER.parent.joinpath('src').rglob('*.java')]
    assert not any(any(token in path.read_bytes().lower() for token in FORBIDDEN)
                   for path in sources)
    data = {
        'case_id': 'ZOOKEEPER-11',
        'original_test': TEST_CLASS + '#' + TEST_METHOD,
        'original_source_commit': commit,
        'original_test_classes_byte_identical_to_unwoven_build': True,
        'selected_production_classes_byte_identical_to_unwoven_build': True,
        'selected_production_class_sha256': class_files,
        'case_local_artifacts': artifacts,
        'independent_classpath_sha256': cp_sha,
        'independent_classpath_entries': len(cp.split(os.pathsep)),
        'forbidden_legacy_component_in_classpath_or_artifact_or_selected_class': False,
        'trial_jvms_verified': len(state['trials']),
        'target_identity': 'QuorumPeer.loadDataBase currentEpoch.tmp exists guard line 1169; IOException ATHROW bytecode mapped to line 1175',
        'fault_identity': 'direct SocketChannel read/write, QuorumPeer epoch FileReader, AtomicFileWritingIdiom and AtomicFileOutputStream I/O site plus global ordinal',
        'runtime_feedback_inputs': ['case-local Probe events.tsv', 'case-local Probe coverage.tsv'],
        'legacy_graph_or_skeleton_artifacts_read_for_selection_or_execution': False,
        'historical_trials_excluded': 5,
    }
    temp = OUTPUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    os.replace(temp, OUTPUT)
    print(json.dumps(data, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
