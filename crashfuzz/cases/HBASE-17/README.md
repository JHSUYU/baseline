# HBASE-17: original cluster JUnit and actor-aware fault campaign

## Active original cluster workload and graph-free campaign

The unchanged original `TestReportRegionStateTransitionFromDeadServer.test`
uses a three-RegionServer MiniCluster. Its test code pauses a region move's
CLOSED report, aborts the source server, and holds/restarts the server-crash
procedure with latches. Production `AssignmentManager.regionClosedAbnormally`
then transitions the same region to `ABNORMALLY_CLOSED`; the selected
`TransitRegionStateProcedure.confirmClosed` assertion evaluates true.

| Independent run | JUnit | Exact B5 | I/O | Wall time |
| --- | --- | --- | ---: | ---: |
| Target-only ByteBuddy probe | 1/1 passed | 1 true | not collected | 48.83 s |
| Full ByteBuddy I/O plus JaCoCo seed | 1/1 passed | 1 true | 62 observed events | 48.78 s |

The old full seed observed 13 stable I/O sites before B5, including the move's
`ExecuteProcedures` RPC, the RegionServer state-transition report, and
`RegionStateStore` writes to `hbase:meta`. Its production JaCoCo scope covers
228 methods and 329 branches at baseline. The exact-guard advice records
method and branch outcome; the fault controller matches each observed I/O by
operation, callsite, thread role, logical endpoint role, stable region
resource, and per-family occurrence in V2. No graph, GraphChecker JAR,
static skeleton, or prewoven classes are used. The original JUnit's server
abort is part of its own scenario and is not counted as an injected campaign
fault.

The two raw logs are on node1 at `independent/report_dead_server_healthy.log`
and `independent/logs/seed.log`; their SHA-256 values are respectively
`cdef9d15c5d230c34fd6b2c2d81fe24933c46cfff67e190ce7c0c7cea26d8d8c`
and `6e72f09bf79589fc7ae70c59693bfce2ab29e736ffca57f9f64bf6de348c78ef`.
## Actor identity correction and V2 seed

The first fault controller logged remote endpoint addresses but omitted them
from the selector. On the three-RegionServer JUnit, the same RPC/occurrence
could therefore hit a different logical actor on replay. It stopped at r039:
39 attempts, 34 coarse-selector matches, 23 post-fault B5 reaches. The
independent role audit can prove the same actor for only 14/34 matched trials
and 10/23 target-retaining trials. Interrupted r040 is not counted. Raw
checkpoint, ledger, and audit are archived in `independent/legacy_actor_phase`;
**none of these old trials enter the V2 effective budget**.

V2 captures the original test's `RegionPlan` source, move destination, target
region, and the remaining third RegionServer from the online server list.
The first target-region OPEN RPC records `INITIAL_OWNER`; the plan must later
prove that it equals `SOURCE_RS`. Each RPC selector includes a stable
table/start-key/replica resource and one of `SOURCE_RS`, `MOVE_DEST_RS`,
`THIRD_RS`, `INITIAL_OWNER`, or `MASTER`. `MasterService` and
`RegionServerStatusService` descriptors identify MASTER. Unknown peers,
`PREMOVE` RPCs other than the validated first OPEN, and unknown resources
remain in the trace but are excluded from the fault queue. The local
`META_PUT` probe covers `RegionStateStore.updateRegionLocation`.

Two final V2 healthy seeds, c and d, each pass the unchanged JUnit, evaluate
exact B5 as true, identify three distinct RegionServers, and verify
`INITIAL_OWNER==SOURCE_RS`. They take 51.67 s and 57.51 s. The machine-readable
`independent/healthy_receipt_v2.json` records raw-log SHA-256 values, both
role maps, exact B5 outcomes, 8 common stable I/O sites, 11 common exact
selectors, per-seed candidate/exclusion counts, and event kinds. V2 ran in
node1 tmux `hbase17-v2-campaign` with `checkpoint_v2.json`,
`trial_ledger_v2.json`, `logs_v2`, 80 effective target-retaining trials,
maximum eight ordered faults, 180 attempts, and an 11,000-second wall cap.
It naturally stopped at 115 attempts and 80 effective trials; its tmux and
JUnit JVM have exited. The final raw-actor audit proves all 86 strict
injections and 80 effective trials, with zero identity errors. The unchanged
original JUnit passed in 110 attempts; two failed only after a direct injected
META write failure aborted the master before B5, and three target-lost runs
were stopped after bounded observation. No selected B5 `AssertionError` or
JUnit failure after a final fault followed by B5 was observed. The campaign
found no confirmed new bug for HBASE-17.

V2 production JaCoCo coverage grew by one method, 27 branches, and 72 lines
over its two-seed union; stable I/O sites grew from 11 to 17. Its last 20
trials added neither new production coverage nor a stable I/O site, so the
conditional 128-trial extension was not activated. The V2 trial time totals
6,573.01 seconds; `result.json` separately preserves the earlier
coarse-identity/calibration time and reports 9,883.27 seconds across all
HBASE-17 work. Each V2 trial's exact plan, timing, JUnit, and target outcome
is in `independent/trial_ledger_v2.json`; complete analysis is in
`independent/v2_source_review.md`. The legacy phase remains separate and
does not enter the 80-trial V2 denominator.

All 115 original JUnit trial logs and JaCoCo `.exec` files, final checkpoint,
ledger, healthy receipt, and actor audit are archived in
`independent/evidence/v2-archive/hbase17-v2-r001-r115.tar.gz` (6,926,939
bytes; SHA-256
`9fbbe89b6a15e7c12601a4bf935b97559c270477b5c8dd50a6c0bfb763e0c92a`).
`independent/evidence/v2-archive/manifest.json` records its contents and
verification. The archive was compressed on node1 and mirrored to node0;
node0 retains more than 2 GiB free disk space.

The earlier `TestProcDispatcher.testRetryLimitOnConnClosedErrors` proof below
is preserved but excluded from the active workload. Six later unchanged-JUnit
calibrations all passed in 58.42–61.60 seconds but reached B5 in 0/6 runs.
Two full-overlay pilots failed their original 5-second wait without reaching
B5, and a 3.25-second wrong-method selector launch never executed a test.
These are setup/calibration evidence and contribute zero fault trials.

## One-off TestProcDispatcher reachability proof

The unchanged original `TestProcDispatcher.testRetryLimitOnConnClosedErrors`
reached the exact guard once in a three-RegionServer MiniCluster. It installs
HBase's test `RSProcDispatcher`, which deliberately returns an RPC error after completing
some `executeProcedures` calls and exercises server-crash recovery. Thus the
run below is a **zero additional fault seed**, not a fault-free execution of
the production protocol. The production `RegionStateStore` log records a
region becoming `ABNORMALLY_CLOSED`; the case-local runtime advice then
observes `confirmClosed` enter in that state and evaluate the selected
`isInState(ABNORMALLY_CLOSED)` assertion once, with result `true`.

| Original JUnit | Wall time | JUnit | `confirmClosed` | Exact B5 |
| --- | ---: | --- | --- | --- |
| `TestProcDispatcher.testRetryLimitOnConnClosedErrors` | 55.03 s | 1 passed, 0 failed | 4 entries: 3 CLOSED, 1 ABNORMALLY_CLOSED | 1 evaluation, true, no AssertionError |

The full log is `node1:cases/HBASE-17/independent/proc_dispatcher_healthy2.log`,
also archived as `independent/proc_dispatcher_healthy2.log.gz`. Its raw
SHA-256 is `db8af35507ae6cc5f085a193b694eaf155eb4cf57372a528061bdcee0a6a860c`.
Relevant lines are 3701 (production META state write), 3712–3716
(target entry, exact B5 evaluation, normal return), and 4539–4542
(JUnit and time). The first launch failed method discovery before running a
test because the old runner did not supply the original JUnit method's
`TestInfo` parameter. The case-local `NativeJUnit17` selector fixes method
discovery without editing the test. This failed launch took 1.84 s and is
excluded from the 55.03 s measured seed.

The prior five-test audit below remains historical evidence for those five
methods only. The one-off proof motivated full instrumentation calibration,
but six later unchanged-JUnit calibrations did not reach B5. This method is
therefore excluded from the active fault campaign; the stable original
`TestReportRegionStateTransitionFromDeadServer.test` above is its workload.

## Earlier five-test audit

Target: HBase 2.6.6 `TransitRegionStateProcedure.confirmClosed`, line 379,
`assert regionNode.isInState(State.ABNORMALLY_CLOSED)`. The selected outcome is
`AssertionError` with assertions enabled. The audited HBase source checkout is
`badd7a2818`; the test JVM used `-ea` and the original JUnit methods in the
unmodified HBase test JAR. The local ByteBuddy agent observes `confirmClosed`
entry and state without GraphChecker or a graph.

The source has two earlier branches: `CLOSED` returns from `confirmClosed`;
`CLOSING` throws `HBaseIOException` for a retry. Only an invocation in another
state can evaluate the selected line 379 assertion. Entering `confirmClosed`
alone therefore does **not** count as reaching HBASE-17.

| Original JUnit method (assignment package) | Cluster scenario | Wall time (s) | JUnit | `confirmClosed` entry states | Exact guard reach |
| --- | --- | ---: | --- | --- | --- |
| `TestRaceBetweenSCPAndTRSP.test` | Move races server crash | 38.24 | passed | 1 × `CLOSED` | no |
| `TestSCPGetRegionsRace.test` | Move races server crash region listing | 44.39 | passed | 1 × `CLOSED` | no |
| `TestCloseRegionWhileRSCrash.testRetryBackoff` | Close retry, server crash and master restart | 64.32 | passed | 5 × `CLOSING` | no |
| `TestTransitRegionStateProcedure.testRecoveryAndDoubleExecutionUnassignAndAssign` | Replay unassign and assign procedures | 39.01 | passed | 3 × `CLOSED` | no |
| `TestRegionMoveAndAbandon.test` | Moves, server failures and master restart | 54.65 | passed | 2 × `CLOSED` | no |

The first four logs used the entry observer only. The fifth included an
`isInState` advice, but it reported zero calls: its `exactB5=0` counter is
**not** evidence. Its typed advice argument loaded `RegionStateNode` before
ByteBuddy installed that transform. After changing the advice argument to
`Object`, two replays of `TestRaceBetweenSCPAndTRSP.test` passed in 39.60 s and
39.04 s. The fixed advice observed 30 and 31 `isInState` calls respectively,
zero expecting `ABNORMALLY_CLOSED`, and zero exact B5 calls. One intermediate
replay's optional state-description reflection failed; the final replay
printed `state=CLOSED` successfully. The five-test reachability conclusion
rests on the recorded entry states and source branch order, with the fixed
replays validating the direct guard observer. Total measured JUnit time was
319.25 s (240.61 s across the five distinct tests plus 78.64 s validation).

No injection was performed during this earlier five-test audit because none
of these five methods reached the target guard. The later
`TestProcDispatcher` result above supersedes its overall reachability
classification.

The full run logs are in `node1:/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-17/independent/`
under `race_healthy.log`, `scp_race_healthy.log`, `close_rs_healthy.log`,
`double_exec_healthy.log`, and `abandon_healthy.log`; replays are
`race_probe_valid.log` and `race_probe_final.log`. The case-local runner and
observer are in `independent/run.sh` and `independent/src/HBase17TargetAgent.java`.
