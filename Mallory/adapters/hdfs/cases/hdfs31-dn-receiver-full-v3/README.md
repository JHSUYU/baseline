# HDFS-31 DataNode receiver fault campaign

This isolated package runs Hadoop 3.4.3's original
`TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` in `MiniDFSCluster`.
The target is the `DataNode.getBPOSForBlock` null check at `DataNode.java:1833`
on the original `dn0`. The source and loaded target class are pinned by SHA.

The sealed v2 healthy JUnit passed 1/0/0 in 14.82 seconds. It observed the
exact check at trace sequence 139 on `hdfs-cluster-1/dn0` and the typed
`BPServiceActor.sendHeartBeat` RPC door at sequence 20 on that same actor.
Hadoop catches ordinary `IOException` from that heartbeat in
`BPServiceActor.offerService` and retries. This is a concrete I/O door with a
plausible target-retaining fault effect. The healthy trace also has 28 other
pretarget automatic I/O doors; the campaign records their effects separately.

An ordinary heartbeat `IOException` does **not** itself delete the local
block-pool mapping. The selected null branch needs `BlockPoolManager.remove`
after the last service actor shuts down, a nameservice refresh, or a block
whose pool ID is absent from the map. The original test does not explicitly
perform those operations after creating the block. Consequently, the fault
campaign can complete without an exact target exception, and an exception
candidate requires source review before any bug claim.

The budget is 80 fault trials or 3600 seconds, whichever occurs first, with
at most three exception faults in a sequence and a 240-second trial timeout.
The controller may naturally finish at `queue_exhausted`; it records each
fault's match, application, target retention, coverage, and exact target
throw independently. It uses the patched receiver adapter from the v2
package and a new output directory, so the previous healthy run is not
modified. A campaign may be resumed using its checkpoint.

Run `python3 -B preflight.py --static` on node0 for the no-JVM check. Dispatch
may run `MALLORY_DISPATCH_ADMITTED=1 ./run_full.sh` on node2 after lane
admission. The runner takes the shared HDFS lock. This package has not run
the HDFS JUnit or a fault trial.
