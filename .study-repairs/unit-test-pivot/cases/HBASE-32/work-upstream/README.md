# HBASE-32 independent upstream I/O campaign

The workload is the unchanged HBase 2.6.6 `TestRegionReplicaFailover#testLotsOfRegionReplicas` MiniCluster JUnit. This phase is separate from `../work-lots/`, which injects at the client flush RPC. `HBase32UpstreamAgent` records the selected B7 target, real Master OPENED report RPC calls, real primary WAL append/sync calls, and their raw region/secondary actor identities. It also passively records meta lookup calls. The queue admits only Master OPENED and WAL append/sync events tied to a target actor. It never injects the unlinked asynchronous meta scan or the table-state Get that occurs after the selected exception guard.

`healthy4.log` and `healthy4.exec` are the immutable fault-free seed. The fresh seed has 540 target-linked Master OPENED, 341 exact-actor WAL append, and 341 exact-actor WAL sync selectors. `campaign.py` stores atomic `supplemental-checkpoint.json`, `supplemental-inflight.json`, and `supplemental-result.json`; each trial has an exit receipt, compressed full trace, and separate JaCoCo `.exec`. On restart it resumes the inflight plan and does not replay a trial with a completed receipt. The controller is run in node0 tmux `hbase32-upstream-fuzz`:

A plan whose exact I/O identity never appears can be retried at most twice, with a lower selection priority. Such attempts retain their raw evidence, never enter the effective denominator or coverage feedback, and do not generate children. Checkpoint version 2 restores unmatched plans from the initial running campaign into the queue without replaying completed trial IDs or changing the accumulated coverage.

Checkpoint version 3 removes an unjustified limit of two `DoNotRetryIOException` faults per sequence. HBase 2.6.6's `HRegion.writeCanNotFlushMarkerToWAL` catches a marker `IOException` and returns `false`; `RegionReplicaFlushHandler` retries that response using `RetryCounter` (default configuration gives five retries after the first failure). The old limit prevented the queue from testing retry exhaustion through this upstream WAL path. Version 3 reconstructs previously pruned children only from fully applied, target-retaining two-fault parent traces, using their original event order and actor identity. The overall eight-fault limit and cluster/target validity rules still apply.

Pure WAL retry exhaustion eventually throws a newly constructed `IOException` from the response-false arm, so it does not execute the selected B7 rethrow in the flush-RPC catch. Checkpoint version 4 adds bounded mixed plans: a fully applied Master/WAL prefix retaining the exact raw target actor can be followed by one observed client flush RPC exception from that actor. The two agents receive their own plan parts; the controller validates the *combined* applied events in raw log order and checks each agent's step number separately. Mixed plans have no children after the terminal RPC fault. Only an exact same-actor B7 rethrow after the final fault counts toward the 80-effective budget. Pure WAL paths remain separate related-path exploration and may contribute coverage/I/O feedback, but never count as B7-effective merely for retry exhaustion.

Checkpoint version 5 changes only queue scoring. It treats a fault identity as the exact I/O selector plus exception kind, counts that identity as tested only when the whole planned sequence was applied, rewards measured parent JaCoCo and related I/O novelty, and slightly reduces priority for mixed plans whose upstream prefix has repeatedly disappeared. Waiting age and the every-tenth-round legal depth choice still prevent one family from monopolizing the queue. The migration keeps all prior plans, trials, coverage, and effective counts.

Checkpoint version 6 also lowers the priority of a terminal RPC ordinal after repeated trials applied the whole upstream prefix but never reached that RPC. It preserves the late ordinal for occasional exploration. For future controlled pauses, create `pause-after-checkpoint`; the controller finishes the current trial, atomically checkpoints it, and then exits its tmux pane. Remove the sentinel before restarting. Inflight receipts still support recovery from an unexpected interruption.

Checkpoint version 7 retains every version 6 plan and receipt. Among new selections, it assigns about 70% to `DoNotRetryIOException` because this was the only exception kind reaching B7 in the first 39 trials; the other three kinds each retain about 10% for semantic exploration. Four of five selections favor a mixed same-actor upstream prefix and terminal client RPC. One of five favors pure upstream exploration, and every tenth round still seeks the deepest legal plan. Existing production coverage, global I/O novelty, waiting age, and unmatched-fault penalties remain in the score. The migration's unchanged queue, trial, coverage, and I/O hashes are recorded in `evidence-v7-migration-pre.json` and `evidence-v7-migration-post.json`.

Checkpoint version 8 retains all 78 completed attempts and the existing queue
while raising the initial attempt safety cap from 240 to 384. The goal remains
80 B7-effective trials with at most eight faults. A future timeout or failed
original JUnit that reaches the target is held for exact replay: its raw
receipts remain, but it cannot contribute to the effective denominator,
coverage/I/O feedback, or child sequences. The version 7 controller had
admitted s078 despite its timeout. Version 8 excluded that one candidate,
recomputed JaCoCo and I/O unions from accepted trials, and corrected the
count from 19 to 18 effective. The queue and all completed source identities
and raw hashes stayed unchanged; `evidence-v8-migration-pre.json` and
`evidence-v8-migration-post.json` record both checkpoint and controller
script hashes. `../evidence/s078-candidate-receipt.json` preserves its exact
two-fault, same-actor B7 observation pending a separate clean replay.

Before starting a new JUnit, the controller checks local free space. Below
2.2 GiB it atomically publishes `paused_low_disk` and exits at the checkpoint,
leaving a margin above the 2 GiB hard floor. Existing raw traces, JaCoCo
files, and receipts remain intact; moving them to a larger node requires a
separate verified archival step.

At the s047 complete checkpoint, 198 closed source, trace, coverage, and
receipt files (164,013,674 bytes) were copied to a dedicated node1 archive.
`archive-s047-manifest.json` records each source SHA-256, and
`archive-s047-verified.json` records the node1 verification of all 198 files.
The node0 originals were retained and the controller resumed at s048.
Another 99 completed raw log, JaCoCo, and exit files for s048–s080
(30,036,213 bytes) were copied to a separate node1 case directory and
verified file by file. `archive-s048-s080-manifest.json` and
`archive-s048-s080-verified.json` record the hashes; node0 originals remain.

Checkpoint version 9 replenishes mixed Master-to-client-RPC plans when the
eligible mixed `DoNotRetryIOException` queue is empty. On a normal mixed
selection round, it first chooses a previously untested single Master OPENED
I/O identity from the original healthy trace. It only generates terminal RPC
children if that faulted parent run actually observes the same actor's RPC
after its injected fault. Existing production coverage, I/O novelty, waiting
age, and fault-identity scores still order candidates; each tenth round keeps
its legal deep-plan preference. The clean s101 boundary migration left 101
attempts, 23 effective trials, 7,231 queued plans, 7,296 seen plans, and the
coverage/I/O unions unchanged. `evidence-v9-pre.json` and
`evidence-v9-post.json` record checkpoint, controller, queue, seen-plan, and
feedback hashes. The controller does not repeat s101 when resumed.

s101 itself applied one Master OPENED exception and one client flush-RPC
exception to the same raw replica-5 actor and reached the B7 rethrow, but its
original JUnit timed out after 397.42 seconds including shutdown. It finished
only 120/600 table-assignment children before timeout. Three pre-timeout
`Thread.print -l` samples show a persistent wait around ServerCrashProcedure
submission and metadata writes, without proof of a closed deadlock cycle.
Two unrelated Solr MiniCluster JUnits were also running on node0; one was
mistakenly placed there instead of node2. This is a resource-confounded
candidate, not a confirmed new bug. It is excluded from effective count,
JaCoCo/I/O feedback, and mutation descendants pending an isolated same-plan
replay. `../evidence/s101-candidate-receipt.json` and
`../evidence/s101-original-node0.tar.gz` preserve full raw evidence and
checksums. The version 9 migration happened only after s101's complete
checkpoint and durable exit receipt.

As node0 approached the 2.2 GiB pause threshold, 79 closed compressed logs
from s001–s080 were relocated to their previously SHA-verified node1 case
archives. The s078 candidate was excluded. The local JaCoCo files and exit
receipts for every trial, plus the complete s078 and s101 candidate logs,
remain on node0. `relocate-s001-s080-logs-pre.json`,
`relocate-s001-s080-node1-verified.json`, and
`relocate-s001-s080-logs-post.json` record each source/destination hash,
checkpoint identity, and recovered space. Version 9 resumed from s102 with
the same 101 completed trials and no repeated plan.

```sh
cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32/work-upstream
tmux attach -t hbase32-upstream-fuzz
```

The current budget is 80 effective trials, at most 384 attempted trials, and
at most eight faults per sequence. Only novelty in the last eight effective
trials extends the goal to 128 effective and at most ten faults, within the
same attempted-trial cap. Each tenth selection prefers a legal deeper fault
sequence. Seeds without postfault target progress, or sequences aborting all
three RegionServers, are not mutated. JaCoCo and I/O novelty enter feedback
only for fully applied sequences retaining the same raw target actor and
without an unreviewed JUnit anomaly. The effective denominator is stricter:
the same raw region, replica, and target invocation must execute the B7
rethrow after the final fault. A Master report retry that merely enters the
target method, or a WAL error that merely causes a same-actor retry, can
generate children but does not count as a B7-effective trial.

Version 10 enforces that every fault in a sequence uses the same stable
region and replica selector, and that the injected calls in one run have the
same raw primary-region bytes and replica. At the s125 complete checkpoint,
an audit found s120 and s121 crossed from replica 2 to replica 5. Their raw
traces and elapsed times remain as attempts, but s120's feedback and s121's
formerly counted B7 hit were withdrawn. The migration recomputed coverage
and I/O unions from SHA-verified original logs, removed 2,830 cross-actor
pending plans, retained all 8,124 seen-plan IDs, and left 125 attempts / 28
valid B7 trials. No completed plan was rerun. See
`evidence-v10-same-actor-migration.json` for before/after hashes and counts;
`evidence-v10-pre-checkpoint.json.gz` contains the exact old checkpoint.

Version 11 changes selection weights only. In s126–s146, nine two-fault
trials yielded five B7-effective results, while seven trials with five to
seven faults yielded one. Outside every tenth mandatory deep-selection
round, each fault above depth three subtracts ten priority points. Coverage,
I/O novelty, waiting age, and exception-kind feedback remain in the score.
The s146 checkpoint migrated with exactly the same 146 attempted plans,
34 effective trials, 5,270 queued plans, 8,200 seen IDs, and unchanged
coverage/I/O unions. See `evidence-v11-depth-priority-migration.json` and
the exact `evidence-v11-pre-checkpoint.json.gz` backup.

`../evidence/upstream-passive-findings.md` records the original-JUnit calibrations, exact actor matching, exclusions, and separate diagnostic pilots. A target B7 throw or an expected server abort is an observation, not by itself a new bug. JUnit failure and timeout trials remain candidates until exact clean replay and source review.
