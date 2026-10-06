# HDFS-31: block-pool offer service lookup

The selected Hadoop 3.4.3 check is `DataNode.getBPOSForBlock`: it uses the
requested block's pool ID to look up a `BPOfferService` in
`blockPoolManager` and throws `IOException` if absent.

The mapped original embedded-cluster
`TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` starts with one
DataNode, writes a block, corrupts its checksum metadata, then starts a
second DataNode and calls `dn0.transferBlock(block, ...)`. The implementation
of `transferBlock` calls `getBPOSForBlock` before inspecting the damaged
replica, so this is a source-grounded route to the target lookup. A healthy
case-local runtime probe must still establish the exact pool ID, DataNode
identity, guard outcome, and observed target-before I/O before fault trials
count. HDFS-32's repaired non-throwing event recorder can be reused as code,
but its trial outcomes cannot be transferred to this check.
