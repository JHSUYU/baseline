#!/usr/bin/env python3
"""Publish the independent ZOOKEEPER-07 adjudication after the bounded run."""

from collections import Counter
import hashlib
import json
from pathlib import Path

import campaign


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    state = json.loads(campaign.STATE.read_text())
    rows = state['trials']
    if state['inflight'] or len(rows) < state['budget']:
        raise RuntimeError('campaign has not reached its bounded stopping point')
    if any(row['exact_target_throw_after_final_fault'] for row in rows):
        raise RuntimeError('target throw candidate requires individual source and differential audit')
    seed = json.loads((campaign.HERE / 'healthy/run.json').read_text())
    result = json.loads(campaign.RESULT.read_text())
    elapsed_trial = round(sum(row['elapsed_seconds'] for row in rows), 3)
    elapsed_total = round(seed['elapsed_seconds'] + elapsed_trial, 3)
    first_families = {'@@'.join(row['fault_plan'][0].split('@@')[:2]) for row in rows}
    planned_families = {'@@'.join(exact.split('@@')[:2])
                        for row in rows for exact in row['fault_plan']}
    ambiguous = sum(row['identity_ambiguous'] for row in rows)
    late = rows[-20:]
    extension = bool(state['extended'])
    result.update(status='quality_complete', bug_mark='none', new_bug_count=0,
                  methodology='coverage_io_no_graph_independent_asm_jacoco',
                  fault_trials=len(rows),
                  strict_trials=sum(row['strict_injection'] for row in rows),
                  fully_applied_trials=sum(row['strict_injection'] for row in rows),
                  strict_injections=sum(row['applied_injections'] for row in rows
                                        if row['strict_injection']),
                  post_fault_target_reach_trials=sum(row['target_guard_after_final_fault']
                                                     for row in rows),
                  target_after_fault=sum(row['target_guard_after_final_fault']
                                         for row in rows),
                  target_reached=True,
                  target_exception_after_fault_trials=0,
                  identity_ambiguous_trials=ambiguous,
                  strict_but_target_lost_trials=sum(row['strict_injection']
                                                    and not row['target_guard_after_final_fault']
                                                    for row in rows),
                  admitted_coverage_gain=len(set(state['admitted_cov'])
                                             - campaign.coverage(campaign.HERE / 'healthy/coverage.tsv')),
                  coverage_gain=len(set(state['admitted_cov'])
                                    - campaign.coverage(campaign.HERE / 'healthy/coverage.tsv')),
                  admitted_new_io_families=len(set(state['admitted_families'])
                                               - {campaign.family(e) for e in campaign.events(
                                                   campaign.HERE / 'healthy/events.tsv')
                                                  if campaign.eligible_io(e)}),
                  new_io_families=len(set(state['admitted_families'])
                                      - {campaign.family(e) for e in campaign.events(
                                          campaign.HERE / 'healthy/events.tsv')
                                         if campaign.eligible_io(e)}),
                  distinct_first_fault_families=len(first_families),
                  distinct_planned_fault_families=len(planned_families),
                  max_faults_actually_tested=max(row['fault_count'] for row in rows),
                  fault_count_distribution=dict(sorted(Counter(str(row['fault_count']) for row in rows).items())),
                  healthy_elapsed_seconds=seed['elapsed_seconds'],
                  trial_elapsed_seconds=elapsed_trial,
                  elapsed_seconds=elapsed_total,
                  elapsed_measurement='healthy and completed original-JUnit JVM durations; excludes source review, instrumentor build, and idle time',
                  baseline_trial_budget=state['budget'],
                  max_faults_per_sequence=state['max_faults'],
                  budget_extended=extension,
                  late_20_admitted_coverage_gain=sum(row['new_production_jacoco_probes'] for row in late),
                  late_20_admitted_io_family_gain=sum(row['new_stable_io_families'] for row in late),
                  stopping_reason='80-trial budget reached; final 20 trials added no independent production coverage probe or stable physical I/O family' if not extension else '128-trial extended budget reached',
                  target_guard='Learner.registerWithLeader():515 newEpoch != self.getAcceptedEpoch() after the greater-than arm',
                  target_exception='Learner.registerWithLeader():525 java.io.IOException("Leaders epoch, ... is less than accepted epoch, ...")',
                  target_guard_source_line=515,
                  target_throw_source_line=525,
                  cluster_test='org.apache.zookeeper.test.QuorumRestartTest#testRollingRestart',
                  workload='original embedded three-peer rolling restart JUnit',
                  source_review='Learner.registerWithLeader sends protocol version 0x10000 and compares the LEADERINFO epoch with its accepted epoch. A greater epoch is persisted, equality is accepted, and the lower remaining branch throws the selected IOException. The exception is a protective protocol rejection; none of the observed checked-I/O failures caused its exact throw.',
                  evidence='README.md', trial_ledger='independent/trials.json',
                  trial_table='independent/trials.csv',
                  provenance='independent/provenance.json',
                  source_audit='independent/source-audit.md',
                  trace_manifest='independent/trace-manifest.json',
                  limitations=['Results apply to the original three-peer rolling-restart JUnit and checked-I/O fault model; they do not prove the selected throw unreachable in all workloads.',
                               'The epoch file source key distinguishes peer and basename but does not record absolute paths.',
                               'Pre-FOLLOWERINFO sid=0 handler sites were excluded from eligible fault selection because they cannot identify a unique peer.'])
    manifest = {'case_id': 'ZOOKEEPER-07', 'methodology': result['methodology'],
                'remote_raw_runs': campaign.ROOT + '/runs', 'trials': []}
    for row in rows:
        local = campaign.HERE / 'trial-evidence' / row['id']
        manifest['trials'].append({'id': row['id'],
            'remote': campaign.ROOT + '/runs/' + row['id'],
            'files_sha256': {name: sha(local / name) for name in
                             ('events.tsv', 'coverage.tsv', 'lines.tsv', 'run.json')}})
    campaign.save_json(campaign.HERE / 'trace-manifest.json', manifest)
    campaign.save_json(campaign.RESULT, result)
    readme = '''# ZOOKEEPER-07: learner accepted-epoch check

Apache ZooKeeper 3.8.7, `Learner.registerWithLeader()` in
`zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java:515-525`.
The selected fatal arm follows the greater-than and equality comparisons of
`newEpoch` against `self.getAcceptedEpoch()`; only its own
`IOException("Leaders epoch, ... is less than accepted epoch, ...")` at line 525 is the target oracle.

The unchanged `QuorumRestartTest#testRollingRestart` JUnit creates three in-JVM
quorum peers and restarts them in turn. Its independent healthy run passed in
{healthy:.3f} seconds, reached the selected guard {healthy_hits} times on the normal arm,
and yielded {seedcov} production JaCoCo probes and {seedio} eligible physical I/O
families. The agent and runner classpath contain no GraphChecker or static
region skeleton. See [provenance.json](independent/provenance.json).

The graph-free CrashFuzz-style campaign tested {trials} checked-I/O fault
sequences (configured maximum {configured_max} faults, observed maximum {maxfault}). {strict} matched and applied
all planned fault selectors in order; {post} also reached the same selected
guard after the final fault. Their admitted feedback added {cov} production
JaCoCo probes and {io} stable physical I/O families. {lost} fully injected
sequences lost the target, and {ambiguous} pre-FOLLOWERINFO handler selections
had ambiguous runtime identity; neither category contributed feedback. No
round executed the exact selected throw after the last fault, so **no new bug
is confirmed at this check**.

The campaign stopped at its {budget}-trial {budget_kind} budget; the final 20 added
{late_cov} admitted production probes and {late_io} stable I/O families. Healthy plus trial JVM time was
{elapsed:.3f} seconds; instrumentor build, source review, and idle time are
excluded. Every round's elapsed time, exact fault plan, strict match, target
outcome, and coverage is in [trials.csv](independent/trials.csv) and
[trials.json](independent/trials.json). Raw logs and JaCoCo exec files remain
in [raw-runs.tar.zst](independent/raw-runs.tar.zst), with per-run hashes in
[trace-manifest.json](independent/trace-manifest.json).

The source review in [source-audit.md](independent/source-audit.md) traces
the version-`0x10000` `LEADERINFO` response and the accepted-epoch comparisons.
This is a bounded result for the original JUnit and checked-I/O fault model,
not a proof for all recovery executions. File family keys include the peer
and epoch-file basename, not an absolute path.

Historical GraphChecker trials remain in
[legacy-graph-result.json](legacy-graph-result.json) and
[legacy-graph-README.md](legacy-graph-README.md). Those 3 trials are excluded
from all independent-method counts.
'''.format(healthy=seed['elapsed_seconds'], healthy_hits=result['healthy_target_guard_hits'],
           seedcov=result['healthy_coverage_probes'],
           seedio=result['healthy_io_families'], trials=len(rows),
           maxfault=result['max_faults_actually_tested'], configured_max=state['max_faults'],
           strict=result['strict_trials'],
           post=result['post_fault_target_reach_trials'], cov=result['admitted_coverage_gain'],
           io=result['admitted_new_io_families'], lost=result['strict_but_target_lost_trials'],
           ambiguous=ambiguous, budget=state['budget'],
           budget_kind='extended' if extension else 'initial',
           late_cov=result['late_20_admitted_coverage_gain'],
           late_io=result['late_20_admitted_io_family_gain'], elapsed=elapsed_total)
    campaign.atomic(campaign.CASE / 'README.md', readme)
    print(json.dumps({key: result[key] for key in ('fault_trials', 'strict_trials',
        'post_fault_target_reach_trials', 'admitted_coverage_gain',
        'target_exception_after_fault_trials', 'elapsed_seconds')}, indent=2))


if __name__ == '__main__':
    main()
