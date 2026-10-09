#!/usr/bin/env python3
"""Publish the independent ZOOKEEPER-05 adjudication after the bounded run."""

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
    result.update(status='completed', bug_mark='none', new_bug_count=0,
                  methodology='coverage_io_no_graph_independent_asm_jacoco',
                  fault_trials=len(rows),
                  strict_trials=sum(row['strict_injection'] for row in rows),
                  strict_injections=sum(row['applied_injections'] for row in rows
                                        if row['strict_injection']),
                  post_fault_target_reach_trials=sum(row['target_guard_after_final_fault']
                                                     for row in rows),
                  target_exception_after_fault_trials=0,
                  identity_ambiguous_trials=ambiguous,
                  strict_but_target_lost_trials=sum(row['strict_injection']
                                                    and not row['target_guard_after_final_fault']
                                                    for row in rows),
                  admitted_coverage_gain=len(set(state['admitted_cov'])
                                             - campaign.coverage(campaign.HERE / 'healthy/coverage.tsv')),
                  admitted_new_io_families=len(set(state['admitted_families'])
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
                  target_guard='Follower.followLeader():98 newEpoch < self.getAcceptedEpoch()',
                  target_exception='Follower.followLeader():103 java.io.IOException("Error: Epoch of leader is lower")',
                  target_guard_source_line=98,
                  target_throw_source_line=103,
                  cluster_test='org.apache.zookeeper.test.QuorumRestartTest#testRollingRestart',
                  workload='original embedded three-peer rolling restart JUnit',
                  source_review='The version-0x10000 LEADERINFO handshake in Learner.registerWithLeader first rejects a lower epoch or persists a higher accepted epoch, so the selected downstream Follower check is redundant unless acceptedEpoch changes concurrently between the two checks. Checked I/O faults observed here did not trigger its exact throw.',
                  evidence='README.md', trial_ledger='independent/trials.json',
                  trial_table='independent/trials.csv',
                  provenance='independent/provenance.json',
                  source_audit='independent/source-audit.md',
                  trace_manifest='independent/trace-manifest.json',
                  limitations=['Results apply to the original three-peer rolling-restart JUnit and checked-I/O fault model; they do not prove the selected throw unreachable in all workloads.',
                               'The epoch file source key distinguishes peer and basename but does not record absolute paths.',
                               'Five pre-FOLLOWERINFO sid=0 selections had ambiguous handler identity and were excluded from strict/post-target/coverage feedback.'])
    manifest = {'case_id': 'ZOOKEEPER-05', 'methodology': result['methodology'],
                'remote_raw_runs': campaign.ROOT + '/runs', 'trials': []}
    for row in rows:
        local = campaign.HERE / 'trial-evidence' / row['id']
        manifest['trials'].append({'id': row['id'],
            'remote': campaign.ROOT + '/runs/' + row['id'],
            'files_sha256': {name: sha(local / name) for name in
                             ('events.tsv', 'coverage.tsv', 'lines.tsv', 'run.json')}})
    campaign.save_json(campaign.HERE / 'trace-manifest.json', manifest)
    campaign.save_json(campaign.RESULT, result)
    readme = '''# ZOOKEEPER-05: Follower leader-epoch check

Apache ZooKeeper 3.8.7, `Follower.followLeader()` in
`zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Follower.java:98-103`.
The selected guard is `newEpoch < self.getAcceptedEpoch()`; only its own
`IOException("Error: Epoch of leader is lower")` at line 103 is the target oracle.

The unchanged `QuorumRestartTest#testRollingRestart` JUnit creates three in-JVM
quorum peers and restarts them in turn. Its independent healthy run passed in
{healthy:.3f} seconds, reached the selected guard six times on the normal arm,
and yielded {seedcov} production JaCoCo probes and {seedio} eligible physical I/O
families. The agent and runner classpath contain no GraphChecker or static
region skeleton. See [provenance.json](independent/provenance.json).

The graph-free CrashFuzz-style campaign tested {trials} checked-I/O fault
sequences (maximum {maxfault} faults per sequence). {strict} matched and applied
all planned fault selectors in order; {post} also reached the same selected
guard after the final fault. Their admitted feedback added {cov} production
JaCoCo probes and {io} stable physical I/O families. {lost} fully injected
sequences lost the target, and {ambiguous} pre-FOLLOWERINFO handler selections
had ambiguous runtime identity; neither category contributed feedback. No
round executed the exact selected throw after the last fault, so **no new bug
is confirmed at this check**.

The campaign stopped at {budget} trials because the final 20 added no admitted
production coverage or stable I/O family. Healthy plus trial JVM time was
{elapsed:.3f} seconds; instrumentor build, source review, and idle time are
excluded. Every round's elapsed time, exact fault plan, strict match, target
outcome, and coverage is in [trials.csv](independent/trials.csv) and
[trials.json](independent/trials.json). Raw logs and JaCoCo exec files remain
on node2 under `/users/ZhenyuLi/zk05-independent/runs`; their compact trace
hashes are in [trace-manifest.json](independent/trace-manifest.json).

The source review in [source-audit.md](independent/source-audit.md) explains
why the version-`0x10000` `LEADERINFO` handshake normally checks or updates
`acceptedEpoch` before the selected `Follower` comparison. This is a bounded
result for the original JUnit and checked-I/O fault model, not a proof for all
concurrent executions. File family keys include the peer and epoch-file
basename, not an absolute path.

Historical GraphChecker trials remain in
[legacy-graph-result.json](legacy-graph-result.json) and
[legacy-graph-README.md](legacy-graph-README.md). Those 11 trials are excluded
from all independent-method counts.
'''.format(healthy=seed['elapsed_seconds'], seedcov=result['healthy_coverage_probes'],
           seedio=result['healthy_io_families'], trials=len(rows),
           maxfault=result['max_faults_actually_tested'], strict=result['strict_trials'],
           post=result['post_fault_target_reach_trials'], cov=result['admitted_coverage_gain'],
           io=result['admitted_new_io_families'], lost=result['strict_but_target_lost_trials'],
           ambiguous=ambiguous, budget=state['budget'], elapsed=elapsed_total)
    campaign.atomic(campaign.CASE / 'README.md', readme)
    print(json.dumps({key: result[key] for key in ('fault_trials', 'strict_trials',
        'post_fault_target_reach_trials', 'admitted_coverage_gain',
        'target_exception_after_fault_trials', 'elapsed_seconds')}, indent=2))


if __name__ == '__main__':
    main()
