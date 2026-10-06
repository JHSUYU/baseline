# HDFS-07: Journal.acceptRecovery committed transaction guard

Status: **pending_graph_precision**. No new bug confirmed.

- Source: `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java:924-933`, function `Journal.acceptRecovery(RequestInfo, SegmentStateProto, URL)`.
- Exact runtime guard: `<org.apache.hadoop.hdfs.qjournal.server.Journal: void acceptRecovery(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo,org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocolProtos$SegmentStateProto,java.net.URL)>#u97`; fatal outcome `false`; region `REGION.122e6f79-f3dc-3d78-8508-4103c829ef3f`.
- Workload: unchanged `org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#testRecoverAfterIncompleteRecovery` under its original three-JournalNode MiniJournalCluster.
- Full case wall time: 2295.625 s; 24 trial JVM runtimes sum to 169.891 s.

## Causal graph and feedback

The healthy JUnit passes in 7.439 s and reaches the pinned guard once. The runtime source is `jn2#epoch1` during recovery phase 3. The expanded GraphChecker scope records 46 Hadoop IPC request sends and 46 paired receives across the embedded nodes. Queued `IPCLoggerChannel` calls carry the recovery request scope. The target closure contains 7 region occurrences ({'EXACT': 1, 'CANDIDATE': 6}) and 60 fault observations on RPC responses and Journal file I/O. The final healthy trace records 82 method entries and 104 branch outcome pairs in its woven scope.

The catalog has no BLOCKING gap. It has three DIAGNOSTIC `ADMISSION_GAP` entries: the target's `SegmentStateProto.EndTxId` and `StartTxId` consumer cells are not bound to an exported RPC message value. The client and server regions are therefore candidate members of the target closure, not an exact value-level proof. The precise gap appears in `healthy-control-door/trace/concolic_region_plan.jsonl` and in the trace archive.

## Fault trials

Every selector names the full runtime occurrence, source, marker, site and hit ordinal. Faults that remove the selected guard are classified `target_lost`. A failure of the JUnit assertions or quorum alone is not a target exception.

| Trial | Fault | JVM s | Applied/requested | Target after fault | Outcome |
|---|---|---:|---:|---|---|
| `trial-01` | HDFS_JOURNAL_FILE:SCAN_LOG | 6.835 | 1/1 | no | target_lost |
| `trial-02` | HDFS_JOURNAL_FILE:SCAN_LOG | 6.434 | 1/1 | no | target_lost |
| `trial-03` | HDFS_JOURNAL_FILE:SCAN_LOG | 7.688 | 0/1 | no | unmatched |
| `trial-04` | HDFS_JOURNAL_FILE:SCAN_LOG | 7.291 | 1/1 | no | target_lost |
| `trial-05` | HDFS_JOURNAL_FILE:SCAN_LOG | 6.887 | 1/1 | no | target_lost |
| `control-rpc-01` | HADOOP_IPC:RESPONSE | 7.991 | 1/1 | yes | target_nonfatal |
| `control-rpc-02` | HADOOP_IPC:RESPONSE | 7.389 | 1/1 | no | target_lost |
| `control-rpc-03` | HADOOP_IPC:RESPONSE | 7.489 | 1/1 | no | target_lost |
| `control-rpc-04` | HADOOP_IPC:RESPONSE | 7.137 | 1/1 | no | target_lost |
| `control-rpc-05` | HADOOP_IPC:RESPONSE | 7.237 | 1/1 | no | target_lost |
| `control-rpc-06` | HADOOP_IPC:RESPONSE | 7.388 | 1/1 | no | target_lost |
| `control-rpc-07` | HADOOP_IPC:RESPONSE | 7.238 | 1/1 | no | target_lost |
| `control-rpc-08` | HADOOP_IPC:RESPONSE | 6.937 | 1/1 | no | target_lost |
| `control-rpc-09` | HADOOP_IPC:RESPONSE | 6.787 | 1/1 | no | target_lost |
| `control-rpc-10` | HADOOP_IPC:RESPONSE | 6.333 | 1/1 | no | target_lost |
| `control-rpc-11` | HADOOP_IPC:RESPONSE | 6.936 | 1/1 | no | target_lost |
| `control-rpc-12` | HADOOP_IPC:RESPONSE | 6.686 | 1/1 | no | target_lost |
| `control-rpc-13` | HADOOP_IPC:RESPONSE | 6.536 | 1/1 | no | target_lost |
| `control-rpc-14` | HADOOP_IPC:RESPONSE | 6.485 | 1/1 | no | target_lost |
| `control-rpc-15` | HADOOP_IPC:RESPONSE | 6.887 | 1/1 | no | target_lost |
| `followup-eof` | HADOOP_IPC:RESPONSE:EOFException | 7.286 | 1/1 | yes | target_nonfatal |
| `followup-timeout` | HADOOP_IPC:RESPONSE:SocketTimeoutException | 7.639 | 1/1 | yes | target_nonfatal |
| `followup-paxos` | HDFS_JOURNAL_FILE:READ_PAXOS | 7.288 | 1/1 | no | target_lost |
| `followup-mutation` | HADOOP_IPC:RESPONSE, HDFS_JOURNAL_FILE:SCAN_LOG | 7.087 | 2/2 | no | target_lost |

Totals: 24 trials, 23 strict selectors, 24 applied fault events, 3 target-retaining trials, zero target throws. All three retained guards take the same nonfatal outcome as healthy.

The three retained trials add one raw branch outcome each, but it belongs to the injected `Client.getRpcResponse` fault guard (`#u44`, `#u49`, `#u54`). Production code coverage gain is zero. A two-fault extension from the first response trial was injected exactly and lost the target; it is not a finding.

Four other unchanged `TestQuorumJournalManager` methods were probed. They all passed but did not evaluate this exact guard; their names and runtimes are in `result.json`. The selected original method remains the best available stock workload for this guard.

## Source review and remaining work

`Journal.checkRequest` updates the durable `committedTxnId` from a request. `QuorumJournalManager.recoverUnclosedSegment` checks reported committed IDs against the proposed segment before sending `acceptRecovery`; the Journal guard protects a node whose local committed transaction would be discarded by a shorter replacement. In the selected test, recovery phases 2 and 3 run with only two live JournalNodes, so many added RPC failures stop at quorum before the guard. The observed target-retaining faults did not create the forbidden interval.

Resolve the three protobuf value-port gaps before marking this case high-quality complete or calling it bug-negative. The exact trace and 24 trial manifests remain on node1; `HDFS-07-traces.tar.gz` contains their compressed copies. Archive SHA-256: `fb55a04c14ea5dd617c592f64ea1f9f32069e15f9ed3964cd4db7a8f9fab6cf8`.
