# HDFS-40: under-replicated complete block during append

The Hadoop 3.4.3 check in `FSDirAppendOp.appendFile` throws `IOException`
when the last block is complete and `BlockManager.isSufficientlyReplicated`
returns false. The latter compares live replicas with minimum storage and
the number of live DataNodes. The originally proposed
`TestFileAppend#testAppendTwice` uses one DataNode and its second append is
rejected earlier by the lease check; it is not yet proven to exercise the
selected replication condition.

An additional original embedded-cluster workload to calibrate is
`TestFileAppendRestart#testAppendWithPipelineRecovery`: it starts four
DataNodes, stops one, then appends and checks the contents after a NameNode
restart. `TestFileAppend#testMultipleAppends` also provides repeated append
attempts with four DataNodes. A case-local runtime probe must establish the
exact target guard and observed I/O before fault trials count. This is a
source review and workload mapping only; there is no new-bug claim.
