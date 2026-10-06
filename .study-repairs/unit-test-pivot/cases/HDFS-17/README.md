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

This is a source/workload mapping, not a claimed execution result. The next
step is an independent healthy original-JUnit run with a case-local target
probe and production coverage. The healthy trace must prove the selected
guard is reached and identify stable block identity and pre-target I/O before
any fuzz trial is counted. Every accepted trial must apply its ordered
exceptions exactly and reach that same block's guard after the last fault.
