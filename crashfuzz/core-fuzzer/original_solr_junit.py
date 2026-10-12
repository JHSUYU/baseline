#!/usr/bin/env python3
"""Compile and run one unchanged Solr 8.11.4 cluster JUnit method."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4')
DIST = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4')


def classpath(classes: Path) -> str:
    dist = DIST / 'dist'
    paths = [classes, SOURCE / 'solr/core/src/test-files',
             dist / 'solr-test-framework-8.11.4.jar',
             dist / 'solr-core-8.11.4.jar', dist / 'solr-solrj-8.11.4.jar',
             dist / 'solr-analysis-extras-8.11.4.jar',
             SOURCE / 'solr/solrj/src/test-files']
    groups = [dist / 'test-framework/lib', dist / 'test-framework/lucene-libs',
              DIST / 'server/solr-webapp/webapp/WEB-INF/lib', DIST / 'server/lib',
              DIST / 'server/lib/ext', DIST / 'contrib/analysis-extras/lib',
              DIST / 'contrib/analysis-extras/lucene-libs']
    for group in groups:
        paths.extend(sorted(group.glob('*.jar')))
    return os.pathsep.join(str(path) for path in paths if path.exists())


def dynamic_plugins() -> list[Path]:
    config = SOURCE / 'solr/core/src/test-files/solr/collection1/conf'
    root = SOURCE / 'solr/core/src/test'
    by_name: dict[str, list[Path]] = {}
    for candidate in root.rglob('*.java'):
        by_name.setdefault(candidate.stem, []).append(candidate)
    names = {'MockExchangeRateProvider', 'NvlValueSourceParser'}
    for config_file in config.glob('*.xml'):
        text = config_file.read_text(encoding='utf-8', errors='replace')
        for clazz in re.findall(r'class\s*=\s*[\'\"]([^\'\"]+)', text):
            if clazz.startswith(('solr.', 'org.apache.solr.')):
                names.add(clazz.split('$', 1)[0].rsplit('.', 1)[-1])
    return sorted({item for name in names for item in by_name.get(name, [])})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--test-class', required=True)
    parser.add_argument('--test-method', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--static-selection', type=Path, required=True)
    parser.add_argument('--fault-trial', type=Path)
    parser.add_argument('--classes-dir', type=Path)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    classes = args.classes_dir.resolve() if args.classes_dir else output / 'classes'
    classes.mkdir(exist_ok=True)
    scratch = output / 'scratch'
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir()
    relative_test = Path(*args.test_class.split('.')).with_suffix('.java')
    candidates = [SOURCE / part / relative_test for part in
                  ('solr/core/src/test', 'solr/solrj/src/test')]
    test_path = next((path for path in candidates if path.is_file()), None)
    if test_path is None:
        raise FileNotFoundError(f'original Solr JUnit source: {candidates}')
    agent = HERE.parent / 'runtime-agent/target/crashfuzz-runtime-agent-0.1.0.jar'
    if not agent.is_file():
        raise FileNotFoundError(agent)
    cp = classpath(classes)
    sourcepath = os.pathsep.join(str(SOURCE / part) for part in
                                 ('solr/core/src/test', 'solr/solrj/src/test'))
    runner = HERE / 'RunOriginalHdfsJUnit.java'
    test_class_file = classes / Path(*args.test_class.split('.')).with_suffix('.class')
    runner_class_file = classes / 'RunOriginalHdfsJUnit.class'
    if (not test_class_file.is_file() or not runner_class_file.is_file() or
            runner_class_file.stat().st_mtime_ns < runner.stat().st_mtime_ns):
        subprocess.run([str(JAVA / 'javac'), '-cp', cp, '-sourcepath', sourcepath,
                        '-d', str(classes), str(test_path), str(runner),
                        *(str(path) for path in dynamic_plugins())], check=True)
    nightly = bool(re.search(r'^\s*@Nightly\b',
                             test_path.read_text(errors='replace'), re.M))
    command = [str(JAVA / 'java'), '-ea', '-Xmx3g', '-Djava.awt.headless=true',
               '-Djava.io.tmpdir=' + str(scratch), '-DtempDir=' + str(scratch),
               '-Dtests.seed=F0993D5343E20BA4',
               '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
               '-Dcommon.dir=' + str(SOURCE / 'lucene'),
               '-Dtests.asserts=true', '-Dtests.slow=true',
               '-Dtests.nightly=' + str(nightly).lower(),
               '-Dtests.awaitsfix=true', '-Dtests.badapples=true',
               '-Dsolr.disableConfigSetsCreateAuthChecks=true',
               '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
               '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
               '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
               '-Djdk.map.althashing.threshold=0',
               '-Djava.security.egd=file:/dev/./urandom',
               '-javaagent:' + str(agent), '-cp', cp, 'RunOriginalHdfsJUnit',
               args.test_class, args.test_method]
    env = dict(os.environ, JAVA_HOME=str(JAVA.parent),
               CRASHFUZZ_STATIC_SELECTION=str(args.static_selection.resolve(strict=True)),
               CAUSYNTH_TRACE_OUTPUT_DIR=str(output))
    if args.fault_trial:
        env['CAUSYNTH_FAULT_TRIAL'] = str(args.fault_trial.resolve(strict=True))
    started = time.monotonic()
    with (output / 'junit.log').open('w') as log:
        try:
            code = subprocess.run(command, cwd=SOURCE, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    result = {'case_id': args.case_id,
              'cluster_test': args.test_class + '#' + args.test_method,
              'nightly_enabled': nightly,
              'returncode': code, 'elapsed_seconds': round(time.monotonic() - started, 3),
              'trace': str(output / 'runtime_trace.jsonl'),
              'junit_log': str(output / 'junit.log')}
    (output / 'manifest.json.tmp').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'manifest.json.tmp').replace(output / 'manifest.json')
    shutil.rmtree(scratch, ignore_errors=True)
    print(json.dumps(result), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
