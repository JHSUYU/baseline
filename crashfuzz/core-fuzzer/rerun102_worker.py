#!/usr/bin/env python3
"""Resumable original-JUnit campaign for the statically selected 102 checks.

Run one worker per system. Each case has its own healthy trace, fuzzer
checkpoint, and summary; restarting a worker skips finished cases.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from fuzzer import atomic_json, campaign, point_from_event
from prepare_case_selection import analysis_for
from soot_selection import prepare

HERE = Path(__file__).resolve().parent
SOURCE_ROOT = Path('/users/ZhenyuLi/.graphchecker-sources')
SOURCE_DIR = {'HDFS': 'hadoop-3.4.3', 'HBase': 'hbase-2.6.6',
              'Solr': 'solr-8.11.4', 'ZooKeeper': 'zookeeper-3.8.7'}
RUNNER = {'HDFS': 'original_hdfs_junit.py',
          'HBase': 'original_hbase_junit.py',
          'Solr': 'original_solr_junit.py',
          'ZooKeeper': 'original_zookeeper_junit.py'}
TIMEOUT = {'HDFS': 240, 'HBase': 300, 'Solr': 600, 'ZooKeeper': 180}


def family(system: str) -> str:
    return next(name for name in SOURCE_DIR if system.startswith(name))


def test_spec(row: dict) -> tuple[str, str]:
    raw = row.get('cluster_test')
    if not raw:
        raise ValueError('no cluster test')
    raw = raw.split(';', 1)[0].strip()
    if '#' in raw:
        clazz, method = raw.split('#', 1)
    elif '.' in raw:
        clazz, method = raw.rsplit('.', 1)
    else:
        raise ValueError(f'cannot parse cluster test: {raw}')
    # JUnit 4's Request.method can match the displayed parameterized name;
    # Jupiter's selector uses the source method name.
    if family(row['system']) != 'HDFS':
        method = re.sub(r'\[\d+\]$|\(.*\)$', '', method)
    if '.' not in clazz:
        root = SOURCE_ROOT / SOURCE_DIR[family(row['system'])]
        matches = sorted(root.rglob(clazz + '.java'))
        if len(matches) != 1:
            raise ValueError(f'ambiguous test class {clazz}: {len(matches)} source matches')
        source = matches[0].read_text(errors='replace')
        package = re.search(r'^package\s+([\w.]+)\s*;', source, re.M)
        if not package:
            raise ValueError(f'package missing in {matches[0]}')
        clazz = package.group(1) + '.' + clazz
    return clazz, method


def exception_type(row: dict) -> str | None:
    code = row.get('check_code', '')
    source = (SOURCE_ROOT / SOURCE_DIR[family(row['system'])] /
              row['exact_check_location']['file'])
    text = source.read_text(errors='replace') if source.is_file() else ''
    match = re.search(r'throw\s+new\s+([\w.]+)\s*\(', code)
    if not match:
        # A selected check can allocate an exception and throw its local
        # variable, or rethrow the exception received by its catch block.
        match = re.search(r'\b([\w.]+)\s+\w+\s*=\s*new\s+\1\s*\(', code)
    if not match:
        rethrow = re.search(r'throw\s+(\w+)\s*;', code)
        if rethrow:
            # Resolve the caught variable in the source preceding this check,
            # using the nearest matching catch in the enclosing method.
            prefix = '\n'.join(text.splitlines()[:
                int(row['exact_check_location']['selected_line'])])
            catches = list(re.finditer(
                r'catch\s*\(\s*([\w.]+)\s+' + re.escape(rethrow.group(1)) +
                r'\s*\)', prefix))
            if catches:
                match = catches[-1]

    def binary_name(qualified: str) -> str:
        # Java imports use Outer.Inner, whereas stack traces use Outer$Inner.
        return re.sub(r'([A-Z][\w]*)\.([A-Z][\w]*)', r'\1$\2', qualified)

    if match:
        name = match.group(1)
        if '.' in name:
            outer, *nested = name.split('.')
            imported = re.search(r'^import\s+([\w.]+\.' + re.escape(outer) +
                                 r')\s*;', text, re.M)
            if imported:
                return binary_name(imported.group(1) + ''.join('.' + part
                                                              for part in nested))
            if outer[0].islower():
                return binary_name(name)
        else:
            imported = re.search(r'^import\s+([\w.]+\.' + re.escape(name) +
                                 r')\s*;', text, re.M)
            if imported:
                return binary_name(imported.group(1))
            if name in {'IOException', 'EOFException', 'IllegalArgumentException',
                        'IllegalStateException', 'RuntimeException',
                        'AssertionError'}:
                return ('java.io.' if name in {'IOException', 'EOFException'}
                        else 'java.lang.') + name
            # A subclass may refer to a public nested exception inherited
            # from its imported superclass (for example SecretManager.InvalidToken).
            parent = re.search(r'\bclass\s+\w+[^\{;]*?\bextends\s+(\w+)', text)
            if parent:
                base = parent.group(1)
                base_import = re.search(r'^import\s+([\w.]+\.' + re.escape(base) +
                                        r')\s*;', text, re.M)
                if base_import and re.search(r'\bthrows\s+' + re.escape(name) +
                                             r'\b', text):
                    return binary_name(base_import.group(1) + '.' + name)
            package = re.search(r'^package\s+([\w.]+)\s*;', text, re.M)
            if package:
                return package.group(1) + '.' + name
    if 'RoutedAlias.newAliasMustExistException' in code:
        return 'org.apache.solr.common.SolrException'
    if 'Preconditions.checkState' in code:
        return 'java.lang.IllegalStateException'
    if 'Preconditions.checkArgument' in code:
        return 'java.lang.IllegalArgumentException'
    if re.search(r'\bassert\s+', code):
        return 'java.lang.AssertionError'
    # Some coordination checks are state guards rather than throw sites.
    # They still supply reachability and coverage feedback; the generic
    # target-exception oracle is disabled for them until a throw is observed
    # at the selected check itself.
    return None


def run_logged(argv: list[str], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as log:
        return subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT,
                              check=False).returncode


def run_healthy_with_retry(argv: list[str], log: Path, output: Path) -> int:
    """Retry one failed clean JUnit; retain its setup failure for diagnosis."""
    first = run_logged(argv, log)
    if first == 0:
        return 0
    log.replace(log.with_name(log.stem + '-failed-1' + log.suffix))
    for name in ('junit.log', 'manifest.json'):
        source = output / name
        if source.is_file():
            shutil.copy2(source, output / (name + '.failed-1'))
    return run_logged(argv, log)


def healthy_matches(manifest: Path, digest: str) -> bool:
    if not manifest.is_file():
        return False
    try:
        record = json.loads(manifest.read_text())
        if record.get('returncode') != 0:
            return False
        with Path(record['trace']).open() as stream:
            for line in stream:
                event = json.loads(line)
                if event.get('event') == 'STATIC_SELECTION_APPLIED':
                    return event.get('digest') == digest
    except (OSError, ValueError, KeyError):
        return False
    return False


def observed_fault_points(trace: Path) -> bool:
    with trace.open() as stream:
        return any((event := json.loads(line)).get('event') ==
                   'FAULT_POINT_OBSERVED' and point_from_event(event) is not None
                   for line in stream)


def live_selection_artifact(base: Path, cid: str, target: str) -> Path | None:
    """Keep an unfinished case's exact Soot result across worker restarts."""
    for artifact in (base / 'caller-expanded-800/soot-selection.json',
                     base / 'caller-expanded/soot-selection.json',
                     base / 'soot-selection.json'):
        if not artifact.is_file():
            continue
        try:
            selected = json.loads(artifact.read_text())
            if selected.get('target_method') != target or not selected.get('input_digest'):
                continue
            for state_path in base.glob('campaign*/' + cid + '/state.json'):
                state = json.loads(state_path.read_text())
                if (state.get('static_selection_digest') == selected['input_digest']
                        and (state.get('seed') or state.get('completed'))):
                    return artifact
        except (OSError, ValueError):
            continue
    return None


def healthy_dir(base: Path, selection: dict, campaign_suffix: str = '') -> Path:
    profile = selection.get('selection_profile')
    name = {'caller_expanded': 'healthy-expanded',
            'caller_expanded_800': 'healthy-800'}.get(profile, 'healthy')
    return base / (name + ('-' + campaign_suffix if campaign_suffix else ''))


def _run_case_unlocked(row: dict, result_root: Path, max_trials: int,
                       max_faults: int, campaign_suffix: str = '',
                       refresh_selection: bool = False) -> dict:
    cid = row['case_id']
    base = result_root / cid
    base.mkdir(parents=True, exist_ok=True)
    summary_path = base / 'case-summary.json'
    previous_seconds = 0.0
    prior = None
    if summary_path.is_file():
        prior = json.loads(summary_path.read_text())
        previous_seconds = float(prior.get('total_elapsed_seconds') or 0)
        if prior.get('finished') and not (refresh_selection or campaign_suffix):
            return prior
    location = row['exact_check_location']
    summary = {'case_id': cid, 'system': row['system'],
               'target_file': location['file'],
               'target_function': location['enclosing_function'],
               'target_line': location['selected_line'],
               'target_site_id': location['site_id'],
               'check_code': row.get('check_code'),
               'cluster_test': row.get('cluster_test'),
               'status': 'preparing', 'bug_mark': 'none',
               'finished': False, 'updated_at': time.time()}
    atomic_json(summary_path, summary)
    if not row.get('cluster_test'):
        summary.update(status='no_cluster_test', finished=True,
                       total_elapsed_seconds=0, fault_trials=0)
        atomic_json(summary_path, summary)
        return summary
    started = time.monotonic()
    try:
        clazz, method = test_spec(row)
        # Selection catalogs may identify the check by a Soot unit (#u) or
        # by an exact source line (#L). Both belong to the same method.
        target = location['site_id'].split('#', 1)[0]
        exc_type = exception_type(row)
        pinned = None if refresh_selection else live_selection_artifact(base, cid, target)
        selection = prepare({'target': {'method': target},
                             'static_selection': ({'artifact': str(pinned)} if pinned
                                                  else {'analysis':
                                                        analysis_for(row['system'])})},
                            base)
        artifact = Path(selection['artifact_path'])
        selection['target_site_id'] = location['site_id']
        selection['target_check_line'] = location['check_start_line']
        selection['target_selected_line'] = location['selected_line']
        atomic_json(artifact, selection)
        summary.update(status='healthy', test_class=clazz, test_method=method,
                       exception_type=exc_type,
                       static_io_calls=len(selection['io_calls']),
                       static_coverage_methods=len(selection['coverage_methods']))
        atomic_json(summary_path, summary)
        healthy = healthy_dir(base, selection, campaign_suffix)
        manifest = healthy / 'manifest.json'
        if not healthy_matches(manifest, selection['input_digest']):
            argv = ['python3', str(HERE / RUNNER[family(row['system'])]),
                    '--case-id', cid, '--test-class', clazz, '--test-method', method,
                    '--output', str(healthy), '--static-selection', str(artifact),
                    '--timeout', str(TIMEOUT[family(row['system'])])]
            if run_healthy_with_retry(argv, base / 'healthy-run.log', healthy) != 0:
                raise RuntimeError('original healthy JUnit did not pass')
        healthy_record = json.loads(manifest.read_text())
        if (not observed_fault_points(Path(healthy_record['trace']))
                and selection.get('selection_profile') not in
                ('caller_expanded', 'caller_expanded_800')):
            # A check can be reached through a deeper caller path than the
            # default coarse selection covers. Widen the Soot caller walk
            # automatically before declaring that the workload has no I/O.
            expanded_analysis = analysis_for(row['system'])
            expanded_analysis.update(max_caller_depth=6, max_callee_depth=0)
            selection = prepare({'target': {'method': target},
                                 'static_selection': {'analysis': expanded_analysis}},
                                base / 'caller-expanded')
            artifact = Path(selection['artifact_path'])
            selection.update(target_site_id=location['site_id'],
                             target_check_line=location['check_start_line'],
                             target_selected_line=location['selected_line'],
                             selection_profile='caller_expanded')
            atomic_json(artifact, selection)
            summary.update(static_io_calls=len(selection['io_calls']),
                           static_coverage_methods=len(selection['coverage_methods']),
                           selection_profile='caller_expanded')
            atomic_json(summary_path, summary)
            healthy = healthy_dir(base, selection, campaign_suffix)
            manifest = healthy / 'manifest.json'
            if not healthy_matches(manifest, selection['input_digest']):
                argv = ['python3', str(HERE / RUNNER[family(row['system'])]),
                        '--case-id', cid, '--test-class', clazz, '--test-method', method,
                        '--output', str(healthy), '--static-selection', str(artifact),
                        '--timeout', str(TIMEOUT[family(row['system'])])]
                if run_healthy_with_retry(argv, base / 'healthy-expanded-run.log',
                                          healthy) != 0:
                    raise RuntimeError('original healthy JUnit did not pass with expanded selection')
            healthy_record = json.loads(manifest.read_text())
        if (not observed_fault_points(Path(healthy_record['trace']))
                and selection.get('selection_profile') != 'caller_expanded_800'):
            # A wide, still bounded scope is useful when a small method budget
            # is consumed by possible field writers before reached I/O callers.
            wide_analysis = analysis_for(row['system'])
            wide_analysis.update(max_methods=800, max_caller_depth=6,
                                 max_callee_depth=0)
            selection = prepare({'target': {'method': target},
                                 'static_selection': {'analysis': wide_analysis}},
                                base / 'caller-expanded-800')
            artifact = Path(selection['artifact_path'])
            selection.update(target_site_id=location['site_id'],
                             target_check_line=location['check_start_line'],
                             target_selected_line=location['selected_line'],
                             selection_profile='caller_expanded_800')
            atomic_json(artifact, selection)
            summary.update(static_io_calls=len(selection['io_calls']),
                           static_coverage_methods=len(selection['coverage_methods']),
                           selection_profile='caller_expanded_800')
            atomic_json(summary_path, summary)
            healthy = healthy_dir(base, selection, campaign_suffix)
            manifest = healthy / 'manifest.json'
            if not healthy_matches(manifest, selection['input_digest']):
                argv = ['python3', str(HERE / RUNNER[family(row['system'])]),
                        '--case-id', cid, '--test-class', clazz, '--test-method', method,
                        '--output', str(healthy), '--static-selection', str(artifact),
                        '--timeout', str(TIMEOUT[family(row['system'])])]
                if run_healthy_with_retry(argv, base / 'healthy-800-run.log',
                                          healthy) != 0:
                    raise RuntimeError('original healthy JUnit did not pass with wide selection')
            healthy_record = json.loads(manifest.read_text())
        summary.update(selection_artifact=str(artifact),
                       healthy_manifest=str(manifest))
        atomic_json(summary_path, summary)
        workspace = base / 'campaign-workspace'
        temp = base / 'campaign-temp'
        workspace.mkdir(exist_ok=True)
        temp.mkdir(exist_ok=True)
        command = ['python3', str(HERE / RUNNER[family(row['system'])]),
                   '--case-id', cid, '--test-class', clazz, '--test-method', method,
                   '--output', '{trace_dir}', '--static-selection', str(artifact),
                   '--timeout', str(TIMEOUT[family(row['system'])])]
        if family(row['system']) == 'Solr':
            command += ['--classes-dir', str(healthy / 'classes')]
        config = {'case_id': cid, 'system': row['system'],
                  'test_class': clazz, 'test_method': method,
                  'cwd': str(workspace),
                  'workspaces': {'system_test': str(workspace), 'temp': str(temp)},
                  'target': {'method': target, 'site_id': location['site_id'],
                             'check_events': ['CHECK_REACHED'],
                             'exception_type': exc_type,
                             'source_file': location['file'],
                             'source_line': location['selected_line'],
                             'code': row.get('check_code')},
                  'static_selection': {'artifact': str(artifact)},
                  'archive_completed_trials': True,
                  'seed': {'trace': healthy_record['trace'],
                           'elapsed_seconds': healthy_record['elapsed_seconds']},
                  'trial': {'command': command},
                  'budget': {'max_trials': max_trials, 'max_faults': max_faults,
                             'base_trials': min(80, max_trials),
                             'min_target_retained_trials': 30,
                             'max_unmatched_retries': 1},
                  'timeout_seconds': TIMEOUT[family(row['system'])] + 30}
        atomic_json(base / 'campaign-config.json', config)
        summary['status'] = 'fuzzing'
        atomic_json(summary_path, summary)
        legacy_state = base / 'campaign' / cid / 'state.json'
        campaign_root = base / 'campaign'
        if legacy_state.is_file():
            old = json.loads(legacy_state.read_text())
            if old.get('static_selection_digest') != selection['input_digest']:
                campaign_root = base / ('campaign-' + selection['input_digest'][:12])
        if campaign_suffix:
            campaign_root = base / (campaign_root.name + '-' + campaign_suffix)
        state = campaign(config, campaign_root)
        record_path = campaign_root / cid / 'result.json'
        record = json.loads(record_path.read_text())
        summary.update(status=record['status'], finished=state['finished'],
                       healthy_seconds=healthy_record['elapsed_seconds'],
                       fault_trials=record['fault_trials'],
                       strict_injections=record['strict_injections'],
                       post_fault_target_reach_trials=record['post_fault_target_reach_trials'],
                       target_exception_candidates=record['oracle_candidates'],
                       bug_mark=record['bug_mark'],
                       active_runtime_seconds=record['total_elapsed_seconds'],
                       total_elapsed_seconds=round(max(
                           previous_seconds + time.monotonic() - started,
                           float(record['total_elapsed_seconds'])), 3),
                       campaign_result=str(record_path))
    except Exception as error:
        if str(error).startswith('case already claimed:') and prior is not None:
            atomic_json(summary_path, prior)
            return prior
        summary.update(status='blocked_setup', error=str(error),
                       total_elapsed_seconds=round(previous_seconds +
                                                   time.monotonic() - started, 3))
    summary['updated_at'] = time.time()
    atomic_json(summary_path, summary)
    return summary


def run_case(row: dict, result_root: Path, max_trials: int,
             max_faults: int, campaign_suffix: str = '',
             refresh_selection: bool = False) -> dict:
    """Claim a case before setup so parallel workers cannot overwrite it."""
    base = result_root / row['case_id']
    base.mkdir(parents=True, exist_ok=True)
    with (base / '.run-case.lock').open('a+') as claim:
        try:
            fcntl.flock(claim, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            summary = base / 'case-summary.json'
            if summary.is_file():
                return json.loads(summary.read_text())
            return {'case_id': row['case_id'], 'system': row['system'],
                    'status': 'claimed_elsewhere', 'finished': False}
        try:
            return _run_case_unlocked(row, result_root, max_trials, max_faults,
                                      campaign_suffix, refresh_selection)
        finally:
            fcntl.flock(claim, fcntl.LOCK_UN)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--system', choices=SOURCE_DIR, required=True)
    parser.add_argument('--checklist', type=Path, required=True)
    parser.add_argument('--result-root', type=Path, required=True)
    parser.add_argument('--case-id', action='append')
    parser.add_argument('--include-added-checks', action='store_true',
                        help='also run the two separately listed known-issue checks')
    parser.add_argument('--exclude-case', action='append', default=[])
    parser.add_argument('--shard-index', type=int, default=0)
    parser.add_argument('--shard-count', type=int, default=1)
    parser.add_argument('--max-trials', type=int, default=240)
    parser.add_argument('--max-faults', type=int, default=10)
    parser.add_argument('--campaign-suffix', default='')
    parser.add_argument('--refresh-selection', action='store_true')
    args = parser.parse_args()
    if args.campaign_suffix and not re.fullmatch(r'[a-z0-9-]+', args.campaign_suffix):
        parser.error('campaign-suffix must use lowercase letters, digits, or hyphens')
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error('shard-index must be in [0, shard-count)')
    rows = json.loads(args.checklist.read_text())['rows']
    allowed_groups = {'original_102'}
    if args.include_added_checks:
        allowed_groups.add('added_known_issue_check')
    system_rows = [row for row in rows
                   if row.get('selection_group') in allowed_groups
                   and family(row['system']) == args.system]
    selected = [row for index, row in enumerate(system_rows)
                if index % args.shard_count == args.shard_index
                and (not args.case_id or row['case_id'] in args.case_id)
                and row['case_id'] not in args.exclude_case]
    for row in selected:
        result = run_case(row, args.result_root, args.max_trials, args.max_faults,
                          args.campaign_suffix, args.refresh_selection)
        print(json.dumps({key: result.get(key) for key in
                          ('case_id', 'status', 'finished', 'fault_trials',
                           'strict_injections', 'total_elapsed_seconds', 'error')}),
              flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
