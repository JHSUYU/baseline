# HBASE-32: primary-flush exception check

Selected HBase 2.6.6 site:
`RegionReplicaFlushHandler.triggerFlushInPrimaryRegion(HRegion)`, B7,
`RegionReplicaFlushHandler.java:136`. A secondary region handler asks the
primary to flush through `FlushRegionCallable`, which calls the primary's
`flushRegion` RPC. If the retried call throws `IOException`, this site returns
for `TableNotFoundException` or a disabled table; otherwise it rethrows the
exception. `RegionReplicaFlushHandler.handleException` then aborts the region
server for ordinary `IOException`.

The mapped unchanged original JUnit is
`TestRegionReplicaFailover.testSecondaryRegionKill`. Its `@BeforeEach` starts a
three-region-server MiniHBaseCluster and creates a table with three replicas.
The test loads rows, aborts the server hosting replica 1, waits for secondary
reads after reassignment, verifies replica 2, and starts a replacement server.
This sequence can invoke the secondary's primary-flush request during reopen.

## Runtime identity and target evidence

The unchanged original test runs a three-region-server MiniHBaseCluster on
node1. The healthy JUnit passed (`1/1`) in 55.35 seconds. Its trace contains
three `triggerFlushInPrimaryRegion` invocations and three observed
`FlushRegionCallable.call:81` RPC sends; JaCoCo measured zero instructions on
source line 136. Different cluster runs allocate different numeric region IDs.
The agent therefore selects an I/O point by stable table/start key, replica
ID, target invocation ordinal, and RPC ordinal. Every trace also records the
full raw primary and secondary region names. A planned fault is applied only
when the live RPC's raw primary name equals the active target invocation's raw
primary name.

The first calibrated exact fault on replica 1's second target invocation
injected a `DoNotRetryIOException` immediately before the real `flushRegion`
RPC. The same raw primary region appeared in `FAULT_APPLIED` and the
subsequent line-136 `TARGET_B7_RETHROW`. The test passed (`1/1`) after HBase
aborted and reassigned the affected region server; JaCoCo's merged production
coverage grew by seven branches, and source line 136 gained two executed
instructions. Source `handleException` explicitly aborts the server for this
ordinary exception, so this outcome is an expected control path, not a new
bug. A separate `TableNotFoundException` calibration reached the line-130
guard for the same raw region without reaching B7, then the JUnit failed with
`OperationTimeoutExceededException` after 180.23 seconds. It fabricated a
table-missing response while the table still existed; this violates the
response's state precondition, so the calibration is excluded from the main
fault queue and is not a bug claim.

The first resumable coverage-guided pilot used `work/campaign.py` with the
original `testSecondaryRegionKill` JUnit. It used case-local ASM probes,
JaCoCo production coverage, exact ordered fault plans, and atomic per-trial
checkpoints. It completed 24 distinct attempts: 23 fully applied, three
retained the target after the last fault, and one exhausted all three region
servers. `result-pilot.json`, `work/checkpoint.json`, and
`evidence/hbase32-pilot-raw.tar.gz` preserve this pilot independently. Its
short 24-attempt cap was used only to settle the final inflight trial before
switching workloads; it was not the case's final fuzz budget.

The second campaign plan injected two no-retry exceptions during successive
recoveries. The original JUnit had already aborted RS
`ms1105.utah.cloudlab.us,37551,1791336903029`; the two target B7 outcomes
caused `handleException` to abort the other two distinct RSs
(`...,33921,1791336902566` and `...,34251,1791336903366`). The master then
reported no region server available. The original attempt reached the 360s
timeout (370.96s including shutdown). An independent replay applied both
faults, reached both target B7 outcomes, aborted three *different* RSs, again
reported no region server available, and exited by timeout (371.07s). The
second run's RS IDs differed because it had a fresh cluster. This sequence
exhausts all three RSs and is invalid under the workload's recovery
precondition. It is excluded from the effective denominator and bug candidates,
and not expanded in the queue. Its fault and target-hit counts remain visible.
`evidence/r002_invalid_replay.json` records both runs' source-derived symptom
and artifact hashes.

Trials r003–r005 injected retryable faults but lost the chosen exception guard
after the last fault. Their attempts, JUnit results, and JaCoCo files remain
archived, but their coverage does not guide later mutation and they do not
count in the effective target-check budget. An atomic checkpoint migration
removed their descendants and coverage data without rerunning these trials;
`evidence/target_loss_migration.json` records the before/after counts and
independent ancestry assertions.

## Reachability audit and workload pivot

At 11 pilot attempts, only two trials retained the target after the last fault.
The probe's healthy trace has three distinct flush-RPC identities: replica 1
at target invocations 1 and 2, and replica 2 at invocation 1. It does not
record broader RPC or file I/O; the campaign cannot claim coverage of such
sites. The first B7 trial's branch novelty was promoting its two-fault
descendants ahead of untried single-fault identities. The priority score now
favors novel single-fault identities and replica/invocation diversity, with
bounded coverage and aging rewards for legal depth. This ordering was applied
after r014's complete raw log and exit status were written. The controller
resumed from the inflight marker, settled r014 without rerunning it, and chose
the previously untried replica-2/target-1 RPC for r015. Matching and effective
trial accounting require the same complete raw primary region identity at the
fault and the later target guard.

I evaluated other unchanged methods of the same cluster test class. Two
fault-free runs of `testSecondaryRegionKillWhilePrimaryIsAcceptingWrites`
passed in 64.51 and 63.82 seconds. Despite concurrent puts and an admin
flush, the current probe saw only three common stable flush-RPC identities and
three target invocations, so it did not materially expand the fault space.
Two fault-free runs of `testLotsOfRegionReplicas` passed in 60.13 and 60.24
seconds (about 2 GiB peak RSS each). This method creates 60 additional
regions with ten replicas. Both runs entered the target 542 times, across 61
stable table/start-key region identities. They observed 555 and 560
flush-RPC selectors, with 543 selectors common across runs; the extra
selectors came from nondeterministic RPC retries. Every observed flush RPC
matched the active target's full raw primary region in its own run. The probe
still does not intercept the workload's broader file I/O or other RPC families.

The separate main campaign now runs the unchanged
`TestRegionReplicaFailover.testLotsOfRegionReplicas` method in node1 tmux
`hbase32-lots-fuzz`. `work-lots/campaign.py` has its own healthy seed,
JaCoCo union, queue, checkpoint, and trial logs. The full budget is 80
effective trials, 240 attempts, and at most eight injected events per plan.
The initial healthy trace generated 2,220 distinct one-fault plans. An
effective trial requires every planned exception to be applied and the last
fault to reach the same *full raw primary region, replica ID, and target
invocation ordinal* at the source exception guard. Trials that lose the
target or exhaust the three-server cluster keep their raw evidence but do not
contribute coverage novelty or descendants. The first faulted trial applied
one `DoNotRetryIOException` to a selector present in the healthy seed,
reached that exact actor's guard and B7 rethrow, and passed JUnit in 57.01
seconds after the expected server abort. `result.json` and the 104-row
checklist reflect the latest synchronized main-campaign checkpoint.

The main campaign initially generated every target-linked child of an
effective trial. After two accepted trials, the queue held 6,742 plans. At
the next complete trial boundary, a versioned scheduling change preserved the
entire existing queue and JaCoCo union, then limited *future* children to 24
distinct selectors per parent. It samples newly exposed I/O identities first,
uses an independently derived deterministic seed for each prefix, and reserves
one in ten selections for valid multi-fault descendants. The checkpoint's
`policy_changes` entry records the migration counts and seed (32).

Main trials r003 and r011 each injected one no-retry flush-RPC exception,
reached the same full raw primary region's guard and B7, and aborted one
region server carrying `hbase:meta`. The original JUnit stalled in
`Admin.createTable` and hit the 360-second test timeout, with 197/600 and
72/600 assignment children complete, respectively. In both runs,
`RegionServerTracker` waited for `AssignmentManager.submitServerCrash`'s
server write lock until shutdown; the first crash procedure was scheduled
only after shutdown began. `Thread.print -l` identifies two region-state
lock holders in r011, but does not identify the shared server read-lock
owners or prove a closed deadlock. The two other region-server aborts in each
run followed timeout teardown and do not count as pre-timeout cluster
exhaustion. The independent source review is in
`independent/r003-timeout-source-review.md`.

Both exact saved plans were replayed in fresh, isolated node2 clusters with
the same agent and HBase JAR checksums and a 600-second cap. r003 passed the
unchanged JUnit in 77.58 seconds; r011 passed in 76.97 seconds. Both replays
fully applied their plan, reached the same actor's B7, aborted only one
region server, scheduled its crash procedure promptly, and completed all
600 assignment children. These are **unreproduced, scheduling-sensitive
timeout candidates, not confirmed new bugs**. Original logs, JaCoCo data,
thread dumps, replay logs, and checksums are archived in
`evidence/hbase32-r003-candidate.tar.gz`,
`evidence/hbase32-r003-node2-exact-replay.tar.gz`,
`evidence/hbase32-r011-original-node1.tar.gz`, and
`evidence/hbase32-r011-node2-exact-replay.tar.gz`; the two replay verdict
JSON files record their classification. The checklist-facing `bug_mark` is
`none` for these reviewed candidates. Any later unresolved JUnit failure or
timeout remains `candidate_review` until replay and source review.

The first 18 lots trials all selected `DoNotRetryIOException`. A clean
checkpoint migration added a four-kind exception rotation, keeping the
existing I/O and code-coverage scores and the one-in-ten legal multi-fault
selection. Calibration trials r019-r034 found that five no-retry trials all
retained the target and exposed 1,254 new normalized I/O selectors in total.
Four ordinary `IOException`, three socket-timeout, and four EOF trials were
fully injected but none retained the target after its final fault. HBase's
`RpcRetryingCallerImpl.callWithRetries` can absorb these one-shot retryable
exceptions before the source guard observes them. Those target-lost trials
remain raw evidence and do not alter coverage or produce children.

The current selection policy adjusts exception-kind weights after each
trial using exact target retention and **admitted** code/I/O novelty, with a
5% exploration floor for every kind. Initial weights at the r034 checkpoint
were 0.655 no-retry, 0.11 ordinary I/O, 0.125 socket timeout, and 0.11 EOF;
see `evidence/v3-kind-calibration.json` and
`evidence/policy-v4-migration.json`. Within a chosen kind, the prior unique
I/O, recovery, coverage, and waiting-time priority scores still apply. The
main controller runs in node1 tmux `hbase32-lots-fuzz`; node0 tmux
`hbase32-result-mirror` copies only this case's atomic `result.json` every
30 seconds and atomically refreshes the 104-row checklist when it changes.

At the 80-effective checkpoint, policy v5 reconstructs a global union of
target-related I/O selectors from the healthy trace and only accepted
postfault trials, in execution order. Earlier `new_related_io_selectors`
values were differences from the healthy trace for each individual run, so
they could count the same recovery selector in many trials. The historical
field remains for audit; `global_new_related_io_selectors` records genuinely
new selectors against all prior accepted runs. Exception-kind and child
selection use the global count after migration, alongside JaCoCo feedback.
The migration keeps the trial list, pending plans, and coverage union intact;
its before/after hashes and last-eight-effective novelty decide whether the
conditional 128-effective/10-fault extension applies.

## Independent upstream I/O phase

Source and passive MiniCluster calibration found two additional target-related
I/O families: RegionServer-to-Master OPENED reports before a secondary enters
the target, and primary WAL append/sync calls reached by its flush RPC. The
unchanged `testLotsOfRegionReplicas` JUnit passed four isolated healthy runs.
The final seed ties 540 Master reports and 341 append plus 341 sync events to
exact runtime identities; asynchronous metadata scans without a secondary
actor stay out of the fault queue. See `evidence/upstream-passive-findings.md`
for the raw log archives, actor-tag validation, and scope limits.

`work-upstream/campaign.py` runs separately in node0 tmux
`hbase32-upstream-fuzz`. It has its own healthy seed, queue, atomic checkpoint,
nine-class JaCoCo union, and 80-effective/8-fault initial budget. A same-actor
Master retry or WAL retry can be a seed, but only a complete fault sequence
followed by that actor's B7 guard evaluation enters its effective denominator.
The exact Master pilot and one WAL append pilot passed the original JUnit;
neither reached B7. A prior WAL pilot did not inject because a global marker
ordinal changed under concurrency. The agent now counts markers within the
exact secondary actor. This phase is distinct from the client flush-RPC
campaign summarized above.

Main trial r058, a one-fault exact B7 timeout on node1, passed an identical
clean 600-second replay on node0 in 68.07 seconds with all 600 assignment
children complete. It remains an unreproduced timeout candidate, not a
confirmed new bug; `evidence/r058-replay-findings.md` has the raw archive and
checksums.

Main trial r066 also timed out after one exact no-retry flush RPC exception
and the same target B7. Its isolated node2 same-plan replay passed the
unchanged JUnit in 55.82 seconds, completed 600/600 assignment children, and
promptly scheduled recovery for its one aborted RegionServer. The original
360-second stall is an unreproduced scheduling-sensitive candidate, not a
confirmed new bug. `evidence/r066-replay-verdict.json` and the two r066 raw
archives contain the checksums and full receipts.

Main trial r123 was a separate timeout candidate. Its one selected
replica-2 flush RPC received a precise `DoNotRetryIOException`, and the same
raw primary region and actor reached the B7 rethrow. One RegionServer aborted;
the original JUnit did not finish by the 360-second cap. The runtime including
shutdown was 413.76 seconds. At 180 seconds and again near the cap,
`Thread.print -l` captured the Master waiting to submit a ServerCrashProcedure
while assignment workers were retrying metadata writes. This is an observed
stall, not a confirmed deadlock or new bug. A clean same-plan 600-second
replay with competing node1 JUnit campaigns paused injected the same fault,
reached the same actor's B7 rethrow, and passed the unchanged JUnit in
79.72 seconds. The Master promptly scheduled the ServerCrashProcedure,
and all 600 table-assignment children succeeded. The original timeout is
classified as an **unreproduced, scheduling-sensitive candidate**. The
original and replay logs, JaCoCo files, thread dumps, and checksums are in
`evidence/hbase32-r123-original-node1.tar.gz`,
`evidence/hbase32-r123-node1-exact-replay.tar.gz`, and
`evidence/r123-replay-verdict.json`.

Policy v6 excludes an unresolved exact timeout or JUnit failure from the
effective denominator, JaCoCo/I/O feedback unions, and mutation descendants
until replay and source review settle its status. The original v5 controller
first checkpointed r123 as effective; the atomic pending-review migration
retained its plan, raw log, JaCoCo file, and the untouched r124 in-flight plan
while correcting the r123 effective count from 89 to 88. Pre/post evidence is
in `work-lots/evidence-r123-pending-pre.json` and
`work-lots/evidence-r123-pending-post.json`. The reviewed timeout remains
excluded from coverage and I/O feedback; `evidence/r123-review-checkpoint-audit.json`
shows that review settlement kept 123 attempts, 88 effective trials, the
14,205-entry queue, and r124's in-flight plan unchanged. The main controller
is paused at this complete checkpoint while node1 is used by other campaigns.

In the independent upstream phase, s078 applied a Master OPENED report
exception and then a client flush RPC exception to the same raw region and
replica-1 actor. The selected B7 rethrow occurred after both faults, but the
unchanged JUnit timed out after 402.76 seconds including shutdown. This is a
candidate awaiting an isolated same-plan replay, not a confirmed new bug.
The full original trace, exit receipt, JaCoCo file, and v8 migration audit
are archived in `evidence/hbase32-s078-original-node0.tar.gz`; the exact
actor receipt is `evidence/s078-candidate-receipt.json`. The v8 checkpoint
excludes this unreviewed run from the supplemental effective denominator and
feedback. The supplemental controller continues under an 80-effective,
384-attempt initial budget and pauses before node0 drops below 2.2 GiB free.
