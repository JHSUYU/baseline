# ZOOKEEPER-04: client zxid ahead

> **Actor identity recheck pending.** The earlier I/O fault selector used a global call-site ordinal and did not bind the peer/client/socket or file owner. Its raw trials, coverage, and elapsed time are preserved as historical selector-level evidence in `result.json`, but are excluded from the current actor-matched budget. See [independent audit](../../audits/zookeeper-terminal-actor-identity-2026-10-07.md).

**Current campaign status: quality_complete.** The independent recorder replay below completed 80 new fault trials. The 29 trials in the historical section remain legacy evidence and are excluded from the current counts: 25 used a GraphChecker JAR for the JUnit lifecycle and four were independent continuations of that older campaign. The current result is in `result.json`; the historical result is in `legacy-graph-result.json`.

## Independent recorder replay

The unchanged ZooKeeper 3.8.7 `ConnectionMetricsTest.testRevalidateCount` passed under a pure JUnit Platform launcher and a rebuilt case-local ASM agent. Its healthy run took 16.192 seconds, evaluated the exact `ZooKeeperServer.processConnectRequest` guard at line 1431 twice on the normal arm, and did not reach the line 1441 `CloseRequestException(CLIENT_ZXID_AHEAD)` throw. The original `ZooKeeperServerTest.testClientZxidAhead` positive control passed and recorded one throw-arm guard and one exact selected throw. The test code and production bytecode came from original commit `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`; the independent JVM classpath, case-local agent, and pure JUnit launcher contain no GraphChecker or skeleton component. The per-JVM classpath and JAR hashes are checked in `evidence/independent-audit.json`.

The new campaign completed 80 original-JUnit fault trials under an 8-fault cap. All 80 matched and applied their entire ordered selector sequence, totaling 512 applied faults; 74 trials reached the same exact target guard after the final fault, with sequences up to depth 8. None reached the selected throw. Six single-fault trials injected `IOException` at `QuorumPeer.readLongFromFile` while the quorum was starting; their JUnit runs failed before the target guard and do not qualify as target-retaining trials. The other 74 JUnit runs passed. Every completed trial and elapsed time appears in `evidence/independent-trial-summary.csv`, and the full ordered plans, event-derived verdicts, and raw traces appear in `evidence/independent-trials.jsonl` and `evidence/zk04-independent-raw-runs.tar.gz` (SHA-256 `50567206a1a3d2dbc337dcddc7f7f5d2950a8c4a026aeb79d56d1e9b8a735934`). The fault JVMs took 1946.423 seconds in aggregate and 980.401 seconds of wall time across two workers; including the healthy and positive-control JVMs, the recorded total is 1967.825 seconds.

The 4 admitted new production lines are `ClientCnxnSocketNIO.doIO:76-77` (socket read EOF handling) and `ClientCnxn.SendThread.run:1293,1298` (exception handling and reconnect). They appeared in target-retaining runs and are consistent with injected client I/O failures. No new production line, method, or stable I/O family appeared in the final eight valid runs, so the conditional 128-trial extension was not triggered. The recorder observed 26 distinct target-pre I/O site and ordinal positions. At the 80-trial ceiling, 35 feedback-generated plans remained queued, so this is a budget-complete result, not selector-frontier exhaustion. Raw-event audit independently recomputed all 80 strict and target-retaining verdicts, all selected throw counts, and all coverage gains. No new target exception or source-supported bug was found.

## Historical campaign

The selected check is the `LCMP@283; IFLE@284` guard at ZooKeeperServer.java:1431. Its selected throw is `ATHROW@376` at line 1441, constructing `CloseRequestException(CLIENT_ZXID_AHEAD)`. This rejection is protective and expected when a client has seen a zxid newer than the server DataTree.

The unchanged original `ConnectionMetricsTest.testRevalidateCount` starts three peers and reconnects the same client from one follower to another. The healthy JUnit passed in 13.408 seconds; the exact guard was evaluated twice, both on its normal arm; the selected throw was absent. The healthy trace recorded 772 line-coverage items and 3 direct I/O sites.

The original `ZooKeeperServerTest.testClientZxidAhead` was run as a positive control (2.420 seconds, JUnit pass). It deliberately sends zxid 99 to a mock connection and asserts `CLIENT_ZXID_AHEAD`; this probe recorded one selected throw-arm guard and one exact selected throw.

A case-local ASM agent instruments the bytecode guard and throw, direct client TCP read/write calls, epoch-file read calls, and production line coverage. Each injected `IOException` is selected by exact call site plus global hit ordinal, with separate matched/applied events. The historical 25 attempts used a legacy GraphChecker JAR solely for the JUnit lifecycle. The four 5–8 fault continuation runs used a case-local JUnit Platform runner with no GraphChecker or skeleton on the JVM classpath. No graph, static analysis, aggregation, or closure result controlled test selection or faults.

| Trial | I/O site and ordinal | Seconds | Matched/applied | Target after fault | Exact throw | New coverage | New I/O sites | Bug |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| trial-01 | `write` #1 | 15.011 | 1/1 | yes | 0 | 0 | 0 | none |
| trial-02 | `read` #1 | 14.418 | 1/1 | yes | 0 | 0 | 0 | none |
| trial-03 | `read` #2 | 15.463 | 1/1 | yes | 0 | 0 | 0 | none |
| trial-04 | `write` #2 | 14.457 | 1/1 | yes | 0 | 0 | 0 | none |
| trial-05 | `read` #3 | 14.907 | 1/1 | yes | 0 | 0 | 0 | none |
| trial-06 | `write` #3 | 13.909 | 1/1 | no | 0 | 0 | 0 | none |
| trial-07 | `read` #4 | 15.167 | 1/1 | yes | 0 | 0 | 0 | none |
| trial-08 | `read` #5 | 14.375 | 1/1 | no | 0 | 2 | 0 | none |
| trial-09 | `read` #6 | 13.056 | 1/1 | no | 0 | 2 | 0 | none |
| trial-10 | `read` #7 | 13.762 | 0/0 | no | 0 | 0 | 0 | none |
| trial-11 | `<init>` #1 | 1.920 | 1/1 | no | 0 | 0 | 0 | none |
| trial-12 | `<init>` #2 | 2.326 | 1/1 | no | 0 | 0 | 0 | none |
| sequence-01 | `write#1+write#2` #1+2 | 13.011 | 0/0 | no | 0 | 0 | 0 | none |
| sequence-02 | `write#1+read#1` #1+1 | 13.703 | 0/0 | no | 0 | 0 | 0 | none |
| sequence-01b | `write#1+write#2` #1+2 | 16.720 | 2/2 | yes | 0 | 0 | 0 | none |
| sequence-02b | `write#1+read#1` #1+1 | 16.820 | 2/2 | yes | 0 | 0 | 0 | none |
| sequence-03b | `write#1+write#2+write#3` #1+2+3 | 18.365 | 3/3 | yes | 0 | 0 | 0 | none |
| sequence-04b | `write#1+write#2+write#3+write#4` #1+2+3+4 | 19.318 | 4/4 | yes | 0 | 0 | 0 | none |
| epoch-03 | `<init>` #3 | 1.970 | 1/1 | no | 0 | 0 | 0 | none |
| epoch-04 | `<init>` #4 | 1.769 | 1/1 | no | 0 | 0 | 0 | none |
| epoch-05 | `<init>` #5 | 1.919 | 1/1 | no | 0 | 0 | 0 | none |
| epoch-06 | `<init>` #6 | 2.071 | 1/1 | no | 0 | 0 | 0 | none |
| retry-read-07 | `read` #7 | 13.505 | 1/1 | no | 0 | 0 | 0 | none |
| feedback-01 | `write#1+write#2+write#3+write#5` #1+2+3+5 | 20.333 | 4/4 | yes | 0 | 0 | 0 | none |
| feedback-02 | `write#1+write#2+write#4+write#5` #1+2+4+5 | 20.535 | 4/4 | yes | 0 | 0 | 0 | none |
| budget5-01b | `write#1+write#2+write#3+write#4+write#6` #1+2+3+4+6 | 21.539 | 5/5 | yes | 0 | 0 | 0 | none |
| budget6-01 | `write#1+write#2+write#3+write#4+write#6+write#7` #1+2+3+4+6+7 | 23.480 | 6/6 | yes | 0 | 0 | 0 | none |
| budget7-01 | `write#1+write#2+write#3+write#4+write#6+write#7+write#8` #1+2+3+4+6+7+8 | 26.397 | 7/7 | yes | 0 | 0 | 0 | none |
| budget8-01 | `write#1+write#2+write#3+write#4+write#6+write#7+write#8+write#9` #1+2+3+4+6+7+8+9 | 25.246 | 8/8 | yes | 0 | 0 | 0 | none |

The table and `result.json` are rewritten after each completed run. Full logs and trace files are in `/users/ZhenyuLi/zk04-runs/`; the compact machine-readable record is `evidence/trials-summary.json`.

## Eight-fault continuation

The four new runs resumed the saved 25-attempt ledger without replaying it. Each used the unchanged original three-peer JUnit and passed: the 5-, 6-, 7-, and 8-fault plans matched/applied all 5/5, 6/6, 7/7, and 8/8 selectors, respectively. Their elapsed times were 21.539, 23.480, 26.397, and 25.246 seconds. Each retained an exact target guard after its final fault. None reached the selected `CLIENT_ZXID_AHEAD` throw or added production line coverage. The cumulative ledger contains 29 completed attempts, 26 strict trials, 61 matched/applied faults, and 16 target-retaining strict trials. Two client cleanup lines in prior late-fault runs are the only observed coverage gain; admitted target-retaining gain is zero.

The final direct-I/O feedback audit examined the healthy seed and all 29 completed trial traces. It found 20 distinct `(call site, global ordinal)` occurrences before a later target guard. Nineteen were faulted exactly. The remaining client TCP write ordinal 10 occurred before a later guard only after eight earlier applied faults; selecting it requires a ninth fault beyond the current cap. No new direct I/O site family appeared. This is the scoped equivalence-exhaustion reason for ending below the 128-trial ceiling. The ninth-fault path, uninstrumented I/O, and other schedules remain untested. The source guard is `ZooKeeperServer.java:1431` and its protective throw is line 1441. The original cluster test at `ConnectionMetricsTest.java:53–85` performs no acknowledged write before changing followers; the original mock positive control deliberately asserts the protective exception.

`evidence/provenance-8fault.json` verifies the actual classpaths of all four continuation JVMs and inspects the ASM agent and independent runner source/JAR for GraphChecker or skeleton references; all checks passed. An initial pure-JUnit setup process (`budget5-01`) completed its JUnit test but failed to exit while ZooKeeper background threads remained alive. It was stopped and excluded from the completed-trial ledger; the runner was corrected before `budget5-01b`. The case-local source checkout is ZooKeeper commit `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae` at `/users/ZhenyuLi/zk04-unit`; the already built 3.8.7 class files were reused read-only. The sum of completed case-local JVM run times is 488.305 seconds, excluding manual review and idle time.
