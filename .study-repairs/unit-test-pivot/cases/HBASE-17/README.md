# HBASE-17: original cluster-test reachability audit

## New original test reaches the exact guard

The unchanged original `TestProcDispatcher.testRetryLimitOnConnClosedErrors`
is a suitable three-RegionServer MiniCluster test. It installs HBase's test
`RSProcDispatcher`, which deliberately returns an RPC error after completing
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
methods only. It no longer supports `no_cluster_test`. The case is reopened
for a graph-free coverage and I/O fault campaign with the newly mapped test.

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

The full run logs are in `node1:/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-17/independent/`
under `race_healthy.log`, `scp_race_healthy.log`, `close_rs_healthy.log`,
`double_exec_healthy.log`, and `abandon_healthy.log`; replays are
`race_probe_valid.log` and `race_probe_final.log`. The case-local runner and
observer are in `independent/run.sh` and `independent/src/HBase17TargetAgent.java`.
