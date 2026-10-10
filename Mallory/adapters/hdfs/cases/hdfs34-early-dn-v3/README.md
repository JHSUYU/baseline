# HDFS-34 early DataNode identity stage

The sealed v2 healthy JUnit passed 1/0/0 and reached the exact
`DataStorage.doTransition@739:branch:5` on four named DataNodes. Its explicit
`BPServiceActor.retrieveNamespaceInfo@260:door:1` `versionRequest` door was
also woven and observed four times, but each door event had `node=unknown`.
The subsequent RPC request events were already named `dn0`–`dn3`.
The v2 healthy archive SHA-256 is
`ab7b86d03d41db7915fb152988de599f990be30dba1cc8f5464e23fd740375ab`.

Hadoop 3.4.3 starts `BPServiceActor` in
`DataNode.startDataNode -> BlockPoolManager.refreshNamenodes` while
`MiniDFSCluster.startDataNodes` is still constructing the DataNode. The v10
adapter registered that DataNode only before the later
`runDatanodeDaemon` call. This isolated v11 adapter carries the concrete
MiniDFSCluster through `startDataNodes`, registers the DataNode and its
storage immediately before `refreshNamenodes`, and treats the existing later
registration as idempotent. The cluster scope restores on both normal and
exceptional exits. The `versionRequest` door and selected check remain the
same source and bytecode sites.

`source-receipt.json` pins the Hadoop source commit, full source digest,
input and transformed DataNode/MiniDFSCluster class hashes, local adapter
sources, adapter release, site file, and config. An offline classfile
transformation confirmed both entry/exit scope hooks and the pre-refresh
registration hook. `python3 -B preflight.py --static` passed on node0 without
starting Hadoop. The node2 operator should run `python3 -B preflight.py`
and, after dispatch admission and an idle HDFS lane,
`MALLORY_DISPATCH_ADMITTED=1 ./run_healthy.sh`.

This is **one healthy JUnit only**. Full fault injection remains on hold until
the fresh trace shows the typed `versionRequest` door on the same named
DataNode and epoch as the exact nonthrowing target, with a root-free
event-time causal path. An injected `IOException` is caught and retried in
`retrieveNamespaceInfo`; postfault retention still requires live evidence.
`Properties.load` remains an abort-prone diagnostic door. No new bug is
claimed from this stage.
