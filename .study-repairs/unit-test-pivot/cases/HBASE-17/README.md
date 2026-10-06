# HBASE-17: original cluster-test reachability audit

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

No injection was performed because none of these original cluster tests
reached the target guard before faults. This is a test-reachability gap in the
five tested methods, not a negative bug finding or a completed fuzz campaign.

The full run logs are in `node1:/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-17/independent/`
under `race_healthy.log`, `scp_race_healthy.log`, `close_rs_healthy.log`,
`double_exec_healthy.log`, and `abandon_healthy.log`; replays are
`race_probe_valid.log` and `race_probe_final.log`. The case-local runner and
observer are in `independent/run.sh` and `independent/src/HBase17TargetAgent.java`.
