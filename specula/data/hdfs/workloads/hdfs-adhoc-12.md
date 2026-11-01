# hdfs-adhoc-12: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.hadoop.hdfs.server.datanode.TestCausynthDataTransferRpcFailure#testUnencryptedReplicationAfterModeledKeyRefreshRpcFailure`, in the fork tree `/bulk/wt/hadoop-hdfs-study-r7` (JHSUYU/hadoop `graphchecker/hdfs-checks`), `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestCausynthDataTransferRpcFailure.java`. It shares `replicateAfterModeledKeyRefreshRpcFailure(encrypted, prefix)` with the HDFS-17899 bug3 test; hdfs-adhoc-12 is the `encrypted = false` call.
- **Port**: `org.apache.hadoop.hdfs.server.datanode.TestAdhocWorkload12#run`, in `tree/hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestAdhocWorkload12.java`. `run-case.sh` copies `tree/` into the case's tree, where it is an untracked file (Specula copies untracked files into its confirmation worktrees).

## Kept (same scenario)

- Topology: one NameNode, two DataNodes, `MiniDFSCluster`.
- The test's own configuration, line for line: encryption off, block access tokens on, 12 locate-following-block retries, 10 min client socket timeout, 10 min heartbeat recheck interval, key update interval 60, token lifetime 1.
- The operations in the same order: create a one-byte file with one replica favored onto the first DataNode (inlined from `CausynthCluster.createOnNode`, which is `DistributedFileSystem.create(..., favoredNodes)`); find the block's source and the other DataNode; rotate the NameNode's block keys twice (`updateKeys(Long.MAX_VALUE)`); mark both DataNodes for a key update; one heartbeat of the target, then of the source, each processing its commands (inlined from `CausynthCluster.refreshKeysFromNameNode`, without its message-propagation scope); `source.transferBlock(...)` to the target; wait until the target holds a valid replica.
- The same waits: 100 ms polls up to 60 s (`CausynthCluster.WINDOW_WAIT_MS` = 60 s, inlined) for the keys, 20 ms polls up to 60 s for the replica; `@Timeout(120)`.
- The assertions the original makes in a native run (`recordingPrecondition` asserts there): two rotations; the source holds the current key; the target holds it.

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| `CausynthCluster.configure(conf)` (6 h IPC/socket/quorum timeouts, ordered HA failover, `ReplicaCachingGetSpaceUsed`, synchronous edit logging) | dropped | GraphChecker's replay-determinism adapter settings ("workarounds for the order of daemon work a replay cannot hold"), not the test's configuration |
| `.dataNodeConfOverlays(CausynthCluster.dataNodeOverlays(2))` (distinct IPC idle times per DataNode) | dropped | an adapter setting that gives each DataNode its own IPC connection so replay attributes connection threads stably |
| `pinBlockKeys(cluster)`: `setSerialNo`, two pre-window rotations, `addKeys` of the NameNode export into each DataNode, pruning every `allKeys` map by reflection | dropped | GraphChecker's cross-replay key-id pinning; it writes the target guard's operand (`allKeys`) directly, which a Specula workload must never do |
| `registerSources` / `CausynthCluster.register*`, `startRecording`, `CausynthMessagePropagation.begin*/end*` | dropped | recording window and message-propagation calls |
| `recordingPrecondition(...)` | `assertTrue(...)` | asserted in a native run in the original |
| `testReplicationAfterModeledKeyRefreshRpcFailure` (encrypted, HDFS-17899) | dropped | a different check (not among the 84) |
| class/method names, path `/causynth-hdfs-17899-bug3`, comments about failed key delivery | `TestAdhocWorkload12#run`, `/adhoc-workload-12`, neutral comments | neutral names (B3); no comment states the failure or the mechanism |

The workload injects no fault.
