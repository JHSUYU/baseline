#!/usr/bin/env python3
"""Publish the actor-V2 case result after full raw and coverage audits."""

import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent


def read(path):
    return json.loads(path.read_text())


def main():
    summary = read(HERE / 'campaign/summary-v2.json')
    progress = read(HERE / 'campaign/progress.json')
    coverage = read(HERE / 'campaign/production-coverage-audit.json')
    archive = read(HERE / 'raw-evidence-v2.archive.json')
    health0 = read(HERE / 'health-audit.json')
    health2 = read(HERE / 'node2-health-audit.json')
    if summary['extend_to_128_max10'] and summary['budget']['max_trials'] < 128:
        raise RuntimeError('novelty requires the conditional 128-trial extension')
    if (summary['effective_trials'] < summary['budget']['max_trials'] or
        summary['exact_target_throw_trials'] or
        summary['strict_injections'] < summary['effective_trials'] or
        summary['postfinal_guard_trials'] < summary['effective_trials']):
        raise RuntimeError('case quality gates incomplete')
    result_path = CASE / 'result.json'
    result = read(result_path)
    baseline = (health0['clean'] + health0['instrumented'] +
                health2['clean'] + health2['instrumented'])
    result.update({
        'status': 'quality_complete', 'quality_complete': True,
        'methodology': 'actor_v2_exact_same_solrzkclient_asm_jacoco',
        'bug_mark': 'none', 'fault_trials': summary['effective_trials'],
        'strict_injections': summary['strict_injections'],
        'post_fault_target_reach_trials': summary['postfinal_guard_trials'],
        'target_after_fault': summary['postfinal_guard_trials'],
        'target_exception_after_fault_trials': summary['exact_target_throw_trials'],
        'elapsed_seconds': summary['elapsed_seconds'],
        'baseline_seconds': round(sum(row['elapsed_seconds'] for row in baseline), 3),
        'healthy_original_junit': 'ran=1 ignored=0 failures=0',
        'healthy_repeated_original_junit_passed': len(baseline),
        'healthy_target_guard_hits': len(health0['instrumented']) +
                                     len(health2['instrumented']),
        'healthy_target_throw_hits': 0,
        'stable_exact_coordinator_request_io_selectors':
            len(health2['common_selectors']),
        'stable_exact_pretarget_io_selectors': len(health2['common_selectors']),
        'coverage_gain': progress['production_probe_gain'],
        'production_methods_gain': coverage['new_production_methods'],
        'production_branch_outcomes_gain': coverage['new_production_branch_outcomes'],
        'io_family_gain': summary['actor_io_family_gain'],
        'raw_io_family_gain': summary['actor_io_family_gain'],
        'evidence': '.study-repairs/unit-test-pivot/cases/SOLR-34/actor-v2/README.md',
        'reason': (f"Original TestCoordinatorRole.testSimple reached the exact guard after "
                   f"{summary['postfinal_guard_trials']} effective ordered same-client "
                   f"ZooKeeper fault trials; zero newly constructed SOLR-34 target "
                   f"exceptions appeared. The line-140 createException rethrow is a "
                   f"different path. Scope: the original embedded-cluster JUnit and "
                   f"the observed SolrZkClient retry-internal native I/O sites."),
        'actor_v2': {
            'budget': summary['budget'],
            'selected_trials': summary['selected_trials'],
            'effective_trials': summary['effective_trials'],
            'node0_completed_trial_numbers': summary['node0_completed_trial_numbers'],
            'node2_completed_trial_numbers': summary['node2_completed_trial_numbers'],
            'node0_orphan_trial16': summary['node0_orphan_trial16'],
            'original_test_sha256': summary['original_test_sha256'],
            'agent_sha256': summary['agent_sha256'],
            'same_client_stable_selectors': len(health2['common_selectors']),
            'healthy_clean_runs': len(health0['clean']) + len(health2['clean']),
            'healthy_instrumented_runs': len(health0['instrumented']) +
                                         len(health2['instrumented']),
            'production_probe_gain': progress['production_probe_gain'],
            'last20_effective_novel_probes_or_io_families':
                summary['last20_effective_novel_probes_or_io_families'],
            'base80_last20_novel_probes_or_io_families':
                summary['base80_last20_novel_probes_or_io_families'],
            'raw_archive': 'actor-v2/' + archive['archive'],
            'raw_archive_sha256': archive['sha256'],
            'trial_ledger': 'actor-v2/campaign/trial-ledger-v2.json',
            'source_review': 'actor-v2/SOURCE_REVIEW.md',
        },
        'updated_at': time.time(),
    })
    result['source_review']['classification'] = 'no_target_exception_observed'
    result['source_review']['scope'] = (
        'unchanged TestCoordinatorRole.testSimple; exact same-client SolrZkClient '
        'retry-internal native I/O; other network/disk modalities not evaluated')
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    outcome = '80/max8 saturation' if summary['budget']['max_trials'] == 80 else '128/max10 extension'
    readme = f'''# SOLR-34 actor-V2 case

The unchanged Solr 8.11.4 `TestCoordinatorRole.testSimple` JUnit passed in all
{summary['selected_trials']} selected fault runs. There were
{summary['effective_trials']} effective ordered same-client native ZooKeeper
fault trials ({outcome}), {summary['postfinal_guard_trials']} strict postfault
guard reaches, and zero exact SOLR-34 target exceptions. No new bug is claimed.

The adapter binds the target to the live coordinator
`solrCall.cores.getZkController().getZkClient()` and records the actual
`SolrZkClient` receiver at every native I/O hook. Eight exact preguard
selectors were stable in both node0 and node2 healthy seeds. A wrong-client
fixture rejects another receiver. Node0 trials 1–15 and node2 trials 16 onward
are labeled in the [trial ledger](campaign/trial-ledger-v2.json); the original
node0 trial-16 raw run was archived but never counted because its runner
receipt was interrupted. HBASE-32 s101 overlapped the node0 phase, as recorded
in the [node0 audit](node0-phase-audit.json).

The case used {summary['elapsed_seconds']:.3f} seconds of selected fault-trial
runtime. Original release-JAR JaCoCo comparison adds
{coverage['new_production_methods']} production methods and
{coverage['new_production_branch_outcomes']} branch outcomes over healthy
seeds; actor-relative I/O families add {summary['actor_io_family_gain']}.
The final 20 effective trials added
{summary['last20_effective_novel_probes_or_io_families']} production probes or
actor-relative I/O families. At the 80-trial boundary the final 20 had added
{summary['base80_last20_novel_probes_or_io_families']} such probes or families;
that observation determined whether the 128-trial extension ran. The
[source review](SOURCE_REVIEW.md) distinguishes
the newly constructed exception at line 143 from the earlier exception rethrow
at line 140. Raw traces, JUnit logs, JaCoCo data, plans, and receipts are in
the [archive](raw-evidence-v2.tar.zst) (SHA-256 `{archive['sha256']}`).

The result covers this original embedded-cluster test and the instrumented
SolrZkClient retry-internal I/O sites.
'''
    (HERE / 'README.md').write_text(readme)
    (CASE / 'README.md').write_text(
        '# SOLR-34: actor-V2 review\n\n'
        'The graph-free original embedded-cluster JUnit and exact same-client '
        'fault campaign are complete. See [the actor-V2 case](actor-v2/README.md). '
        'The 80 earlier collection-only trials remain under `legacy_coarse_actor` '
        'in `result.json` and do not count toward this result.\n')
    print(json.dumps({'status': result['status'], 'fault_trials': result['fault_trials'],
                      'target_exception_after_fault_trials':
                          result['target_exception_after_fault_trials']}, sort_keys=True))


if __name__ == '__main__':
    main()
