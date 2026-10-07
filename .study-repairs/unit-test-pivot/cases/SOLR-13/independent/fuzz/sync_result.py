#!/usr/bin/env python3
"""Project authoritative SOLR-13 campaign checkpoint into the shared table row."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRESS = HERE / 'evidence/campaign/progress.json'
RESULT = HERE.parents[1] / 'result.json'


def main() -> None:
    progress = json.loads(PROGRESS.read_text())
    result = json.loads(RESULT.read_text())
    result.update({
        'status': 'running' if progress['status'] == 'running'
                  else 'candidate_target_exception'
                  if progress['status'] == 'candidate_target_exception'
                  else progress['status'],
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
    tmp = RESULT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    tmp.replace(RESULT)
    print(json.dumps({key: result[key] for key in
                      ('status', 'fault_trials', 'strict_injections',
                       'target_after_fault', 'coverage_gain', 'elapsed_seconds')},
                     sort_keys=True))


if __name__ == '__main__':
    main()
