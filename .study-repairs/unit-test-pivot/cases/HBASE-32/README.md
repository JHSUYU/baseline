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
then resumed from r124 without repeating an earlier trial.

Main trial r136 was a separate exact single-fault timeout during overlapping
node1 JUnit campaigns. The selected replica-4 flush RPC exception and same
raw-region B7 rethrow occurred, but the original JUnit had completed only
149/600 table-assignment children at the 360-second cap. Its pre-timeout
`Thread.print -l` samples show a delayed ServerCrashProcedure submission;
they do not establish a closed deadlock. Policy v6 checkpointed r136 as
**not effective** and admitted none of its JaCoCo/I/O feedback or children.
With the other node1 JUnit campaigns paused, an isolated exact 600-second
replay reached the same actor's B7 rethrow and passed the unchanged JUnit in
57.25 seconds: 600/600 assignment children succeeded, one RegionServer
aborted, and the Master promptly scheduled its crash procedure. The original
timeout is an **unreproduced, scheduling-sensitive candidate**, not a
confirmed new bug. `evidence/r136-replay-verdict.json`,
`evidence/r136-checkpoint-exclusion.json`, and
`evidence/r136-original-and-clean-replay-node1.tar.gz` preserve the plan,
raw logs, JaCoCo data, thread dumps, and SHA checks. The controller resumed
its saved r137 plan after the replay; the r136 trial remains excluded from
the effective denominator and feedback.

Main trial r159 was another exact single-fault timeout: the replica-6 flush
RPC exception and B7 rethrow matched the same raw primary region, while the
original JUnit completed only 163/600 assignment children before its
360-second cap. Three live `Thread.print -l` dumps and the original log were
preserved. The controller excluded this run from effective, coverage, I/O,
and descendant counts before starting r160. With other node1 JUnit jobs
paused, a clean same-plan replay used the same agent and HBase JAR and passed
the unchanged JUnit in 56.59 seconds; its exact B7 occurred, one region
server aborted, and all 600 children completed. This is an
**unreproduced timeout candidate**, not a confirmed new bug. The raw bundle,
SHA checks, review verdict, and checkpoint exclusion are in
`evidence/r159-original-and-clean-replay-node1.tar.gz`,
`evidence/r159-replay-verdict.json`, and
`evidence/r159-checkpoint-exclusion.json`. The saved r160 plan resumed without
rerunning r159.

At the first apparent 128-effective endpoint (r177), an independent
checkpoint audit found five earlier, already reviewed timeout runs—r003,
r011, r058, r066, and r075—that the pre-v6 controller had still counted as
effective and had admitted into JaCoCo/I/O feedback. Each original JUnit
exited 124, and each exact isolated replay passed. At a complete checkpoint,
`work-lots/migrate_reviewed_timeouts.py` preserved the original state and
raw evidence, excluded those five runs, recomputed both feedback unions,
and corrected 177 trials from 128 to 123 valid effective trials. No
completed or queued descendant used those five plans; the queue and seen
plan hashes remained identical. The before/after receipts and compressed
original checkpoint are in `work-lots/evidence-reviewed-timeouts-*`. The
main controller resumed at r178 to fill the remaining five valid trials,
without repeating any prior plan.

The main phase ended at r185 with 185 distinct attempted plans, 182 strictly
applied plans, and 128 valid target-retaining plans. All 128 valid plans ran
the unchanged JUnit successfully. The terminal audit re-read every plan,
raw log, exit receipt, and JaCoCo file, recomputed the accepted I/O selector
union (3,237 selectors) and production coverage (20 branches, 11 methods,
61 lines across the two instrumented production classes), and matched both
unions to the checkpoint. The target B7 line 136 had two covered
instructions. All eight timeout candidates are reviewed and excluded from
the valid denominator and feedback; none is a confirmed new bug. The
machine-readable receipt is `work-lots/evidence-main-terminal-audit.json`.
The largest executed plan had two faults, despite the configured maximum of
ten; the configured maximum is not evidence of deeper coverage. The separately counted upstream supplemental phase is paused at s203
with 203 attempts and 51 valid plans, pending source review of an isolated
reproduced timeout.

In the independent upstream phase, s078 applied a Master OPENED report
exception and then a client flush RPC exception to the same raw region and
replica-1 actor. The selected B7 rethrow occurred after both faults, but the
unchanged JUnit timed out after 402.76 seconds including shutdown. This is a
candidate that was later replayed in an isolated node0 slot.
The full original trace, exit receipt, JaCoCo file, and v8 migration audit
are archived in `evidence/hbase32-s078-original-node0.tar.gz`; the exact
actor receipt is `evidence/s078-candidate-receipt.json`. The v8 checkpoint
excludes this run from the supplemental effective denominator and
feedback. The supplemental controller continues under an 80-effective,
384-attempt initial budget and pauses before node0 drops below 2.2 GiB free.
Its later s101 Master-to-client-RPC sequence also reached B7 but timed out
while two unrelated Solr JUnit clusters overlapped on node0. s101 is separately
quarantined from effective and feedback counts;
`evidence/s101-candidate-receipt.json` records exact actor and raw
checks. Checkpoint version 9 replenishes mixed-plan parents from distinct
observed Master I/O identities when mixed terminal plans run out, while
preserving coverage/I/O priority and periodic deeper-plan exploration.
Isolated 600-second same-plan replays of s101 and s078 each applied both
faults, reached the same actor's B7 rethrow, and passed the unchanged JUnit
with 600/600 assignment children in 59.77 and 77.99 seconds, respectively.
Their original timeouts are **unreproduced candidates**, not confirmed new
bugs. Per-trial raw bundles, SHA checks, verdicts, and checkpoint exclusion
receipts are in `evidence/s101-*` and `evidence/s078-*`. Neither source
trial was imported into the effective denominator or feedback.
Supplemental trial s113 applied a distinct same-actor Master OPENED and
client flush RPC no-retry sequence to replica 9. Both faults and the later B7
rethrow occurred, but the original JUnit timed out with 111/600 assignment
children complete. It overlapped a Solr JUnit late in the run. An isolated
same-plan 600-second replay applied both faults, reached B7, and passed the
unchanged JUnit in 78.62 seconds with 600/600 children and one region server
abort. s113 is an **unreproduced timeout candidate**, not a confirmed new
bug. The original and replay raw receipts, SHA checks, and exclusion proof
are in `evidence/s113-original-and-clean-replay-node0.tar.gz`,
`evidence/s113-replay-verdict.json`, and
`evidence/s113-checkpoint-exclusion.json`. It remains excluded from effective,
coverage, and descendant counts. The supplemental reporting review map marks
s078, s101, and s113 reviewed; s203 is a separate pending candidate.
To protect node0 disk space, 25 completed noncandidate raw logs from
s081-s100 and s102-s106 were copied to the HBASE-32 archive on node1 and
verified byte-for-byte by SHA-256 before their node0 copies were removed.
The pre-transfer manifest, node1 verification, and post-transfer receipts
are in `work-upstream/relocate-s081-s106-logs-*.json`. The local JaCoCo and
exit receipts, plus both s078 and s101 candidate raw logs, remain on node0.
Eight completed healthy, pilot, and meta-observation logs were archived the
same way; `work-upstream/relocate-calibration-*.json` records the byte counts
and hashes. Their JaCoCo files remain local.

## Supplemental s203 exact timeout candidate (interim)

The unchanged original JUnit `TestRegionReplicaFailover#testLotsOfRegionReplicas`
received two exact `DoNotRetryIOException` faults for the same raw primary
region and replica 7: a Master OPENED report, then the client flush RPC. The
selected `RegionReplicaFlushHandler.triggerFlushInPrimaryRegion` B7 rethrow
occurred after the second fault. The original trial timed out in 405.83 seconds
including shutdown. Its isolated, identical-plan replay timed out again at
the 600-second limit (641.94 seconds including shutdown). The replay applied
both faults, reached the same actor's B7 once, and left the original JUnit
incomplete with 170/600 table-2 assignment children successful. Only one
region server aborted before timeout cleanup. The server-expiration handler
started at 09:50:30 UTC but did not schedule the first ServerCrashProcedure
until 10:00:09 UTC, after the 09:59:43 shutdown hook began. Five `Thread.print
-l` dumps retain the wait stacks before cleanup.

This is a **reproduced exact timeout candidate**, with `new_bug=false` until
source and lock-owner review establish its mechanism and novelty. s203 remains
excluded from the effective denominator, JaCoCo/I/O feedback, and descendants;
the fuzz controller is stopped at its complete s203 checkpoint. The original
7 files and replay 11 files were each mirrored to node1 with independent
per-file SHA-256 checks. `work-upstream/evidence-s203-candidate-receipt.json`,
`work-upstream/evidence-s203-original-manifest.json`, and
`work-upstream/evidence-s203-replay-manifest.json` give the trial times, exact
plan SHA, file hashes, and node1 locations. The main 128/128 phase remains
complete; the independent supplemental budget is 51/80 effective at this
interim checkpoint.

### s203 trace-only lock identity control

A separate observer agent logs the `ServerStateNode` server name and object
identity when `readLock()` or `writeLock()` returns. Around the selected
`AssignmentManager.reportRegionStateTransition` and `submitServerCrash` lock
call sites, it logs the same identity before `lock()`, after successful
acquisition, and after release. It does not change the original JUnit, HBase
release JAR, fault selectors, or fuzz checkpoint. The diagnostic agent JAR SHA
is `c4ac78d1f34c4ada2728ebea831dec0505f76aab7f7c1b3ff3b3f98f5d94e4fa`.
The no-fault original JUnit passed in 59.97 seconds and produced 1,208
balanced read-lock acquisitions with concrete server names. Its raw manifest
SHA is `25adb109adf8e5aae5dd8825e41d8a5446f7e65d67f6996176c1e41cb791bd0f`.

The first same-plan diagnostic fault run applied both faults to replica 7 and
reached B7, but the aborted server did **not** carry `hbase:meta`. Its
`ServerStateNode` read locks had all been released when the tracker requested
the write lock; the tracker acquired it immediately, scheduled SCP promptly,
and the original JUnit passed in 57.89 seconds. This is a conditional
non-meta control, not evidence against the meta-hosting s203 timeout. Its
raw manifest SHA is `eb199ab13fecc1ac8522b7c7a7c8d4b593b8679ce977643aba3b7d5e420d1bb3`.
Both diagnostic raw sets were independently verified on node1. They are
excluded from the fuzz attempt and effective counters. Direct proof of the
meta-hosting reader/writer identity chain remains pending.

Three additional fresh-fixture runs used the same plan and unchanged original
JUnit. Repeat 2 selected the `hbase:meta` host and applied both faults to the
same replica-7 actor; B7 occurred, then the test passed in 89.90 seconds with
600/600 table-2 children complete. For that server node, all 90 READ lock
acquisitions had matching releases before the tracker requested WRITE; WRITE
was acquired immediately and SCP was scheduled. Repeats 3 and 4 selected
non-meta servers and also passed (58.06 and 60.29 seconds). Their exact faults,
B7, lock events, JaCoCo, and raw logs were independently SHA-checked on node1.
The five control manifests and separate budgets are recorded in
`work-upstream/diag-s203/evidence-diagnostic-rollup.json`.

The independent source and lock review is
`../../audits/hbase32-s203-independent-lock-review-2026-10-07.md`. Original
s203 and its clean replay still establish a reproducible timeout under their
observed schedule. The trace-only controls did not reproduce it, including
the same-meta-host repeat. The original dumps cannot prove that the blocked
report handler holds a READ lock on the *same* `ServerStateNode` whose WRITE
lock blocks the tracker. Classification remains
`candidate_pending_lock_identity`, with `new_bug=false`. No diagnostic run
contributed to the 51/80 supplemental effective count or its coverage/queue.
The main 128/128 result and its ledger are unchanged.

## Supplemental s272 exact timeout candidate (interim)

The unchanged `TestRegionReplicaFailover#testLotsOfRegionReplicas` reached the exact B7 rethrow after both same-actor faults and timed out (exit 124, 403.94 s including shutdown). The 272-attempt supplemental checkpoint contains 68 true effective trials; s272 is excluded from coverage/I/O feedback and descendants. The original raw log, JaCoCo, four `Thread.print -l` dumps, checkpoint, runner and agent hashes were preserved on node0 and independently SHA-256 verified as 19 files on node1. See `work-upstream/evidence-s272-original-manifest.json` and `work-upstream/evidence-s272-original-remote-receipt.json`.

Trace-only lock identity markers record RPC handler READ ACQUIRED on `ServerStateNode` identity `72dae815` for the aborted meta RS at event 605, followed by tracker WRITE BEFORE_LOCK on the **same node/server** at event 741. One reader remains active at the WRITE wait; no WRITE acquire appears before shutdown. Four native thread dumps show the tracker waiting for the server write lock, that RPC handler waiting for a region lock, and `PEWorker-14` holding the region lock during meta `HTable.put` retry. The first SCP appears only after timeout shutdown starts. The machine also hosted other test JVMs during the original run. See `work-upstream/evidence-s272-candidate-review.json`. An isolated same-plan 600 s replay and independent source/known-issue comparison are pending. Classification: `exact_timeout_candidate_pending_clean_replay`, `new_bug=false`.

### s272 bounded exact replay outcome

Six unchanged original JUnit reruns used the frozen two-fault plan with the same agent and release JAR hashes. Every rerun injected both faults into the same raw primary region, reached B7, passed JUnit and completed 600/600 child assignments. Replays 4 and 6 selected the current `hbase:meta` hosting RS; both had zero outstanding report READ holders when the tracker requested WRITE, acquired WRITE immediately, and scheduled SCP. The original s272 had one outstanding READ on that same ServerStateNode and remained stalled until timeout shutdown. This is a scheduling-sensitive recovery wait candidate; B7 itself is the expected rethrow of our injected DNR exception. The first replay briefly overlapped a read-only HBASE-22 `CoverageNamespace` JaCoCo helper at startup; replays 2–6 had no known additional node0 JVM. See `work-upstream/evidence-s272-six-replay-audit.json` and the SHA-verified node1 archives for every run. No replay entered fuzz coverage/queue/effective counters; supplemental remains 68/80 effective and `new_bug=false`. A distinct role-aware plan is being designed offline and will not be reported as an exact s272 replay.

### Distinct meta-host role-aware variation

`work-role/` is the first plan and remains immutable. Its original no-fault
`testLotsOfRegionReplicas` JUnit passed in 58.36 s and reached 542 targets,
but its fixed stable-region replica-2 master report came from a different RS
than the current meta host. The strict identity gate rejected that plan; the
raw log/JaCoCo/receipt were SHA-verified on node1. It is a calibration
attempt, not a fuzz-effective trial or an s272 exact replay.

`work-role-v2/` is a separate dynamic role plan. F1 selects an actually
observed table2 replica-2 OPENED RPC on the successful pre-fault meta host;
F2 selects the target-ordinal-1 flush RPC for the same raw primary and
secondary region. The log also keeps actual stable region, full ServerName,
and lock identities. Java 8 build, bytecode callsite, selector and auditor
positive/negative smokes passed. This branch requires two independent
passing no-fault original JUnits before up to three fault diagnostics.
Its own checkpoint starts from zero and never imports the fixed-region
calibration or supplemental 68 effective trials. A new timeout remains a
candidate until raw lock-chain/source review and original same-plan replay.

Its first no-fault original JUnit also passed (57.47 s, 542 target invocations),
but all 60 table2 replica-2 OPENED reports came from a non-meta RS. The meta
host served another secondary replica index. That raw calibration was
separately SHA-verified on node1 and is not a V3 healthy pass. The new
`work-role-v3/` plan selects the **actual secondary replica on the meta host**
and requires F1, F2, target, and B7 to agree on the numeric replica and raw
primary/secondary region. V3 starts a fresh two-healthy gate and at most
three diagnostic fault attempts; it remains separate from s272 exact replay
and both fuzz denominators.

V3 original no-fault calibrations `healthy-001` and `healthy-002` passed
JUnit 1/1 in 59.96 s and 60.69 s. They observed 164 and 175 exact
meta-host secondary-replica to same-raw-region target to flush-RPC paths.
Both complete raw logs, JaCoCo data, and receipts are SHA-verified on node1
under `role-aware-v3-pilot/healthy-001` and `healthy-002`. These are
calibrations only; neither enters the 128 main or 68 supplemental effective
trial count. The V3 bounded fault stage uses its own checkpoint and plan.

V3 `role-f001` used the unchanged original JUnit and strictly applied both
faults to the actual meta-hosting RS and the same raw region/replica-8 actor.
The target B7 rethrow occurred once; the original JUnit did not complete
within the 600 s test cap (runner elapsed 641.95 s including shutdown).
Five thread dumps and the trace-only lock hook show a same-server-node
recovery wait lasting until shutdown. Full raw/JaCoCo and the dumps were
SHA-verified on node1. See `work-role-v3/role-f001-owner-audit.md` for source
and line-level evidence. This is a **candidate**, `new_bug=false`; subsequent
V3 runs are paused pending independent review and bounded same-plan replay.

V3 `role-f002`, the first bounded fresh-fixture replay, also strictly reached
the meta host and the same raw actor (replica 9 in this fixture), then timed
out at the original JUnit cap (643.45 s including shutdown). Five dumps and
the lock trace show two active READ holders on the expired meta server node;
the first carrying-meta SCP was scheduled only after shutdown released them.
Its raw evidence is SHA-verified on node1. See
`work-role-v3/role-f002-owner-audit.md`. Both runs remain candidates and
contribute to neither fuzz budget.

### V3 terminal role-aware comparison and case result

V3 `role-f003`, the last bounded semantic replay, hit the actual meta-hosting
RS and strictly applied both faults to one raw primary/secondary region and
replica 3. B7 occurred after the second fault. The original JUnit passed 1/1
in 89.83 s, and all 600 table2 child assignments completed. When the tracker
requested WRITE, there was no active transition-report READ holder on that
same `ServerStateNode`; WRITE was acquired immediately and carrying-meta SCP
was scheduled. See `work-role-v3/role-f003-owner-audit.md` and the raw trace.
This same-role negative control shows that meta placement and the two source
selectors alone do not force the long wait seen in `role-f001/f002`.

The frozen V3 diagnostic therefore contains two strict role-conditioned
600 s original-JUnit noncompletion runs and one strict same-role passing
control, following two passing no-fault calibrations. Across these five JUnit
runs the measured runner time is 1,495.88 s. Every raw log, JaCoCo file,
thread dump where applicable, and receipt is retained; each per-run archive
and manifest were independently SHA-256 matched to the node1 copy. The
machine-readable list and hashes are in `work-role-v3/role-v3-rollup.json`.
V3 contributes zero effective fuzz trials to either main or supplemental
checkpoints. The original main stage completed 185 attempts / 128 true
effective trials in 14,645.67 s, including its 60.13 s healthy calibration;
supplemental reached 272 attempts / 68 effective trials in 18,792.59 s and
stopped at the precise s272 candidate. The supplemental duration is the sum
of all 272 checkpoint trial receipts and corrects an earlier stale result
field. The measured subtotal for these three phases is **34,934.14 s**; it excludes
earlier isolated replays and V1/V2 calibrations, whose timings remain in
their own receipts.

The source-backed wait in `role-f001/f002` is: transition handler holds a
READ on the expired meta host's `ServerStateNode` while awaiting a region
lock; a procedure worker holds that region lock while synchronous
`RegionStateStore.updateRegionLocation` retries a meta `HTable.put` to the
failed host; the tracker needs WRITE on the same server node before it can
submit SCP. Dumps and lock identities sustain this chain until test timeout
shutdown. The B7 rethrow itself is expected for the injected
`DoNotRetryIOException`. A 600 s timeout does not prove an infinite deadlock:
the meta RPC retries may eventually terminate. HBASE-24526 describes a
related meta update progress problem after a meta assignment subprocedure is
already scheduled, whereas these traces stop before SCP submission.
HBASE-21508 and HBASE-29259 also have partial mechanism overlap; the latter
issue's primary failure differs. Independent source reviews are in
`audits/hbase32-role-f001-independent-review-2026-10-07.md` and
`audits/hbase32-role-f002-novelty-review-2026-10-07.md`. The case is
`quality_complete` as a **reproduced candidate with novelty pending**,
`new_bug=false`. There is no confirmed new HBase bug in this checklist row.

Resume points are immutable and separated: main
`work-lots/checkpoint.json` is terminal at 128 effective; supplemental
`work-upstream/supplemental-checkpoint.json` preserves s272 as an excluded
candidate with 68 effective. V3 `work-role-v3/role-pilot-checkpoint.json`
has two healthy and three fault diagnostics, `in_flight=null`, and is at its
three-fault cap. Any future work must start a new diagnostic stage or, if
explicitly expanding supplemental fuzz after candidate review, recover from
the supplemental checkpoint without importing V3 attempts or repeating old
plans.

The independent three-run review is
`audits/hbase32-role-v3-three-run-independent-review-2026-10-07.md`. It
confirmed both bounded positive waits and the same-role passing control,
and retains `new_bug=false`.

### Terminal raw offload and recovery

After terminal review, compressed logs from 70 non-candidate supplemental
trials (`s201-s202` and `s204-s271`) were copied with each trial's JaCoCo and
exit receipt to node1. An independent pass rehashed all 210 archive members
and extracted two sample members per segment before removing only the 70
duplicate `.log.gz` files on node0. JaCoCo, exit receipts, checkpoint, and
the `s203` and `s272` candidate records remain locally. The exact paths,
sizes, SHA-256 values, archive locations, and disk readings are in
`work-upstream/evidence-terminal-offload-s201-s271.json`; segment manifests
and remote receipts are named `evidence-segment-s201-s202-*` and
`evidence-segment-s204-s271-*` in that directory. This released 68,908,708
bytes without changing the supplemental checkpoint.

To restore an offloaded log, copy the corresponding `*.tar.gz` from the
receipt's `remote_archive` on node1 to a temporary directory, verify its
`archive_sha256`, extract the `logs/*.log.gz` member there, compare its SHA
with `files_offloaded`, then copy that member back to `work-upstream/logs/`.
Do not treat missing local compressed logs as missing trials: each trial's
identity, result, duration, and feedback remain in the checkpoint and
original JaCoCo and exit receipts stay in place.

On node1, the 177 main-stage trials with original JUnit exit 0 and no
timeout/review candidate held 2,287,021,148 bytes of plain `.log` files.
Their exact names, per-file SHA-256 values and eight excluded candidate IDs
are in `work-lots/evidence-main-pass-log-offload-manifest.json`. A low-priority
stream created a compressed archive **only on node2** at
`/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32/main-pass-logs-terminal/main-pass-logs.tar.zst`.
Its SHA-256 is
`5d0273b5612720df114b4da705e6614c2086d056ad8997ded6e2b734924c0c0b`.
The node2 verifier hashed all 177 tar members and actually extracted and
rehash-checked `r001.log` and `r185.log`. Only after this check were the 177
node1 source logs removed. The node1 checkpoint SHA stayed
`f3f75d5b5d19cfe17ec3be42300feaa2402c23968e6ebbb28e5d0f28e5156115`;
the eight timeout/candidate logs, `actor-healthy.log`, all `.exec` and `.exit`
files, and receipts remain on node1. The remote verification and node1
deletion receipts are `work-lots/evidence-main-pass-log-offload-remote-receipt.json`
and `work-lots/evidence-main-pass-log-offload-node1-receipt.json`.

For recovery, copy that node2 archive to a temporary location, compare its
SHA-256 with the receipt, and run `zstd -dc ARCHIVE | tar -xOf -
logs/rNNN.log > TEMP_LOG`. Compare `TEMP_LOG` with the corresponding entry in
the manifest, then move it to the node1 `work-lots/logs/rNNN.log` path. No
original JUnit rerun is needed.
