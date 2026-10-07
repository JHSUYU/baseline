#!/usr/bin/env python3
"""Project authoritative SOLR-13 campaign checkpoint into the shared table row."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRESS = HERE / 'evidence/campaign/progress.json'
STAGE2_PROGRESS = HERE.parent / 'stage2/evidence/campaign-node1-mirror/progress.json'
RESULT = HERE.parents[1] / 'result.json'


def main() -> None:
    progress = json.loads(PROGRESS.read_text())
    result = json.loads(RESULT.read_text())
    stage2 = json.loads(STAGE2_PROGRESS.read_text()) if STAGE2_PROGRESS.is_file() else None
    if stage2 is not None:
        if stage2.get('case_id') != 'SOLR-13' or stage2.get('phase') != 'overseer_alias_write':
            raise ValueError('wrong node1 SOLR-13 phase mirror')
        if stage2['effective_target_retaining_trials'] > stage2['strict_injections']:
            raise ValueError('stage2 effective count exceeds strict count')
    phase_statuses = [progress['status']]
    if stage2 is not None:
        phase_statuses.append(stage2['status'])
    status = ('candidate_target_exception' if 'candidate_target_exception' in phase_statuses
              else 'running' if 'running' in phase_statuses
              else 'budget_complete' if all(s == 'budget_complete' for s in phase_statuses)
              else 'partial_budget')
    result.update({
        'status': status,
        'top_level_counter_scope': 'stage1_target_context_zk_only',
        'fault_trials': progress['attempted_plans'],
        'jvm_attempts': progress['jvm_attempts'],
        'strict_injections': progress['strict_injections'],
        'fully_applied_trials': progress['strict_injections'],
        'post_fault_target_reach_trials': progress['effective_target_retaining_trials'],
        'target_after_fault': progress['effective_target_retaining_trials'],
        'target_exception_candidates': progress['target_exception_candidates'],
        'coverage_gain': progress['production_probe_gain'],
        'max_applied_faults': progress['max_applied_faults'],
        'elapsed_seconds': progress['elapsed_seconds'],
        'evidence': 'cases/SOLR-13/independent/fuzz/evidence/campaign/progress.json',
    })
    stages = {
        'target_context_zk': {
            'host': 'node0', 'status': progress['status'],
            'attempted_plans': progress['attempted_plans'],
            'jvm_attempts': progress['jvm_attempts'],
            'strict_injections': progress['strict_injections'],
            'effective_target_retaining_trials': progress['effective_target_retaining_trials'],
            'target_exception_candidates': progress['target_exception_candidates'],
            'production_probe_gain': progress['production_probe_gain'],
            'elapsed_seconds': progress['elapsed_seconds'],
            'evidence': 'cases/SOLR-13/independent/fuzz/evidence/campaign/progress.json',
        },
    }
    if stage2 is not None:
        stages['overseer_alias_write'] = {
            'host': 'node1', 'status': stage2['status'],
            'attempted_plans': stage2['attempted_plans'],
            'jvm_attempts': stage2['jvm_attempts'],
            'valid_jvm_attempts': stage2.get('valid_jvm_attempts'),
            'invalid_setup_plans': stage2.get('invalid_setup_plans', 0),
            'invalid_setup_jvm_attempts': stage2.get('invalid_setup_jvm_attempts', 0),
            'invalid_setup_elapsed_seconds': stage2.get('invalid_setup_elapsed_seconds', 0),
            'strict_injections': stage2['strict_injections'],
            'effective_target_retaining_trials': stage2['effective_target_retaining_trials'],
            'target_exception_candidates': stage2['target_exception_candidates'],
            'production_probe_gain': stage2['production_probe_gain'],
            'elapsed_seconds': stage2['elapsed_seconds'],
            'evidence': ('node1:cases/SOLR-13/independent/stage2/evidence/campaign/'
                         'progress.json'),
            'progress_mirror': ('cases/SOLR-13/independent/stage2/evidence/'
                                'campaign-node1-mirror/progress.json'),
        }
        result['combined_totals'] = {
            'attempted_plans': sum(p['attempted_plans'] for p in stages.values()),
            'jvm_attempts': sum(p['jvm_attempts'] for p in stages.values()),
            'invalid_setup_jvm_attempts': stage2.get('invalid_setup_jvm_attempts', 0),
            'strict_injections': sum(p['strict_injections'] for p in stages.values()),
            'effective_target_retaining_trials': sum(
                p['effective_target_retaining_trials'] for p in stages.values()),
            'target_exception_candidates': sum(
                p['target_exception_candidates'] for p in stages.values()),
            'cumulative_trial_seconds': round(
                sum(p['elapsed_seconds'] for p in stages.values()), 3),
            'coverage_note': 'Phase probe gains overlap; no union count is claimed.',
        }
    result['stages'] = stages
    tmp = RESULT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    tmp.replace(RESULT)
    print(json.dumps({key: result[key] for key in
                      ('status', 'fault_trials', 'strict_injections',
                       'target_after_fault', 'coverage_gain', 'elapsed_seconds')},
                     sort_keys=True))


if __name__ == '__main__':
    main()
