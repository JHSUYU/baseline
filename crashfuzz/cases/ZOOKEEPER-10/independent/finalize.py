#!/usr/bin/env python3
"""Publish the independent ZOOKEEPER-10 adjudication after the bounded run."""

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
    result.pop('source_inventory_only', None)
    result.pop('reason', None)
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
                  stopping_reason='80-trial budget reached; final 20 trials added no independent production coverage probe or stable I/O family' if not extension else '128-trial extended budget reached',
                  target_guard='ObserverMaster.removeProposedPacket(long):365 pkt.getZxid() != zxid',
                  target_exception='ObserverMaster.removeProposedPacket(long):371 java.lang.RuntimeException("Unexpected proposal packet on commit ack...")',
                  target_guard_source_line=365,
                  target_throw_source_line=371,
                  cluster_test='org.apache.zookeeper.test.ObserverMasterTest#testInOrderCommits(true)',
                  workload='original two-participant, one-observer JUnit with 20,002 asynchronous writes',
                  source_review='Follower.processPacket queues proposal zxids in ObserverMaster and then commits their zxids through the selected check. A selected throw means the queued proposal head is older than the processed commit. None of the observed checked-I/O failures caused this exact throw.',
                  evidence='README.md', trial_ledger='independent/trials.json',
                  trial_table='independent/trials.csv',
                  provenance='independent/provenance.json',
                  source_audit='independent/source-audit.md',
                  trace_manifest='independent/trace-manifest.json',
                  setup_audit='independent/setup-audit.tar.zst',
                  mapping_result='mapping-result.json',
                  limitations=['Results apply to the original testInOrderCommits(true) JUnit and checked-I/O fault model; they do not prove the selected throw unreachable in all workloads.',
                               'High-volume I/O and normal guard occurrences are sampled for queue construction; exact matched/applied faults, throw arms, and the first target guard after every applied fault are retained.',
                               'The transaction-log family uses the peer and logical txn-log key rather than an absolute file path.',
                               'Pre-FOLLOWERINFO sid=0 handler sites were excluded from eligible fault selection because they cannot identify a unique peer.'])
    manifest = {'case_id': 'ZOOKEEPER-10', 'methodology': result['methodology'],
                'remote_raw_runs': campaign.ROOT + '/runs', 'trials': []}
    for row in rows:
        local = campaign.HERE / 'trial-evidence' / row['id']
        manifest['trials'].append({'id': row['id'],
            'remote': campaign.ROOT + '/runs/' + row['id'],
            'files_sha256': {name: sha(local / name) for name in
                             ('events.tsv', 'coverage.tsv', 'lines.tsv', 'run.json')}})
    campaign.save_json(campaign.HERE / 'trace-manifest.json', manifest)
    campaign.save_json(campaign.RESULT, result)
    readme = '''# ZOOKEEPER-10: observer-master proposal/commit ordering

Apache ZooKeeper 3.8.7, `ObserverMaster.removeProposedPacket(long)` in
`zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ObserverMaster.java:359-375`.
The selected guard compares the queued proposal zxid with the commit zxid at
line 365. Only its `RuntimeException("Unexpected proposal packet on commit ack...")`
at line 371 is the target oracle.

The unchanged `ObserverMasterTest#testInOrderCommits(true)` JUnit creates two
participants and one observer, enables observer-master forwarding, and issues
20,002 asynchronous writes. The unique-id runner executes only the `true`
parameterized invocation with its normal JUnit lifecycle. The independent
healthy run passed in {healthy:.3f} seconds and executed the exact guard
{healthy_hits:,} times, all with matching zxids. The compact trace samples
{sampled_guard} normal guard events; its end summary retains the full count.
JaCoCo recorded {seedcov} production probes and the runtime recorder identified
{seedio} stable related I/O families. The classpath contains no GraphChecker or
static region skeleton. See [provenance.json](independent/provenance.json).

The graph-free CrashFuzz-style campaign tested {trials} checked-I/O fault
sequences (configured maximum {configured_max} faults, observed maximum {maxfault}).
{strict} matched and applied all planned fault selectors in order; {post} also
reached the same selected guard after the final fault. Their admitted feedback
added {cov} production JaCoCo probes and {io} stable I/O families.
{lost} fully injected sequences lost the target, and {ambiguous} selections
had ambiguous runtime identity; neither contributed feedback. No round
executed the exact selected throw after its final fault, so **no new bug is
confirmed at this check**.

The campaign stopped at its {budget}-trial {budget_kind} budget; its final 20
added {late_cov} admitted production probes and {late_io} stable I/O families.
Healthy plus trial JVM time was {elapsed:.3f} seconds; build, source review,
and idle time are excluded. Every round's elapsed time, exact selector plan,
strict match, target outcome, and coverage is in [trials.csv](independent/trials.csv)
and [trials.json](independent/trials.json). Raw logs and JaCoCo exec files are
in [raw-runs.tar.zst](independent/raw-runs.tar.zst), with per-run hashes in
[trace-manifest.json](independent/trace-manifest.json).
The archive omits each JUnit run's temporary embedded-cluster data directory;
the original complete directories remain on node2 for short-term audit.

The source review in [source-audit.md](independent/source-audit.md) traces
`Follower.processPacket()` into the proposal queue and selected commit check.
The runtime hook samples repeated I/O callsite occurrences for scheduling;
every exact fault match and the first target check after each fault is retained.
Transaction-log keys identify the peer and logical log, not a distinct absolute
file path. The original preflight and excluded instrumentor setup diagnostics
are preserved in [setup-audit.tar.zst](independent/setup-audit.tar.zst). The
initial unverified mapping is in [mapping-result.json](mapping-result.json).
This bounded result does not prove the selected throw unreachable elsewhere.
'''.format(healthy=seed['elapsed_seconds'], healthy_hits=result['healthy_target_guard_hits'],
           sampled_guard=result['healthy_target_guard_sampled_events'],
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
