# HDFS-17 source and cluster-workload review

The selected guard is the `!storedBlock.isComplete()` precondition in
`BlockManager.StatefulBlockInfo`. This object is added to the `toUC` list while
the NameNode reconciles a DataNode block report: the NameNode's stored block
state and the DataNode's reported replica state meet at this check. Unlike a
direct input validation, the two values arise from different participants and
the NameNode's under-construction lifecycle. A fault campaign should verify
the same dynamic block at this guard, rather than treating any unrelated
`IllegalArgumentException` as a selected outcome.

The mapped original JUnit is
`org.apache.hadoop.hdfs.server.namenode.TestAddStripedBlocks#testAddUCReplica`.
Its `@Before` starts a `MiniDFSCluster` with `groupSize` DataNodes (the
erasure-coding policy's data plus parity units). The test creates an
under-construction striped block, sends incremental block reports, restarts
the NameNode, and then sends full block reports to check the reconstructed
under-construction replica list. The reported block paths and NameNode restart
provide natural file/RPC fault points to observe before the selected guard.

The source screening result is in [SCREENING.md](SCREENING.md). The selected
precondition is implied by the only predecessor branch in the released
source, under the NameNode write lock. This check is therefore excluded from
the ad hoc coordination fuzz queue; it is not counted as a successful full
fuzz campaign or as a discovered bug.

The unmodified released Hadoop 3.4.3 test now passes in an isolated fresh
directory: `testAddUCReplica` ran once with zero failures in 38.927 seconds.
Its `@Before` starts one NameNode and nine DataNodes. The original test
constructs a striped under-construction block, directly submits incremental
reports through the namesystem, restarts the NameNode, and then submits full
reports through `NameNodeRpcServer.blockReport`. The runner and manifest are
under `independent/`. This only proves the JUnit workload runs; the selected
`StatefulBlockInfo` guard was then observed by a case-local ASM probe. An
instrumented healthy run passed and recorded nine executions of that guard
for one stored striped block, all with `!storedBlock.isComplete() == true`.
It also observed 18 block-report RPCs across nine distinct DataNode UUIDs.
The probe assigns a per-run logical DataNode identity in first-observed order,
while retaining each physical UUID in the trace.

One diagnostic `IOException` at the first DataNode block-report RPC matched
and applied exactly. The original JUnit still passed, and all nine checks of
the same stored block executed after the fault with the precondition true.
JaCoCo recorded 13 new production probes and five new covered branch units
against the instrumented healthy run. The trial verifies the fault hook and
target reachability; the source implication, rather than this one trial,
supports the screening decision.
