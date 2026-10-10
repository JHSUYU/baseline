# HDFS-31/32 named healthy admission

These two case-local configurations run **one no-fault MiniDFSCluster JUnit
each**. They are staged for dispatch and have not started a JVM. Both use the
frozen fa5f core, 38658059 agent, 9d828a42 HDFS adapter, Hadoop 3.4.3 source
digest, and compiled `DataNode` target hash pinned in `manifest.json` and
`preflight.py`. The old calibrations failed during startup with an obsolete
agent `LinkageError`; they do not establish target reach.

| Case | Existing JUnit | Exact selected guard | Typed pretarget I/O candidates |
| --- | --- | --- | --- |
| HDFS-31 | `TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` | `DataNode.getBPOSForBlock`, null check at 1833 before `IOException` at 1835 | DataNode `BPServiceActor.sendHeartBeat` RPC `IOException`; test metadata `RandomAccessFile.writeByte` and `writeInt` `IOException` |
| HDFS-32 | `TestDeleteBlockPool#testDfsAdminDeleteBlockPool` | `DataNode.deleteBlockPool`, running-pool check at 3819 before `IOException` at 3822 | DataNode `BPServiceActor.sendHeartBeat` RPC `IOException`; `DFSAdmin.deleteBlockPool` client RPC `IOException` |

HDFS-31's method corrupts block metadata, starts another DataNode, then calls
`dn0.transferBlock` with an existing block. The source compares a DataNode
object with a UUID string while selecting the destination; its practical
effect and the exact target actor remain runtime questions. HDFS-32's method
removes nameservice 2 through `refreshNamenodes`, then expects a no-force
delete request to fail because files remain and a force request to pass. That
expected failure must not be confused with the selected running-pool guard.

The catalog doors are source and compiled-class candidates. No retained
I/O-to-guard state change has been established. Admission requires the actual
healthy JUnit to pass 1/0/0, reach the exact nonthrowing guard on a named
DataNode and epoch, validate the loaded target class/catalog, and observe at
least one eligible pretarget injectable I/O door. Graph path quality and a
fault-to-target causal gap are outcomes, not a reason to misclassify a
completed full budget. HDFS-31/32 full configs remain separate and unrun.

Run `python3 preflight.py --case HDFS-31 --static` (and HDFS-32) on node0 or
node2 to check SHA pins, exact source lines, class bytes, site file, and
Mallory's static config without Java. Dispatch may use
`MALLORY_DISPATCH_ADMITTED=1 ./run_healthy.sh HDFS-31` or HDFS-32 on an idle
node2 HDFS lane. The runner holds the shared lock and refuses a reused output
directory. A separate dispatch GO is required before any JVM launch.
