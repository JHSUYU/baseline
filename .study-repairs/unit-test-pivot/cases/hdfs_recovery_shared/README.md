# HDFS-28/29/30: block-recovery checks

This is one shared execution campaign with three separate target oracles. It
uses the unchanged Hadoop 3.4.3 JUnit
`org.apache.hadoop.hdfs.server.datanode.TestBlockRecovery2#testRecoveryTimeout`.
Its original `@Before` starts a mock-NameNode DataNode, which the test stops;
the test then calls `TestBlockRecovery.testRecoveryWithDatanodeDelayed`.
That helper builds a one-NameNode, two-DataNode `MiniDFSCluster`, writes an
unclosed file, delays/drops the first `commitBlockSynchronization` call, and
waits for recovery after a short lease (`TestBlockRecovery2.java:283-321`,
`TestBlockRecovery.java:973-1023`).

| Case | Selected source check | State read | Meaning |
| --- | --- | --- | --- |
| HDFS-28 | `BlockRecoveryWorker.getDatanodeID`, guard `#u12`, throw at `BlockRecoveryWorker.java:539` | DataNode's block-pool offer-service map | Per-replica recovery needs the DataNode's registration for the block pool. |
| HDFS-29 | `BlockRecoveryWorker.getActiveNamenodeForBP`, guard `#u12`, throw at line 578 | The same block-pool offer-service map | Synchronization rechecks the map after replica RPCs; an actor can shut down in between. |
| HDFS-30 | `BlockRecoveryWorker.getActiveNamenodeForBP`, guard `#u23`, throw at line 583 | The offer service's active-NameNode actor | Heartbeat/handshake claims and actor shutdown can change active-NN state. |

These checks are not yet source-excluded. HDFS-28 and HDFS-29 repeat a
block-pool map lookup at different phases, separated by replica-recovery RPCs
(`BlockRecoveryWorker.java:118-189`). `DataNode.getBPOfferService` delegates
to `BlockPoolManager.get` (`DataNode.java:2235-2236`); the manager adds and
removes entries as offer-service actors change (`BlockPoolManager.java:65-95`).
HDFS-30 reads `BPOfferService.getActiveNN`, whose value comes from handshake,
heartbeat HA claims, and shutdown (`BPOfferService.java:375-382,467-471,
519-534,567-603`). That is a control-plane relation, not a purely local
comparison. Whether any injected failure creates an incorrect state is an
experimental question.

## Original-JUnit calibration and runtime identity

The untouched distribution test passed in 30.795 seconds
(`independent/healthy-native/manifest.json`). Four independent case-local
ASM/JaCoCo healthy runs passed and observed both possible coordinator nodes,
`dn0` and `dn1` (`independent/healthy-v3*/manifest.json` and each
`runtime_trace.jsonl`). Each run reached HDFS-28 twice, HDFS-29 once, and
HDFS-30 once, with all guards nonfatal. The first instrumented run captured
29,324 package-prefix JaCoCo probe IDs. That archival RPC-only pilot used
the union of four healthy runs as its baseline; its coverage count included
test-generated classes and is not compared with the corrected V4 production
coverage below.

`PatchRecovery.java` instruments only the released `BlockRecoveryWorker`,
its contiguous recovery task and block record, `MiniDFSCluster.waitActive`,
and `Client$Connection.sendRpcRequest`. Its build fails if any of the three
guard branches, three target throws, recovery context, or RPC hooks is absent.
`RecoveryProbe.java` registers physical `dn0`/`dn1` identities from the
cluster, records block ID and attempt ordinal in each recovery root, and
distinguishes a remote `InterDatanodeProtocol.initReplicaRecovery` call from
the local method call. The physical Hadoop IPC send hook labels
`initReplicaRecovery`, `updateReplicaUnderRecovery`, and
`commitBlockSynchronization` separately. A selected fault requires the full
runtime marker, exact bytecode/source call site, source node, recovery
occurrence, and hit ordinal; the injected kind is also recorded. The raw
runtime trace and per-run fault plan prove matching and application in order.
`independent/provenance.json` hashes the released distribution and original
test classes, lists the five case-local overlay classes, and verifies the
runtime classpath contains no GraphChecker component.

The initial exact `IOException` replay at a remote recovery RPC is
`independent/smoke-v3-remote-io`. It applied one fault at seq 8 and then
reached the same `dn1/block:1073741825` target operation: HDFS-28 guard
seq 9, HDFS-29 seq 12, HDFS-30 seq 14; all were nonfatal. The original JUnit
passed in 23.540 seconds. The smoke is the campaign's first counted trial.

## Fuzzing and evidence

`independent/campaign.py` uses observed recovery RPC points and JaCoCo
production probes/methods/branch counts to prioritize ordered exception
sequences; it reads no GraphChecker graph, closure, skeleton, or runtime JAR.
The default budget is 80 trials with at most 8 faults per sequence. If the
last eight target-retaining trials add stable I/O families or production
coverage, it extends to 128 trials/10 faults. Each case has its own post-fault
target and exact `IOException` throw count, even though the JUnit execution
is shared. A JUnit failure by itself is not a bug oracle. A new exact target
exception is a candidate requiring source review and replay.

The campaign runs in tmux `hdfs28_30_recovery_campaign`. Its atomic resume
checkpoint is `independent/campaign-state.json`, with a pending active
sequence preserved across process interruption. The bounded tmux supervisor
is `independent/supervise.sh`; the process log is
`independent/campaign.log`. Every trial has its own fault plan, original-JUnit
log, trace, JaCoCo data, coverage lists, and timing manifest in
`independent/runs/trial-NNN/`. Each case's `result.json` and
`trial-ledger.csv` are written separately under `cases/HDFS-28`,
`cases/HDFS-29`, and `cases/HDFS-30`.

An unmatched node-specific selector is recorded as an attempt and requeued
up to twice because the original test may choose either DataNode as recovery
coordinator. Applied faults at post-check update/commit RPCs are retained as
observations, but only a later same-node, same-block target check makes such
a trial valid for feedback. A controlled scheduler restart preserved four
completed attempts; the interrupted fifth attempt's partial files are under
`independent/runs/interrupted-trial-005-20261006` and are not counted.

## Expanded replica-file I/O campaign

The RPC-only run above was stopped after 13 attempted sequences and archived
as `independent/campaign-state.json` and each case's
`legacy-rpc-result.json`/`legacy-rpc-trial-ledger.csv`. Its 6 exact injections,
2 target-retaining trials per case, and 509.569 seconds per case remain in the
102-case totals. The interrupted fourteenth attempt is excluded. The old
tmux worker is stopped. Its JaCoCo gains are **not** mixed with the expanded
instrumentation's coverage denominator.

The active phase is `phase-v4/`. It adds the actual
`FsDatasetImpl.checkReplicaFiles` file-existence and file-length reads at
lines 2295–2308 to the RPC I/O scope. The server-side probe carries the
block ID, recovery ID, and coordinator's source through the incoming
`initReplicaRecovery` call; its runtime address also names the physical
DataNode performing the read. A file fault requires exact marker, site,
physical server, coordinator/attempt/block address, and hit ordinal. The
campaign also verifies a preceding owner `RECOVERY_BEGIN`; a file point
must have a matching physical `SERVER_RECOVERY_BEGIN`. Post-fault target
checks require that same owner occurrence, so a later retry or another
DataNode does not replace a lost target. The probe accepts `IOException`
and `FileNotFoundException` at the file check.
The original JUnit method and operations remain unchanged.

The source calls `checkReplicaFiles` both during replica initialization
(`FsDatasetImpl.java:3039`) and during update (`:3121`, `:3146`). A third
original-JUnit healthy run, `phase-v4/healthy-file-phase`, used the same
production ASM hooks and passed in 22.713 seconds. It observed eight
`initReplicaRecovery` file points and eight local
`updateReplicaUnderRecovery` points. The file probe now checks its call
stack: initialization needs the incoming server recovery context; update
requires the original coordinator thread and matching owner root. The fault
selector records this phase as a seventh field, preventing a skipped init
read from shifting the same site and ordinal onto an update read. Earlier
strict file faults were checked against source order and this calibration:
their first-ordinal points occurred before HDFS-29; the sole second-ordinal
point was a local update after HDFS-29. `phase-v4/upgrade_phase_context.py`
and `upgrade_phase_selector.py` record the idempotent checkpoint migration.

Two phase-v4 healthy runs passed in 30.418 and 25.028 seconds; they exercised
opposite `dn1` and `dn0` coordinator roles and reached all three nonfatal
guards. The strict file-fault pilot `phase-v4/smoke-file-remote` injected
`IOException` on `dn0`'s `blockDataExists` read, with `dn1` as the
coordinator, at trace seq 19. The same recovery reached HDFS-29 at seq 20 and
HDFS-30 at seq 22, and the original JUnit passed in 24.827 seconds.
HDFS-28's check preceded the fault, so this pilot does not count as a
target-retaining HDFS-28 trial.

`phase-v4/campaign.py` runs the 80-trial/max-8-fault budget, extending to
128/max-10 when one of the last eight valid trials adds production JaCoCo
coverage or a stable I/O family. The queue uses three healthy traces and
contains 106 distinct initial RPC/file selectors. It stores an atomic
checkpoint at `phase-v4/campaign-state.json`; `phase-v4/supervise.sh` resumes
the same sequence after a process failure. Per-case expanded-phase ledgers
are `trial-ledger-v4.csv`. The per-case `result.json` reports only the V4
budget and elapsed time; the earlier 13 RPC-only attempts remain separately
in each case's `legacy-rpc-result.json`.

After trial 52, coverage feedback was corrected at a clean trial boundary.
The earlier JaCoCo probe extractor accepted Mockito classes generated under
Hadoop package names with a fresh random suffix in every JUnit process;
these were false coverage gains. `CoverageRecovery.java` now retains only
classes in the released Hadoop HDFS, HDFS client, and common production jars.
`phase-v4/correct_coverage.py` filtered all saved derived coverage text,
recomputed the healthy baseline, per-trial gains, per-case union, and queue
scores without replaying any completed test. The raw `jacoco.exec` and
runtime traces remain intact. The original checkpoint is compressed at
`phase-v4/campaign-state.before-coverage-correction.json.gz`, with per-run
hashes/counts in `phase-v4/coverage-correction.json`. At the correction point,
the stable probe gains were 106 for HDFS-28 and 107 for HDFS-29/30.

Later phase-v4 trials use a 180-second JUnit timeout, about six times the
healthy execution time. A timeout is recorded with its elapsed time, strict
fault match, and post-fault target status; it does not by itself mark a bug.
The scheduler samples three single-fault selections per multi-fault selection
to cover more distinct file/RPC points before spending time on fault
combinations. It balances the four exception types before scoring previously
tested I/O families, because otherwise each family's first `IOException`
would consume the budget before `FileNotFoundException`, `EOFException`, or
`SocketTimeoutException` received a trial. This change took effect after
V4 trial 28 via `phase-v4/pause.request` at a completed-trial boundary; no
partial trial was added to the ledger. V4 trials 2–4 used the original
420-second cap; each has a
`timeout-policy.json` sidecar in its trial directory.

After V4 trial 64, another clean-boundary queue update prioritized a child
whose observed I/O preceded the next target check of the same recovery owner
in its parent run. Three selections in four use this preference; the fourth
retains exploration of all queued points. All 430 existing sequences stayed
in the queue, and completed trials were not replayed. Before the change,
16 two-fault attempts included five exact injections but no check on the same
owner after the second fault. The migration classified 110 multi-fault
children as pre-target and 259 as later I/O, using the original parent trace;
`phase-v4/pre-target-priority-change.json` records the rule, checkpoint hash,
queue counts, and the prior effectiveness. The previous checkpoint is at
`phase-v4/campaign-state.before-pre-target-priority.json.gz`.

The V4 queue completed 128 attempts (63 exact injections). An independent
raw-trace audit found same-recovery-owner target checks after exact faults in
18, 39, and 39 attempts for HDFS-28, HDFS-29, and HDFS-30, respectively;
none threw the selected target `IOException`. The audit parsed every completed
raw trace, and a SHA-256 verified archive preserves 799 raw files before 640
regenerable scratch/coverage exports were removed. See
`phase-v4/final-audit.json` and `phase-v4/raw-evidence-receipt.json`.
The archived V4 probe source has a malformed `TARGET_THROW` JSON field after
its numeric block ID. No completed trace contains that event, and the audit
would have rejected malformed JSON; this issue was fixed in the separate HA
control-plane adapter before its fault campaign. The archived V4 source and
provenance hash were left intact.

### Effective-budget continuation

The 128 V4 runs reached the earlier **attempt** cap, leaving 789 observed-I/O
plans queued. The actor-qualified post-fault target counts were only 18
(HDFS-28), 39 (HDFS-29), and 39 (HDFS-30), so none meets the current
80-effective-trial standard. `phase-v4/resume_effective.py` resumes the
unchanged original `TestBlockRecovery2#testRecoveryTimeout` JUnit from that
exact checkpoint. It requires the saved checkpoint SHA-256
`c990b52036d45f25a4370c611a2254fa3bdd580853a392226909ad04dd3a2b1b`,
backs it up, retains all 128 completed plans, and assigns each check its own
80-effective goal. Late method/branch or related I/O novelty at that check's
80th effective trial extends that check to 128 effective. The distinct
attempt cap is 512; exhausting the queue or cap before the goals is
inconclusive. A selected target exception stops for source review and replay.
Every fault plan still comes from runtime I/O observed in the original JUnit;
the controller uses JaCoCo feedback and the saved same-recovery-owner
identity receipt.

The node1 copy has the same absolute workspace path, matching released
Hadoop 3.4.3 test/production JAR hashes, and an exact SHA-256 copy of the
original checkpoint. A dry migration on node0 reproduced the 18/39/39 counts
and preserved 128 trial IDs and 789 queued plans. Run `--preview` for a
read-only count, then `--run --max-new-attempts 1` for a bounded original
JUnit pilot. Further `--run` calls resume the atomic checkpoint. The
supervisor checks host JVM count and disk before every JUnit and shares
`jvm-start.lock` with the node1 QJM controllers. It does not count the old
128 attempts as 128 effective trials or claim final quality before a new
independent raw audit.

## Independent HA owner-test calibration

The released `TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization`
is another original embedded-cluster JUnit for the same three checks. Its
source sets `NN_COUNT = 3`, builds a three-NameNode, three-DataNode
MiniDFSCluster, and fails over
after the first block-synchronization request but before commit
(`TestPipelinesFailover.java:328–407,418–422`). A first direct run lacked
the project's Maven test-resource `hdfs-site.xml` and failed before any
target check because its 4 KiB test block was below the distribution's 1 MiB
minimum. The released source's `src/test/resources/hdfs-site.xml:30–33`
sets that minimum to zero for the test suite. Passing that original resource
directory on the classpath made the unchanged JUnit pass in 27.964 seconds:
`phase-v4/healthy-ha-failover-resources/manifest.json`. Its trace records
two distinct recovery owners (`dn1` and `dn0`), each reaching HDFS-28/29/30
on the nonfatal branch, no target throw, and 44 observed recovery RPC/file
I/O events. This is a separate healthy calibration; its time, coverage, and
I/O points are excluded from the running `TestBlockRecovery2` campaign and
the 102-case trial totals.

An isolated HA pilot applied one exact remote replica-file `IOException` in
the first recovery on `dn1` (`ha-smoke-file-b/runtime_trace.jsonl`, seq 20).
The same recovery then reached HDFS-28/29/30 at seq 21/29/31 on the
nonfatal branch; the unchanged JUnit passed in 26.370 seconds. Relative to
the HA healthy seed, released production-class JaCoCo gained 29 probes,
three methods, and 22 branch-count IDs
(`ha-smoke-file-b/evaluation.json`). The first attempt
with this selector, `ha-smoke-file`, had no matched fault because the
original test chose `dn2` as primary instead of `dn1`. These two HA pilots
are kept separate from the main 80-trial budget.

## HDFS-30 HA control-plane supplement

The separate, original `TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization`
campaign ran on node2 with its released 3-NameNode/3-DataNode embedded cluster.
The case-local ASM overlay recorded the heartbeat request, response delivery,
HA actor state, and the original target guards after NN0-to-NN1 failover.
Its no-fault active1-gated seed passed in 25.170 seconds. Two earlier no-fault
node0 seeds timed out before failover under host load and were excluded from
the target-valid set.

The bounded supplement completed 24 attempts (11 exact full-sequence
injections). Two reached the same DataNode/block/recovery-ID HDFS-30 guard
after the final fault; neither made its guard fatal or threw the selected
`IOException`. It added 22 released-production JaCoCo probes, one method,
and five covered-branch-count units within this separate JUnit campaign.
The remaining 60 queued sequences were not executed after the stated
24-attempt budget. Its independent audit parsed all 24 trial traces and four
healthy traces with no integrity errors. The raw-evidence archive contains
180 SHA-256-verified files (archive SHA-256
`d39f16d3e148b719f7f026ccac34cfb893ae00d9aa751492daee7cd4b8f05fe3`);
only 114 regenerable scratch/coverage exports were removed. See
`ha-control-v1/README.md`, `ha-control-v1/ha-final-audit.json`, and
`ha-control-v1/ha-raw-evidence-receipt.json`.

HDFS-30's checklist result counts 128 V4 recovery attempts plus these 24 HA
attempts: 152 attempts, 74 exact full-sequence injections, 41 strict
same-identity target-retaining trials, and zero selected target exceptions.
The 13 earlier RPC-only pilot attempts are preserved separately and excluded
from this total. Reported fault-trial time is 4,689.058 seconds; including
the four HA no-fault calibrations, reported time is 4,868.851 seconds.
