# HDFS-32: typed heartbeat exploration

This isolated package runs the original Hadoop 3.4.3 `MiniDFSCluster` test
`TestDeleteBlockPool#testDfsAdminDeleteBlockPool`. It selects the exact
`DataNode.deleteBlockPool` guard at `DataNode.java:3819` and its
`IOException` at line 3822. A prior healthy run on node2 passed one JUnit
test and reached the guard twice on named `hdfs-cluster-1/dn0`.

The sole configured fault door is
`BPServiceActor.sendHeartBeat` at line 563, throwing a typed
`java.io.IOException` on `hdfs-cluster-1/dn0`. The actor catches this
exception in `offerService` and retries. This is a target-retention
exploration. There is **no source proof** that a heartbeat fault changes
`BlockPoolManager.bpByBlockPoolId`, which is the selected guard's input.
In particular, this package must not claim that an exact target exception
is expected or that a healthy target occurrence after a fault proves a bug.

The client `DFSAdmin.deleteBlockPool` RPC door from the older package is
excluded. A fault there can prevent the current server call entirely; the
test already expects its first unforced delete to fail. Broad automatic
I/O doors are disabled so the queue contains the one typed source-backed
site. The 80 trial, 3600 second, three fault budget is a cap; exhaustion
of the finite replay queue may end the campaign earlier. Per-trial target
retention and graph paths remain measured outcomes. A fault that removes
all target occurrences does not spawn child sequences.

`preflight.py --static` checks a source-equivalent local mirror without
running Java. Runtime execution is reserved for dispatch on node2 under
`MALLORY_DISPATCH_ADMITTED=1`; `run_full.sh` takes the shared node2 HDFS
lock and resumes only with a byte-identical config and checkpoint.
