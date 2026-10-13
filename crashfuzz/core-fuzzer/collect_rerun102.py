#!/usr/bin/env python3
"""Merge the three nodes' per-case checkpoints into the 102-check table."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SSH = ['/usr/bin/ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes']
REMOTE_ROOT = '/users/ZhenyuLi/static-rerun/results'
LOCAL_ROOT = ROOT / '.study-repairs/static102-rerun'
OFFLOADS = ROOT / 'data/crashfuzz/static102-offloads.json'
REVIEWS = ROOT / 'data/crashfuzz/static102-candidate-reviews.json'
MIGRATIONS = ROOT / 'data/crashfuzz/static102-campaign-migrations.json'
COLUMNS = ('case_id', 'system', 'status', 'finished', 'bug_mark',
           'review_verdict', 'review_reason', 'review_evidence',
           'target_file', 'target_function', 'target_line', 'target_site_id',
           'check_code', 'cluster_test', 'total_elapsed_seconds',
           'active_runtime_seconds',
           'prior_campaign_elapsed_seconds', 'prior_campaign_fault_trials',
           'prior_campaign_strict_injections', 'prior_campaign_breakdown',
           'current_campaign_elapsed_seconds',
           'current_campaign_fault_trials', 'migration_audit',
           'healthy_seconds', 'fault_trials', 'active_trial', 'strict_injections',
           'healthy_target_reached', 'post_fault_target_reach_trials',
           'lost_target_trials', 'target_outcome_changed_trials',
           'coverage_gain_methods', 'coverage_gain_branches',
           'target_exception_candidates',
           'static_io_calls', 'static_coverage_methods', 'campaign_result',
           'archive_host', 'archive_path', 'error')


def enrich_live_trials(value: dict, state: dict) -> None:
    completed = state.get('completed', [])
    statuses = [trial.get('status') for trial in completed]
    value['fault_trials'] = len(completed)
    value['strict_injections'] = sum(status not in (None, 'unmatched')
                                     for status in statuses)
    value['post_fault_target_reach_trials'] = sum(
        status not in (None, 'unmatched', 'lost_target') for status in statuses)
    candidates = statuses.count('target_exception_candidate')
    value['target_exception_candidates'] = candidates
    if candidates:
        value['bug_mark'] = 'candidate'


def reconcile_elapsed(value: dict) -> None:
    """A resumed worker's final wall segment cannot undercount prior trials."""
    active = value.get('active_runtime_seconds')
    if active is None:
        return
    value['active_runtime_seconds'] = round(float(active), 3)
    total = value.get('total_elapsed_seconds')
    value['total_elapsed_seconds'] = round(max(float(total or 0), float(active)), 3)


def apply_campaign_migration(value: dict, migrations: dict[str, dict]) -> None:
    """Keep retired trials separate while charging their time to the check."""
    migration = migrations.get(value['case_id'])
    if not migration:
        return
    replacement = migration['replacement_campaign']
    paths = (value.get('healthy_manifest') or '', value.get('campaign_result') or '')
    if not any(replacement in path for path in paths):
        return
    retired = migration['retired_campaigns']
    prior = sum(float(item['elapsed_seconds']) for item in retired)
    # A terminal worker inherits the previous summary's elapsed time only
    # when that summary had a value. HBase's retired summaries were terminal;
    # the interrupted Solr summaries had no elapsed value. Compare the
    # reported wall time with the replacement checkpoint to distinguish the
    # two cases, while using the checkpoint as the lower bound during a run.
    reported = float(value.get('total_elapsed_seconds') or 0)
    active = float(value.get('active_runtime_seconds') or 0)
    cumulative = prior > 0 and reported >= prior + active - 0.001
    current = max(reported - prior if cumulative else reported, active)
    value['prior_campaign_elapsed_seconds'] = round(prior, 3)
    value['prior_campaign_fault_trials'] = sum(
        int(item['completed_trials']) for item in retired)
    value['prior_campaign_strict_injections'] = sum(
        int(item['strict_injections']) for item in retired)
    value['prior_campaign_breakdown'] = json.dumps([
        {'campaign': item['campaign'],
         'elapsed_seconds': item['elapsed_seconds'],
         'completed_trials': item['completed_trials'],
         'budget_trials': item['budget_trials']}
        for item in retired], separators=(',', ':'))
    value['current_campaign_elapsed_seconds'] = round(current, 3)
    value['current_campaign_fault_trials'] = value.get('fault_trials') or 0
    value['migration_audit'] = ';'.join(item['audit_path'] for item in retired)
    value['total_elapsed_seconds'] = round(prior + current, 3)


def apply_candidate_review(value: dict, reviews: dict[str, dict]) -> None:
    count = int(value.get('target_exception_candidates') or 0)
    if count < 1:
        return
    review = reviews.get(value['case_id'])
    if not review or count > review.get('reviewed_candidate_count', 0):
        value['review_verdict'] = 'pending_source_review'
        return
    value['review_verdict'] = review['verdict']
    value['review_reason'] = review['reason']
    value['review_evidence'] = review['evidence']
    if review['verdict'].startswith('rejected_'):
        value['bug_mark'] = 'rejected'


def enrich_result_metrics(value: dict, record: dict) -> None:
    gain = record.get('coverage_gain_by_kind') or {}
    value['healthy_target_reached'] = record.get('target_reached')
    value['lost_target_trials'] = record.get('lost_target_trials')
    value['target_outcome_changed_trials'] = record.get('target_outcome_changed_trials')
    value['coverage_gain_methods'] = gain.get('methods')
    value['coverage_gain_branches'] = gain.get('branch_outcomes')


def enrich_live_summary(base: Path, value: dict) -> None:
    if value.get('status') != 'fuzzing' or value.get('finished'):
        return
    artifact = (Path(value['selection_artifact'])
                if value.get('selection_artifact') else
                base / ('caller-expanded/soot-selection.json'
                        if value.get('selection_profile') == 'caller_expanded'
                        else 'soot-selection.json'))
    digest = (json.loads(artifact.read_text()).get('input_digest')
              if artifact.is_file() else None)
    for state_path in sorted(base.glob('campaign*/' + value['case_id'] + '/state.json'),
                             key=lambda path: path.stat().st_mtime, reverse=True):
        state = json.loads(state_path.read_text())
        if digest and state.get('static_selection_digest') != digest:
            continue
        enrich_live_trials(value, state)
        active = state.get('active')
        value['active_trial'] = active.get('number') if isinstance(active, dict) else None
        value['active_runtime_seconds'] = state.get('active_runtime_seconds')
        result_path = state_path.with_name('result.json')
        if result_path.is_file():
            enrich_result_metrics(value, json.loads(result_path.read_text()))
        break


def local_summaries() -> dict[str, dict]:
    result = {}
    for path in LOCAL_ROOT.glob('*/case-summary.json'):
        try:
            value = json.loads(path.read_text())
            if value.get('campaign_result'):
                result_path = Path(value['campaign_result'])
                if result_path.is_file():
                    record = json.loads(result_path.read_text())
                    enrich_result_metrics(value, record)
                    if not value.get('active_runtime_seconds'):
                        value['active_runtime_seconds'] = record.get('total_elapsed_seconds')
            enrich_live_summary(path.parent, value)
            reconcile_elapsed(value)
            result[value['case_id']] = value
        except (OSError, ValueError, KeyError):
            continue
    return result


def remote_summaries(host: str) -> dict[str, dict]:
    script = ("import glob,json,pathlib\n"
              "rows=[]\n"
              "for p in glob.glob('/users/ZhenyuLi/static-rerun/results/*/case-summary.json'):\n"
              "    try:\n"
              "        row=json.load(open(p))\n"
              "        base=pathlib.Path(p).parent\n"
              "        result=row.get('campaign_result')\n"
              "        if result and pathlib.Path(result).is_file():\n"
              "            record=json.load(open(result))\n"
              "            gain=record.get('coverage_gain_by_kind') or {}\n"
              "            row.update(healthy_target_reached=record.get('target_reached'),lost_target_trials=record.get('lost_target_trials'),target_outcome_changed_trials=record.get('target_outcome_changed_trials'),coverage_gain_methods=gain.get('methods'),coverage_gain_branches=gain.get('branch_outcomes'))\n"
              "            if not row.get('active_runtime_seconds'): row['active_runtime_seconds']=record.get('total_elapsed_seconds')\n"
              "        if row.get('status')=='fuzzing' and not row.get('finished'):\n"
              "            artifact=pathlib.Path(row['selection_artifact']) if row.get('selection_artifact') else base/('caller-expanded/soot-selection.json' if row.get('selection_profile')=='caller_expanded' else 'soot-selection.json')\n"
              "            digest=json.load(open(artifact)).get('input_digest') if artifact.is_file() else None\n"
              "            states=sorted(base.glob('campaign*/'+row['case_id']+'/state.json'),key=lambda s:s.stat().st_mtime,reverse=True)\n"
              "            for state_path in states:\n"
              "                state=json.load(open(state_path))\n"
              "                if digest and state.get('static_selection_digest')!=digest: continue\n"
              "                statuses=[trial.get('status') for trial in state.get('completed',[])]\n"
              "                row['fault_trials']=len(statuses)\n"
              "                row['strict_injections']=sum(s not in (None,'unmatched') for s in statuses)\n"
              "                row['post_fault_target_reach_trials']=sum(s not in (None,'unmatched','lost_target') for s in statuses)\n"
              "                row['target_exception_candidates']=statuses.count('target_exception_candidate')\n"
              "                if row['target_exception_candidates']: row['bug_mark']='candidate'\n"
              "                active=state.get('active')\n"
              "                row['active_trial']=active.get('number') if isinstance(active,dict) else None\n"
              "                row['active_runtime_seconds']=state.get('active_runtime_seconds')\n"
              "                result_path=state_path.with_name('result.json')\n"
              "                if result_path.is_file():\n"
              "                    record=json.load(open(result_path))\n"
              "                    gain=record.get('coverage_gain_by_kind') or {}\n"
              "                    row.update(healthy_target_reached=record.get('target_reached'),lost_target_trials=record.get('lost_target_trials'),target_outcome_changed_trials=record.get('target_outcome_changed_trials'),coverage_gain_methods=gain.get('methods'),coverage_gain_branches=gain.get('branch_outcomes'))\n"
              "                break\n"
              "        active=row.get('active_runtime_seconds')\n"
              "        if active is not None:\n"
              "            row['active_runtime_seconds']=round(float(active),3)\n"
              "            row['total_elapsed_seconds']=round(max(float(row.get('total_elapsed_seconds') or 0),float(active)),3)\n"
              "        rows.append(row)\n"
              "    except (OSError, ValueError): pass\n"
              "print(json.dumps(rows))\n")
    process = subprocess.run(SSH + ['ZhenyuLi@' + host, 'python3', '-'],
                             input=script, text=True, capture_output=True, timeout=20,
                             check=False)
    if process.returncode:
        raise RuntimeError(f'{host}: {process.stderr.strip()}')
    return {row['case_id']: row for row in json.loads(process.stdout)}


def accepts_remote_case(host: str, cid: str, offloads: dict[str, dict]) -> bool:
    if host == 'node1':
        return cid.startswith('HBASE-')
    if host == 'node2':
        return (cid.startswith(('SOLR-', 'ZOOKEEPER-')) or
                (offloads.get(cid, {}).get('state') == 'active' and
                 offloads[cid].get('execution_host') == host))
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'data/crashfuzz/static102-rerun.tsv')
    args = parser.parse_args()
    original = [row for row in json.loads(
        (ROOT / 'data/crashfuzz/checklist102.json').read_text())['rows']
        if row.get('selection_group') == 'original_102']
    if len(original) != 102:
        raise ValueError(f'expected 102 original checks, got {len(original)}')
    offloads = json.loads(OFFLOADS.read_text()).get('cases', {}) if OFFLOADS.is_file() else {}
    reviews = json.loads(REVIEWS.read_text()).get('cases', {}) if REVIEWS.is_file() else {}
    migrations = (json.loads(MIGRATIONS.read_text()).get('cases', {})
                  if MIGRATIONS.is_file() else {})
    summaries = local_summaries()
    for node in ('node1', 'node2'):
        try:
            updates = remote_summaries(node)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            print(f'collector: {error}', flush=True)
            continue
        for cid, row in updates.items():
            if accepts_remote_case(node, cid, offloads):
                summaries[cid] = row
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COLUMNS, delimiter='\t',
                            lineterminator='\n', extrasaction='ignore')
    writer.writeheader()
    for row in original:
        location = row['exact_check_location']
        baseline = {'case_id': row['case_id'], 'system': row['system'],
                    'status': 'pending', 'finished': False, 'bug_mark': 'none',
                    'target_file': location['file'],
                    'target_function': location['enclosing_function'],
                    'target_line': location['selected_line'],
                    'target_site_id': location['site_id'],
                    'check_code': row.get('check_code'),
                    'cluster_test': row.get('cluster_test')}
        merged = {**baseline, **summaries.get(row['case_id'], {})}
        apply_campaign_migration(merged, migrations)
        apply_candidate_review(merged, reviews)
        writer.writerow({key: (value.replace('\r', ' ').replace('\n', '\\n')
                              if isinstance(value, str) else value)
                         for key, value in merged.items()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + f'.tmp.{os.getpid()}')
    temporary.write_text(output.getvalue())
    os.replace(temporary, args.output)
    print(json.dumps({'rows': len(original),
                      'started': sum(row['case_id'] in summaries for row in original),
                      'finished': sum(bool(summaries.get(row['case_id'], {}).get('finished'))
                                      for row in original),
                      'output': str(args.output)}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
