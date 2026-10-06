# ZOOKEEPER-04: client zxid ahead

**Current campaign status: pending independent recorder replay.** The 29 trials below are preserved as historical evidence. The first 25 used a GraphChecker JAR for the JUnit lifecycle, and the final four were independent continuation runs. Because the current baseline requires every counted run to use an independent recorder and original JUnit, none of these 29 are counted toward its new budget. The current result is in `result.json`; the full historical result is in `legacy-graph-result.json`.

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
