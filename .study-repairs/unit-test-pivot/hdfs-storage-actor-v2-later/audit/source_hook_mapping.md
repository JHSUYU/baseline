# HDFS storage V2: remaining original tests and target identity

Offline source audit against Hadoop `rel/release-3.4.3` at
`/users/ZhenyuLi/hdfs32-independent-source`. No cluster JVM was started for
this audit. The later-group overlay has its own digest
`a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`;
the running startup campaign retains its earlier calibrated digest.

| Case | Original JUnit workload | Exact target in production source | Expected healthy behavior to record |
| --- | --- | --- | --- |
| HDFS-24 | `TestDFSUpgrade#testUpgrade` (line 225) | `BlockPoolSliceStorage.doTransition`, lines 414–415: stored block-pool layout version and cTime compared with software layout and NameNode `NamespaceInfo` | The test loops over one and two storage directories and deliberately includes invalid upgrade states. Legacy healthy trace contains three target throws. Two V2 healthy seeds must establish exact actor/storage/exception signatures before classifying a faulted throw. |
| HDFS-27 | `TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout` (line 42), through `TestDFSUpgradeFromImage.upgradeAndVerify` | `BlockPoolSliceStorage.doUpgrade` line 510: `assert this.namespaceID == nsInfo.getNamespaceID()` | The configured DataNode directory is `dfs/data`, not `dfs/data1`. With `-ea`, a failing check throws `AssertionError`. The current source first records the exact operands and then records a throw at that assertion; two V2 healthy seeds must show a bound `StorageDirectory` actor after the asynchronous callable handoff. |
| HDFS-26 | `TestDFSRollback#testRollback` (line 139) | `BlockPoolSliceStorage.doRollback`, lines 618–620: previous block-pool layout version and cTime versus software and NameNode namespace time | The JUnit deliberately creates valid and invalid previous states. The old healthy trace has no throw at this exact block-pool guard. |
| HDFS-37 | The **same** `TestDFSRollback#testRollback` JUnit | `DataStorage.doRollback`, lines 939–941: previous DataNode volume layout version and cTime versus software and NameNode namespace time | The old healthy trace contains three target throws here, arising from intended invalid rollback subtests. It is a distinct target, storage level, and identity from HDFS-26 even though the workload is shared. |

`MiniDFSCluster.startDataNodes` defines a startup episode. Its synchronous
`DataNode` construction registers an actor using the configured directories
and slot; `BPServiceActor.run` adopts that registered object and its raw
NameNode address. The file hook uses the exact `StorageDirectory` volume;
the RPC hook accepts only the actor's NameNode endpoint. A sequence is
eligible for a target only if its preceding fault point has that same actor
and either the same storage volume or the actor's `NN0` endpoint. Missing
actor, directory, or endpoint identity fails calibration and trial matching.

For HDFS-27, `BlockPoolSliceStorage.doUpgrade` first receives `bpSd` on the
actor thread and can enqueue a `Callable<StorageDirectory>` that later calls
the overload containing the assertion. The V2 `StorageDirectory` identity
map binds `bpSd` before enqueue and rejoins the same object at the overload
entry. It clears any previous executor-thread actor when no object binding
exists; a thread name or path suffix is not accepted as a substitute.

The bytecode weaver checks the expected branch hooks and one throw hook at
each target. Its offline smoke test verifies the patched class
shapes. Runtime proof remains pending: each group needs two original healthy
JUnit seeds with a stable exact selector, actor/storage target receipt,
JaCoCo coverage, and matching overlay digest before fault trials begin.
