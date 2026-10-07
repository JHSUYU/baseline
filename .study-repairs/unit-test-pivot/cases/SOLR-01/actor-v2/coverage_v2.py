#!/usr/bin/env python3
"""Summarize original Solr production coverage from actor V2 effective trials."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from build_v2 import asm_jars, classpath


HERE = Path(__file__).resolve().parent
STATE = HERE / 'campaign/state.json'
OUTPUT = HERE / 'campaign/coverage-summary.json'
JAVA = '/usr/lib/jvm/java-8-openjdk-amd64/bin/java'
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm')
VERSION = '9.10.1'
DIST = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist')
CLASSPATH = ':'.join(map(str, (
    HERE / 'classes', HERE.parent / 'independent/lib/jacoco-core.jar',
    ASM / 'asm' / VERSION / f'asm-{VERSION}.jar',
    ASM / 'asm-tree' / VERSION / f'asm-tree-{VERSION}.jar',
    ASM / 'asm-commons' / VERSION / f'asm-commons-{VERSION}.jar',
)))


def prepare_overrides() -> dict[str, str]:
    receipt = json.loads((HERE / 'build-receipt.json').read_text())
    source = HERE / 'src/research/solraliasv2/Agent.java'
    if hashlib.sha256(source.read_bytes()).hexdigest() != receipt['agent_sources_sha256']['Agent.java']:
        raise RuntimeError('agent source changed since healthy calibration')
    agent_jar = HERE / 'solr01-actor-v2-agent.jar'
    if hashlib.sha256(agent_jar.read_bytes()).hexdigest() != receipt['agent_sha256']:
        raise RuntimeError('agent JAR changed since healthy calibration')
    compiled_agent = HERE / 'agent-classes/research/solraliasv2/Agent.class'
    with zipfile.ZipFile(agent_jar) as jar:
        if compiled_agent.read_bytes() != jar.read('research/solraliasv2/Agent.class'):
            raise RuntimeError('offline transformer differs from frozen agent JAR')
    helper = HERE / 'src/research/solraliasv2/CoverageBytecode.java'
    helper_classes = HERE / 'coverage-helper-classes'
    helper_classes.mkdir(exist_ok=True)
    agent_cp = ':'.join([str(HERE / 'agent-classes'), *map(str, asm_jars())])
    subprocess.run([str(Path(JAVA).with_name('javac')), '-source', '8', '-target', '8',
                    '-cp', agent_cp, '-d', str(helper_classes), str(helper)], check=True)
    overrides = HERE / 'coverage-classes'
    original_cloud = overrides / 'org/apache/solr/client/solrj/impl/BaseCloudSolrClient.class'
    original_cloud.unlink(missing_ok=True)
    subprocess.run([JAVA, '-cp', ':'.join((str(helper_classes), agent_cp, classpath())),
                    'research.solraliasv2.CoverageBytecode', str(DIST), str(overrides)],
                   check=True, capture_output=True, text=True)
    files = (overrides / 'org/apache/solr/client/solrj/impl/BaseHttpClusterStateProvider.class',
             overrides / 'org/apache/solr/client/solrj/embedded/JettySolrRunner.class')
    return {str(path.relative_to(overrides)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}


def summarize(files: list[Path]) -> dict:
    for path in files:
        if not path.is_file() or not path.stat().st_size:
            raise FileNotFoundError(path)
    command = [JAVA, '-cp', CLASSPATH, 'baseline.solr01.CoverageSummary',
               str(DIST), str(HERE / 'coverage-classes'), *map(str, files)]
    return json.loads(subprocess.check_output(command, text=True))


def main() -> None:
    state = json.loads(STATE.read_text())
    if not state.get('stopped'):
        raise RuntimeError('production summary requires a completed V2 campaign')
    bytecode_hashes = prepare_overrides()
    healthy = [HERE / f'healthy-{number:02d}/jacoco.exec' for number in (7, 8)]
    eligible = [HERE / 'campaign' / f"trial-{trial['number']:03d}" / 'jacoco.exec'
                for trial in state['trials'] if trial['effective']]
    baseline = summarize(healthy)
    combined = summarize(healthy + eligible)
    report = {
        'case_id': 'SOLR-01', 'identity_version': 'actor-v2',
        'attempts': len(state['trials']), 'effective_trials': len(eligible),
        'healthy': baseline, 'healthy_plus_effective': combined,
        'analysis_bytecode_sha256': bytecode_hashes,
        'new_covered_methods': combined['covered_methods'] - baseline['covered_methods'],
        'new_covered_branches': combined['covered_branches'] - baseline['covered_branches'],
        'target_guard_taken': any(trial['effective'] and trial['target_exception']
                                  for trial in state['trials']),
    }
    if baseline['unmatched_classes'] or combined['unmatched_classes']:
        raise RuntimeError('JaCoCo production class ID does not match analysis bytecode')
    temporary = OUTPUT.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    temporary.replace(OUTPUT)
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ('healthy', 'healthy_plus_effective')}, sort_keys=True))


if __name__ == '__main__':
    main()
