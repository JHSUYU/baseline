#!/usr/bin/env python3
"""Recompute strict verdicts, exact target events, coverage, and provenance."""

import hashlib
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from campaign import (CASE, CHECKPOINT, HEALTHY, HERE, RESULT, ROOT, WORKERS,
                      candidates, events, selector)
from run_native import (AGENT, ASM, BUILD, GUARD_LINE, REPORT, RUNNER, SOURCE,
                        TARGET_METHOD, TEST_CLASS, TEST_METHOD, THROW_LINE)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    state = json.loads(CHECKPOINT.read_text())
    assert state['finished']
    result = json.loads(RESULT.read_text())
    source = SOURCE / 'zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java'
    lines = source.read_text().splitlines()
    assert TARGET_METHOD in source.read_text()
    assert 'if (' in lines[GUARD_LINE - 1]
    assert 'SessionMovedException' in lines[THROW_LINE - 1]
    class_rel = Path('zookeeper-server/target/classes/org/apache/zookeeper/server/SessionTrackerImpl.class')
    assert sha256(SOURCE / class_rel) == sha256(BUILD / class_rel)
    healthy = events('healthy-01')
    positive_path = ROOT / 'positive-control-01/run.json'
    assert json.loads((ROOT / 'healthy-01/run.json').read_text())['exit_code'] == 0
    assert any(x[1] == 'TARGET_GUARD' for x in healthy)
    assert not any(x[1] == 'TARGET_THROW' for x in healthy)
    if positive_path.exists():
        positive = events('positive-control-01')
        assert json.loads(positive_path.read_text())['exit_code'] == 0
        assert any(x[1] == 'TARGET_THROW'
                   and len(x[3]) > 1
                   and x[3][1] == 'org.apache.zookeeper.KeeperException$SessionMovedException'
                   for x in positive)
    local_sources = [*AGENT.parent.joinpath('src').rglob('*.java'),
                     *RUNNER.parent.joinpath('src').rglob('*.java')]
    violations = [str(p) for p in local_sources
                  if any(x in p.read_text().lower() for x in ('graphchecker', 'skeleton'))]
    for artifact in (AGENT, RUNNER):
        with zipfile.ZipFile(artifact) as jar:
            violations += [name for name in jar.namelist()
                           if any(x in jar.read(name).lower() for x in (b'graphchecker', b'skeleton'))]
    assert not violations, violations
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    cp = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    cp = ':'.join([ASM, cp.replace(str(BUILD), str(SOURCE)), str(RUNNER)])
    assert 'graphchecker' not in cp.lower() and 'skeleton' not in cp.lower()
    cp_sha = hashlib.sha256(cp.encode()).hexdigest()
    agent_sha, runner_sha = sha256(AGENT), sha256(RUNNER)
    raw_failures = []
    all_cov, retained_cov = set(), set()
    seen_plans = set()
    max_depth = 0
    strict_count = retained_count = throw_count = failure_count = 0
    target_retaining_failures = []
    for item in state['trials']:
        run_id = item['run_id']
        run = json.loads((ROOT / run_id / 'run.json').read_text())
        assert run['plan'] == item['plan']
        assert run['test_class'] == TEST_CLASS and run['method'] == TEST_METHOD
        assert run['target_method'] == TARGET_METHOD
        assert run['target_guard_line'] == GUARD_LINE and run['target_throw_line'] == THROW_LINE
        assert run['classpath_sha256'] == cp_sha
        assert run['agent_sha256'] == agent_sha and run['runner_sha256'] == runner_sha
        assert run['port_assignment_worker_count'] == 8
        assert run['port_assignment_worker_id'] in WORKERS
        trace = events(run_id)
        matched = [selector(x) for x in trace if x[1] == 'FAULT_MATCHED']
        applied_events = [x for x in trace if x[1] == 'FAULT_APPLIED']
        applied = [selector(x) for x in applied_events]
        strict = matched == item['plan'] and applied == item['plan']
        after = applied_events[-1][0] if applied_events else 0
        guards = [x for x in trace if x[1] == 'TARGET_GUARD' and x[0] > after]
        throws = [x for x in trace if x[1] == 'TARGET_THROW' and x[0] > after]
        all_throws = [x for x in trace if x[1] == 'TARGET_THROW']
        retained = strict and bool(guards)
        assert strict == item['strict_injection']
        assert retained == item['target_after_final_fault']
        assert len(guards) == item['target_guard_after_fault_count']
        assert [x[3][0] for x in guards] == item['target_guard_sessions_after_fault']
        assert len(throws) == item['target_throw_after_fault_count']
        assert len(all_throws) == item['target_throw_total_count']
        assert all(len(x[3]) > 1
                   and x[3][1] == 'org.apache.zookeeper.KeeperException$SessionMovedException'
                   for x in all_throws)
        assert (candidates(trace, after) if retained else []) == item['candidate_pretarget_io']
        cov_path = ROOT / run_id / 'coverage.tsv'
        cov = set(cov_path.read_text().splitlines()) if cov_path.exists() else set()
        novel = cov - HEALTHY
        assert sorted(novel) == item['new_production_coverage']
        all_cov |= novel
        if retained:
            retained_cov |= novel
        seen_plans.add(tuple(item['plan']))
        strict_count += strict
        retained_count += retained
        throw_count += len(throws)
        failure_count += run['exit_code'] != 0
        max_depth = max(max_depth, len(item['plan']))
        if run['exit_code'] != 0:
            failure = {'trial': run_id, 'plan': item['plan'],
                       'strict': strict, 'target_after_fault': retained,
                       'target_throw_after_fault': len(throws)}
            raw_failures.append(failure)
            if retained:
                target_retaining_failures.append(failure)
    assert len(seen_plans) == len(state['trials'])
    assert result['fault_trials'] == len(state['trials'])
    assert result['strict_injections'] == strict_count
    assert result['target_after_fault'] == retained_count
    assert result['coverage_gain'] == len(retained_cov)
    assert result['coverage_gain_all_attempts'] == len(all_cov)
    assert result['max_fault_depth_attempted'] == max_depth
    data = {
        'original_test': TEST_CLASS + '#' + TEST_METHOD,
        'original_source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae',
        'target_guard_source': 'SessionTrackerImpl.java:' + str(GUARD_LINE),
        'target_throw_source': 'SessionTrackerImpl.java:' + str(THROW_LINE)
                               + ' KeeperException.SessionMovedException',
        'healthy_junit_exit': 0,
        'healthy_target_guards': sum(x[1] == 'TARGET_GUARD' for x in healthy),
        'healthy_target_throws': 0,
        'positive_control_available': positive_path.exists(),
        'independent_classpath_sha256': cp_sha,
        'graphchecker_or_skeleton_in_classpath_agent_or_runner': False,
        'agent_sha256': agent_sha, 'runner_sha256': runner_sha,
        'trials_reaudited': len(state['trials']), 'strict': strict_count,
        'target_retaining': retained_count, 'target_throw_after_fault': throw_count,
        'junit_nonzero': failure_count, 'junit_nonzero_trials': raw_failures,
        'target_retaining_junit_nonzero_trials': target_retaining_failures,
        'max_fault_depth': max_depth,
        'retained_coverage_gain_lines': sorted(retained_cov),
        'all_attempt_coverage_gain_lines': sorted(all_cov),
        'budget': state['budget'], 'max_faults': state['max_faults'],
        'stop_reason': state['stop_reason'],
        'late_extension_signal': state.get('late_extension_signal'),
        'legacy_trials_excluded': json.loads((CASE / 'legacy-graph-result.json').read_text()).get('fault_trials'),
    }
    path = HERE / 'audit.json'
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    temp.replace(path)
    print(json.dumps({k: v for k, v in data.items()
                      if k not in ('retained_coverage_gain_lines', 'all_attempt_coverage_gain_lines',
                                   'junit_nonzero_trials')}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
