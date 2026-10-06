# HDFS-39: committed block during append

The Hadoop 3.4.3 check in `FSDirAppendOp.appendFile` throws
`RetriableException(NotReplicatedYetException)` when the last block is
`COMMITTED` but not yet `COMPLETE`. This comes after lease recovery in the
function. The originally proposed `TestFileAppend#testAppendTwice` uses one
DataNode: its second append is intentionally rejected as
`AlreadyBeingCreatedException` by the active lease, before this block-state
check can decide the second request.

The original `TestFileAppend#testMultipleAppends` is a stronger alternate
healthy workload to calibrate. It starts four DataNodes, enables closing
with one committed block, and repeatedly appends and closes a file. This may
expose the selected block-state transition while preserving an original
embedded-cluster JUnit. No target hit or fault result is claimed until a
case-local runtime probe confirms the exact guard visit. The related
[HDFS-40](../HDFS-40/README.md) checks replication after a complete block.
