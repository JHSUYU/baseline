# HDFS-31 typed I/O admission

The existing TestDiskError#testDataTransferWhenBytesPerChecksumIsZero healthy
run passed one JUnit and reached the selected DataNode.getBPOSForBlock guard
once, nonthrowing, on named dn0 epoch 0. The pretarget dn0 heartbeat RPC
door was observed at sequence 20; another dn0 heartbeat at sequence 141 was
after the target at sequence 139.

The guard reads bpByBlockPoolId[block.getBlockPoolId()]. The test obtains
that block from the NameNode, corrupts its metadata file, starts another
DataNode, and directly calls dn0.transferBlock. Metadata writeByte and
writeInt exceptions abort this JUnit before the direct call. A heartbeat
IOException is caught and retried without removing the map entry. Replica
I/O in transferBlock occurs only after this guard. The reviewed typed I/O
sites therefore have no source-backed route to the selected null operand
while retaining the target.

The existing ../hdfs31-map-state-healthy-v3/ package is the next useful
healthy-only diagnostic: it would observe the exact map object, block-pool
key, and add/get state records on dn0. Its static preflight passes, but no v3
JVM trace exists. A matching sampled map version remains candidate evidence;
it does not establish a caught I/O fault that removes the entry. Dispatch can
schedule it after HDFS-48 v4 if operand identity is needed. No HDFS-31 fault
or full campaign is admitted by this receipt.

Run python3 -B check_offline.py to recheck all SHA pins, source ordering,
the archived healthy events, and the staged diagnostic without a JVM.
