#!/usr/bin/env python3
"""One guarded, checkpointed original-JUnit feasibility run per invocation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
FIRST = HERE.parent
sys.path.insert(0, str(FIRST))
from build import (JAVA, SOURCE, classpath, clean_classpath)  # noqa: E402
from audit import audit  # noqa: E402

ROOT = Path('/users/ZhenyuLi/solr18-alternate-junit-runs')
STATE = HERE / 'calibration-state.json'
LOCK = FIRST.parents[2] / 'jvm-start.lock'
TEST_CLASS = 'org.apache.solr.cloud.AliasIntegrationTest'
TEST_CLASS_REL = Path('org/apache/solr/cloud/AliasIntegrationTest.class')
ORIGINAL_CLASS_SHA = '7674e0e501483b11108f72129a2a68ff54ae5c6d35c4862d6546a132f439f402'
FIRST_STATE_SHA = '5df381a7965fffadb09b5b3b132e7ba0e4777150d3aadf46245bbc018a595113'
MIN_START = 10 * 1024**3 + 256 * 1024**2
MIN_CONTINUE = 10 * 1024**3
MAX_OTHER_JVMS = 4
SEED = 'D82A1912E3C1791F'
CANDIDATES = ('testDeleteAliasWithExistingCollectionName', 'testErrorChecks')
JACOCO = Path('/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def validate_frozen() -> dict:
    assert sha(FIRST / 'campaign-state.json') == FIRST_STATE_SHA
    clean_class = FIRST / 'clean-classes' / TEST_CLASS_REL
    patched_class = FIRST / 'classes' / TEST_CLASS_REL
    assert sha(clean_class) == sha(patched_class) == ORIGINAL_CLASS_SHA
    build = json.loads((FIRST / 'build.json').read_text())
    assert build['source_revision'] == 'e27f44e3d78dfcec230c97e0a1240e3751daeff9'
    assert sha(SOURCE / 'solr/core/src/test' / TEST_CLASS_REL.with_suffix('.java')) == build['source_sha256']['solr/core/src/test/org/apache/solr/cloud/AliasIntegrationTest.java']
    return {'first_campaign_state_sha256': FIRST_STATE_SHA,
            'original_junit_class_sha256': ORIGINAL_CLASS_SHA,
            'original_source_revision': build['source_revision'],
            'original_source_sha256': build['source_sha256']['solr/core/src/test/org/apache/solr/cloud/AliasIntegrationTest.java'],
            'alternate_probe_source_sha256': sha(HERE / 'Solr18Probe.java')}


def resource_gate() -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    stat = os.statvfs(ROOT)
    free = stat.f_bavail * stat.f_frsize
    output = subprocess.run(['jps', '-lm'], text=True, capture_output=True, check=True).stdout
    business = [line for line in output.splitlines() if 'sun.tools.jps.Jps' not in line]
    result = {'checked_at_utc': stamp(), 'free_bytes': free,
              'business_jvms': business, 'min_start_bytes': MIN_START,
              'min_continue_bytes': MIN_CONTINUE,
              'max_other_jvms': MAX_OTHER_JVMS}
    assert free >= MIN_START and len(business) <= MAX_OTHER_JVMS, result
    assert not any('research.solr18.OriginalJUnit' in line for line in business), result
    return result


def alternate_classpath() -> str:
    entries = classpath().split(':')
    assert entries[1] == str(FIRST / 'classes')
    entries.insert(1, str(HERE / 'classes'))
    return ':'.join(entries)


def compile_probe() -> str:
    target = HERE / 'classes/research/solr18/Solr18Probe.class'
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                        '-cp', classpath(), '-d', str(HERE / 'classes'),
                        str(HERE / 'Solr18Probe.java')], check=True,
                       capture_output=True, text=True)
    return sha(target)


def command(method: str, instrumented: bool, scratch: Path, run_dir: Path) -> list[str]:
    cmd = [str(JAVA / 'java'), '-ea', '-Xmx4g', '-Djava.awt.headless=true',
           '-Djava.io.tmpdir=' + str(scratch), '-DtempDir=' + str(scratch),
           '-Dtests.seed=' + SEED, '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
           '-Dcommon.dir=' + str(SOURCE / 'lucene'), '-Dtests.asserts=true',
           '-Dtests.slow=true', '-Dtests.nightly=true',
           '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
           '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
           '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
           '-Djdk.map.althashing.threshold=0',
           '-Djava.security.egd=file:/dev/./urandom']
    if instrumented:
        cmd.extend(['-Dsolr18.trace=' + str(run_dir / 'events.tsv'),
                    '-Dsolr18.plan=',
                    '-javaagent:' + str(JACOCO) + '=destfile=' + str(run_dir / 'jacoco.exec')
                    + ',includes=org.apache.solr.*,dumponexit=true,append=false'])
    cmd.extend(['-cp', alternate_classpath() if instrumented else clean_classpath(),
                'research.solr18.OriginalJUnit', TEST_CLASS, method])
    return cmd


def run_one(method: str, kind: str, frozen: dict, gate: dict) -> dict:
    run_id = method + '-' + kind
    instrumented = kind != 'clean'
    probe_class_sha = compile_probe() if instrumented else None
    out = ROOT / run_id
    assert not out.exists(), f'unreceipted raw directory exists: {out}'
    out.mkdir(parents=True)
    scratch = out / 'scratch'
    scratch.mkdir()
    cmd = command(method, instrumented, scratch, out)
    start = time.monotonic()
    with (out / 'console.log').open('w') as log:
        try:
            code = subprocess.run(cmd, cwd=SOURCE, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=360).returncode
        except subprocess.TimeoutExpired:
            code = 124
    log_text = (out / 'console.log').read_text(errors='replace')
    checked = audit(out / 'events.tsv') if instrumented and (out / 'events.tsv').exists() else None
    manifest = {'schema_version': 1, 'run_id': run_id,
                'test': TEST_CLASS + '#' + method, 'kind': kind,
                'original_junit': True, 'seed': SEED, 'plan': [],
                'started_at_utc': gate['checked_at_utc'], 'finished_at_utc': stamp(),
                'elapsed_seconds': round(time.monotonic() - start, 3),
                'junit_exit': code,
                'junit_summary_present': 'SOLR18_ORIGINAL_JUNIT ran=1 ignored=0 failures=0' in log_text,
                'assumption_failure_count': log_text.count('SOLR18_ASSUMPTION_FAILURE '),
                'gate': gate, 'frozen': frozen,
                'alternate_probe_class_sha256': probe_class_sha,
                'actor_audit': checked,
                'raw_file_sha256': {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
    atomic_json(out / 'run.json', manifest)
    return manifest


def passed(row: dict) -> bool:
    return (row['junit_exit'] == 0 and row['junit_summary_present']
            and row['assumption_failure_count'] == 0)


def next_work(state: dict) -> tuple[str, str] | None:
    if verdict(state)['qualifying_candidates']:
        return None
    for method in CANDIDATES:
        runs = state['candidates'].setdefault(method, {})
        if 'clean' not in runs:
            return method, 'clean'
        if not passed(runs['clean']):
            continue
        if 'instrumented-a' not in runs:
            return method, 'instrumented-a'
        first = runs['instrumented-a']
        checked = first.get('actor_audit') or {}
        if not passed(first) or not checked.get('selected_target') \
                or not checked.get('stable_root_candidates'):
            continue
        if 'instrumented-b' not in runs:
            return method, 'instrumented-b'
    return None


def verdict(state: dict) -> dict:
    qualifying = {}
    for method in CANDIDATES:
        runs = state['candidates'].get(method, {})
        a, b = runs.get('instrumented-a'), runs.get('instrumented-b')
        if a and b and passed(a) and passed(b):
            aa, bb = a['actor_audit'], b['actor_audit']
            stable = sorted(set(aa['stable_root_candidates']) &
                            set(bb['stable_root_candidates']))
            if aa['selected_target'] and bb['selected_target'] and stable:
                qualifying[method] = {'stable_novel_roots': stable,
                                      'healthy_run_ids': [a['run_id'], b['run_id']]}
    return {'qualifying_candidates': qualifying,
            'status': 'new_supplemental_stage_possible' if qualifying
                      else 'bounded_alternate_junit_calibration_exhausted'}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--one', action='store_true', required=True)
    args = parser.parse_args()
    frozen = validate_frozen()
    state = {'schema_version': 1, 'phase': 'alternate_original_junit_feasibility',
             'frozen': frozen, 'candidates': {}, 'finished': False}
    if STATE.exists():
        state = json.loads(STATE.read_text())
        assert state['frozen'] == frozen
    work = next_work(state)
    if work is None:
        state.update(verdict(state))
        state['finished'] = True
        state.setdefault('finished_at_utc', stamp())
        atomic_json(STATE, state)
        print(json.dumps({'status': state['status'], 'qualifying_candidates':
                          state['qualifying_candidates']}))
        return
    method, kind = work
    with LOCK.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        gate = resource_gate()
        row = run_one(method, kind, frozen, gate)
    state['candidates'][method][kind] = row
    state['last_checkpoint_at_utc'] = stamp()
    atomic_json(STATE, state)
    print(json.dumps({'run_id': row['run_id'], 'junit_exit': row['junit_exit'],
                      'selected_target': (row['actor_audit'] or {}).get('selected_target'),
                      'novel_roots': (row['actor_audit'] or {}).get('stable_root_candidates', []),
                      'next': next_work(state)}, sort_keys=True))


if __name__ == '__main__':
    main()
