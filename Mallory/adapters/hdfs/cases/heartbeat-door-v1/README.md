# HDFS-19 and HDFS-20 source-only healthy handoff

`source-receipt.json` pins the Hadoop 3.4.3 source commit, target and JUnit
source/classes, prior v2 healthy evidence, the frozen agent, and the staged
heartbeat reply/command queue adapter. No JVM or fault trial was started for
this handoff. The two configs each allow one fault-free healthy calibration and
disable automatic campaign promotion.

| Case | Existing MiniDFSCluster JUnit | Explicit typed I/O door |
| --- | --- | --- |
| HDFS-19 | `TestDFSFinalize#testFinalize` | `BPServiceActor.blockReport` line 423, one `IOException` before the `DatanodeProtocolClientSideTranslatorPB.blockReport` call |
| HDFS-20 | `TestStandbyIsHot#testStandbyIsHot` | `BPServiceActor.sendHeartBeat` line 563, one `IOException` before the translator's `sendHeartbeat` call |

The prior v2 calibrations passed each selected JUnit (1 test, 0 failures or
errors), reached the exact check on named DataNodes, and recorded no selected
assertion throw. They recorded **zero doors in target closure**; those runs do
not prove the required I/O ancestry. The staged `heartbeat-v1` adapter adds
the concrete heartbeat response and block-report command queue joins. Its JAR
and source are pinned in the receipt, but it has not run with these JUnits.

`BPServiceActor.offerService` catches `IOException` from either RPC and
continues its service loop. A one-shot heartbeat exception should leave later
HDFS-20 heartbeat checks reachable. For HDFS-19, restrict a later pilot to a
pre-finalization block report: a failure on the sole command-bearing forced
report can consume the force flag and lose that phase's target. A later
`finalizeCluster`/`triggerBlockReports` phase is the candidate retained path.
Neither target retention nor a strict postfault path has been demonstrated.

Dispatch should admit the two healthy probes on isolated idle lanes only after
checking every runtime artifact hash. Require a passing JUnit, exact
nonthrowing target on a named DataNode, a woven explicit door, a matched
response path, and an offline root-free event-time audit. HDFS-19 also needs
the command queue submit/claim pair. A JUnit pass or target count alone is
insufficient to promote a fault campaign.
