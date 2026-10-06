# HDFS-32: original cluster tests and target-retaining fault trials

The selected check is `DataNode.deleteBlockPool(String, boolean)` in Hadoop
3.4.3, region `REGION.10878e59-8e3c-3d04-a34c-7cd16fd5e446`, guard
`#u9`. The guard reads `blockPoolManager.get(blockPoolId)` and throws an
`IOException` at `#u14` when the block pool service is still registered
([DataNode.java:3814-3827](/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java#L3814)).

## Bounded owner-test search

Search command:

```sh
rg -n --glob '*Test*.java' 'deleteBlockPool\(|-deleteBlockPool|DFSAdmin\.deleteBlockPool' \
  /users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project
```

The only cluster test methods found were in
`TestDeleteBlockPool.java:42-194`. The other match,
`TestTools.java:82`, lists `-deleteBlockPool` for an invalid-usage/help test
and does not execute a cluster deletion. `testDeleteBlockPool` builds a
two-NameNode, two-DataNode `MiniDFSCluster` and calls `DataNode.deleteBlockPool`
directly. It deliberately catches the target's `IOException` for running
block pools at lines 69-74 and 106-112. The recorded healthy trace has five
target-region hits, including two expected fatal outcomes. It therefore
cannot use the same exception as a new-bug oracle. The selected original
`testDfsAdminDeleteBlockPool` builds a two-NameNode, one-DataNode cluster
at lines 141-151, refreshes nameservices at 166-169, then sends separate
`DFSAdmin.deleteBlockPool(force=false)` and `(force=true)` commands at
173-182. Both healthy target guard outcomes are true; no target exception
occurs. These are distinct semantic operations even though both reach the
same source region.

## Exact injection outcomes

The original `testDfsAdminDeleteBlockPool` was run by GraphChecker with an
embedded Hadoop IPC bridge. The healthy `force=false` target occurrence and
request marker are in one target closure, with no blocking lineage gap:
`graph-ipc-semantic-seed/trace/concolic_region_plan.jsonl`. The selected
marker is the client `sendRpcRequest` door in region
`REGION.763d087e-89f1-3a45-a53b-21f4012a2fe8`.

| Trial | Exact fault applied | Same `force=false` target after fault | Result |
| --- | --- | --- | --- |
| `graph-ipc-core-trial-01` | Yes; pre-semantic request index `@14` | No | Request-index drift, then test failure at the later `force=true` command; `lost_target`. |
| `graph-ipc-semantic-trial-01` | Yes; `IOException` at `sendRpcRequest#u20` for `force=false` | No | Only the later `force=true` guard remains; `lost_target`. |
| `graph-ipc-semantic-trial-02` | Yes; `ConnectTimeoutException` at `sendRpcRequest#u25` for `force=false` | No | Only the later `force=true` guard remains; `lost_target`. |

The faulted traces and aggregate manifests are preserved under each trial
directory. The region-level `targetAfterFault=true` in a raw trial summary
is insufficient here: it refers to the later `force=true` command. Across
three exact injections, zero trials retained the selected `force=false`
target occurrence; zero qualify as target-retaining trials, and no new bug
is marked.

## Why another pre-target I/O point was not selected

The source mutates the in-memory block-pool map first:
`DataNode.shutdownBlockPool` calls `blockPoolManager.remove(bpos)` at
`DataNode.java:2148`, which removes the block-pool-ID entry at
`BlockPoolManager.java:89-95`. It calls
`data.shutdownBlockPool(bpId)` only afterward at `DataNode.java:2159-2160`;
the downstream shutdown path writes replica and usage state in
`BlockPoolSlice.shutdown` at lines 942-945. The target check reads that map
at `DataNode.java:3819`, before the target's own dataset deletion at 3827.
Thus the observed shutdown file writes are downstream of the map removal
that determines this guard; they are not a supported pre-removal fault point
for the selected check. Expanding the original test's GraphChecker scope to
`BPServiceActor` in `static-ipc-actor` and rerunning healthy seeds in
`graph-ipc-actor-seed` and `graph-ipc-actor-cleanup-seed` did not produce
another selected fault marker in the target closure. The only selected
pre-target RPC door raised before the target method ran.

This is a bounded conclusion for the searched original Hadoop 3.4.3 unit
tests and measured closure. HDFS-32 is recorded as `no_valid_target_trial`,
not `no_cluster_test`, `quality_complete`, or `confirmed_bug`.
