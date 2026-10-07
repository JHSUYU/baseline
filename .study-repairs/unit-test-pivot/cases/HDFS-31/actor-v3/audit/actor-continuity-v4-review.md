# HDFS-31 V4 actor-continuity boundary review

The original `TestDiskError#testDataTransferWhenBytesPerChecksumIsZero`
campaign reached a complete JUnit boundary at 21 plans, 16 effective under
the legacy V3 raw-UUID rule. The first 20 plans had 15 effective. Neither
count was recalculated. The original 21-run state SHA is
`d5afe9d4863eed4bbae0d859b36d90de85566f4eebc776fa7a675dc92e312692`.
The frozen archive contains 254 SHA-verified files; its SHA is
`601faffbc1616c15b2a5939bc4c9ffa1074816a3dde62e2580d6ea66dd98434d`.
The archive was restored and all 254 hashes independently checked on node1.

The selected source is `DataNode.getBPOSForBlock(ExtendedBlock)` at Hadoop
3.4.3 line 1832, before the potential throw at line 1835. The producer is
`Client.getRpcResponse(Connection)` bound to the raw NN0 endpoint. The probe
registers the actual `DataNode` object before its BP actor starts, records
the `BPServiceActor.run` service object, and traces `POOL_ADD`, transfer, and
selected target events. The original source/JUnit remains unchanged.

Three legacy trials applied the fault before Hadoop assigned a DataNode UUID.
Their UUID was `null` at fault time and assigned by the time the same object
reached the selected target. V3 recorded each as strict but not effective;
the target was observed after the fault in all three:

| Plan | Fault seq | Target seq | Actor/object/service | Legacy credit | V4 hypothetical credit |
| --- | ---: | ---: | --- | ---: | ---: |
| `535ec888f9d97608d01c` | 6 | 81 | episode1/dn1/object1/service1 | 0 | 1 |
| `d877cce0ebaf8909bfc2` | 6 | 82 | episode1/dn1/object1/service1 | 0 | 1 |
| `f1e1d3c9207d03f7ca57` | 6 | 85 | episode1/dn1/object1/service1 | 0 | 1 |

V4 requires a unique registration and actor-enter event before the fault,
with the same episode, physical DataNode object, BP service and raw NN
endpoint. It rejects a later actor-enter/replacement and requires the same
object/service `POOL_ADD` before selected target credit. This proof is applied
even if the raw UUID strings match. Negative controls changing each of
episode, object, service, or NN endpoint are rejected by both the controller
and independent auditor, including controls with deliberately equal UUIDs.
The complete controls and raw sequence values are in
`actor-continuity-v4-offline-audit.json`.

The atomic migration wrote `identity_rule_migration.boundary_completed=21`;
completed IDs, queue IDs, old results and effective count were unchanged.
The migrated state SHA is
`0ae5046cc719e19ba47360a010af8fd1daea448db335f2199f30dd9d817ecfcc`.
The independent raw auditor still reported 21 strict, 16 effective, zero
issues. The first new V4 plan `d4df81852dcd1c3c0bfc` then ran the original
JUnit for 16.565 seconds, passed, injected three ordered RPC exceptions, and
reached the same actor target after the last fault; zero selected target
exceptions. The independent audit reported 22 strict, 17 effective, zero
issues. Its complete checkpoint SHA is
`b9f50e2afe6024132623d69980b3da33e0c23593efa500c28ae1256b67b9df1e`.
The remaining budget continues from that checkpoint in the node2 tmux
`hdfs31_actor_v4_budget`, with shared JVM lock, Java-before at most four, and
at least 10 GiB free disk required for each new JUnit.
