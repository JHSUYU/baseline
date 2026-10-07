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

Main trial r003 is a **candidate under review**, not a confirmed bug. A
single no-retry flush-RPC exception reached the same actor's guard and B7; one
region server aborted. The original JUnit remained in `Admin.createTable`
at `TestRegionReplicaFailover.java:326` until the 360-second timeout. Two JVM
thread dumps before timeout showed the master and two other region-server
threads still alive. The two later server aborts occurred after the JVM
shutdown hook began and resulted from closed connections during teardown;
they are excluded from the runtime cluster-tolerance count. The raw log,
JaCoCo file, exit status, and dumps are retained under `work-lots/logs/` on
node1. `work-lots/replay-r003-plan.json` and `replay.py` prepare an isolated
600-second replay with the same selector and matching HBase/agent bytecode;
the diagnostic replay has not yet run.
