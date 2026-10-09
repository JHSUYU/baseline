# HDFS-28/29/30 workload provenance

All three selected checks have **two distinct original JUnit workloads** in
their evidence history. Their denominators must be reported by phase.

| Evidence phase | Original JUnit method | Scope |
| --- | --- | --- |
| Historical RPC pilot and `phase-v4` | `org.apache.hadoop.hdfs.server.datanode.TestBlockRecovery2#testRecoveryTimeout` | The recovery-timeout MiniDFSCluster path; phase-v4's 128 attempts and target reach counters are historical. |
| HDFS-30 `ha-control-v1` supplement | `org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization` | 3 NN/3 DN, 24 completed attempts in a separate bounded control run. |
| Current `ha-effective-v2` | `org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization` | 3 NN/3 DN, two fresh healthy calibrations, independent effective denominator for each of HDFS-28/29/30. |

`phase-v4/healthy-file-phase/manifest.json` records the first method and
JUnit return code 0. The current `ha-effective-v2/healthy-a/manifest.json`
and `healthy-b/manifest.json` on node1 both record the second method and
return code 0 (manifest SHA-256 prefixes `4b5b7d43eba110a5` and
`978ff59d79170aac`). Every current fault trial has its own original-test
manifest, trace, JUnit log, JaCoCo data, and exact runtime actor/recovery
identity audit. The same original HA run can retain more than one selected
check; a valid sequence contributes to each case's denominator only if that
case's target occurs after the final exact fault on the same identity.

The case `result.json` files currently keep historical `cluster_test` as
`TestBlockRecovery2`. On terminal review, change the checklist-facing
`cluster_test` to the current HA method and retain `cluster_tests` plus
phase-specific `workload` and counts, so the new effective rounds are not
misattributed to the earlier JUnit.
