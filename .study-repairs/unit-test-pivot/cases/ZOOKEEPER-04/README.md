# ZOOKEEPER-04: client zxid ahead

The selected check is the `LCMP@283; IFLE@284` guard at ZooKeeperServer.java:1431. Its selected throw is `ATHROW@376` at line 1441, constructing `CloseRequestException(CLIENT_ZXID_AHEAD)`. This rejection is protective and expected when a client has seen a zxid newer than the server DataTree.

The unchanged original `ConnectionMetricsTest.testRevalidateCount` starts three peers and reconnects the same client from one follower to another. The healthy JUnit passed in 13.408 seconds; the exact guard was evaluated twice, both on its normal arm; the selected throw was absent. The healthy trace recorded 772 line-coverage items and 3 direct I/O sites.

The original `ZooKeeperServerTest.testClientZxidAhead` was run as a positive control (2.420 seconds, JUnit pass). It deliberately sends zxid 99 to a mock connection and asserts `CLIENT_ZXID_AHEAD`; this probe recorded one selected throw-arm guard and one exact selected throw.

A case-local ASM agent instruments the bytecode guard and throw, direct client TCP read/write calls, epoch-file read calls, and line coverage. Each injected IOException is selected by exact call site plus hit ordinal, with separate matched/applied events. The original JUnit lifecycle runner is supplied by a legacy GraphChecker JAR; no graph, static analysis, aggregation, or closure result controls test selection or faults.

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

The table and `result.json` are rewritten after each completed run. Full logs and trace files are in `/users/ZhenyuLi/zk04-runs/`; the compact machine-readable record is `evidence/trials-summary.json`.

## Feedback and stopping point

The 25 trial attempts produced 35 exact matched/applied exceptions in 22 strict runs. Twelve strict runs evaluated the selected guard after their final fault. None took the throw arm. The two new line-coverage items were client cleanup lines 1398–1399 in late read-fault runs; both faults occurred after the last target guard, so admitted target-preserving coverage gain is zero. No new direct I/O site family appeared. The original test has no acknowledged client write before the follower switch, which limits its ability to produce a client zxid ahead of the second server. Fault-induced JUnit failures and the intentional positive-control exception are not marked as bugs.

The runtime feedback audit examined the healthy seed and all 25 trial traces. It found 16 distinct direct I/O `(call site, global hit ordinal)` occurrences before a later target guard. Fifteen were faulted with exact matching, including all six observed epoch-file opens. Every epoch-open fault prevented quorum startup and reached no target after the fault. The remaining occurrence is client TCP write ordinal 6. It appeared before a later guard only in runs with four earlier applied write faults; selecting it would require a fifth fault, beyond the four-fault sequence cap. The 2-, 3-, and 4-fault plans and two feedback plans all matched completely and kept a target guard after their final fault. This is the bounded I/O-equivalence stopping evidence for ending below the default 48-trial ceiling. It does not exclude uninstrumented I/O or other schedules.

Two initial sequence attempts matched zero faults because the first selector-list delimiter conflicted with the semicolon in Java method descriptors. They remain in the table as unmatched attempts; the corrected delimiter was then used for all six exact sequence runs. A late client read ordinal 7 was absent on its first replay and matched on retry, but both observations place it after the target guard.

Source checkout: ZooKeeper commit `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae` in `/users/ZhenyuLi/zk04-unit`. The JVM used previously built 3.8.7 class files from `/tmp/zk387-unit-smoke-20261006` read-only and isolated test-data/output directories under `/users/ZhenyuLi/zk04-runs`. The case-local agent source, final JAR, scripts, per-trial summary, and `evidence/feedback-audit.json` are archived here. All executions ran on node0 under isolated tmux sessions.
