# What a finding must show to count as each known bug

Written on 2026-11-08, before any agent run, from each JIRA's fix commit (`known/fixes/<case>.full.diff`;
the production part, `<case>.prod.diff`, is what the fixed-version check applies).

A finding **detects** the bug when all three hold:
1. it is a validated reproduction: the agent's test, on an unmodified buggy tree, throws the check's
   exception from the check's line;
2. its root cause is the bug's defect below (the part of the code the fix changes), not another defect that
   happens to fail the same check;
3. the realistic-trigger rules of `REVIEW-RUBRIC.md` hold.

**Partly**: the finding reproduces the bug's defect but not its consequence as the JIRA states it (e.g. the
failure is masked by a retry), or it reaches the defect only with an unrealistic step.

Supporting evidence (not decisive alone): the agent's test, re-run on the **fixed** version (the buggy tree
plus the fix's production changes, `known/<case>/fixed/`), no longer shows the failure. For bugs whose fix
handles the check's exception instead of preventing it (ZOOKEEPER-710/2886, HBASE-15039, HDFS-12931,
HDFS-5766, HDFS-10609), the check may still fire on the fixed version; there the consequence must go away.

| case | bug | defect a finding must hit |
| --- | --- | --- |
| hdfs-adhoc-k1 | HDFS-11741 Balancer block moves fail | The balancer's `KeyManager` caches one `DataEncryptionKey` and never replaces it after it expires (no expiry check in `newDataEncryptionKey`); once the block key it was made with has rolled out of the DataNodes' keys, every encrypted block move of a long-running balancer fails the DataNode's check. |
| hdfs-adhoc-k2 | HDFS-17383 Block transfers fail | In HA, a DataNode takes its block-token `currentKey` from the **standby** NameNode too (registration or KeyUpdateCommand from standby overwrite `currentKey`; and a new active does not push new keys to DataNodes). Tokens the DataNode itself creates for DataNode-to-DataNode transfers (replication/reconstruction) then carry a key id the receiving side does not know, and the transfer fails the `retrievePassword` check. |
| hdfs-adhoc-k3 | HDFS-12931 File checksum fails | `getFileChecksum` (FileChecksumHelper `checksumBlock`) does not handle `InvalidEncryptionKeyException`: when the client's cached data encryption key is no longer valid at the DataNode (e.g. expired/rolled, DataNode restarted or NameNode keys changed), the checksum request fails instead of clearing the key and retrying. |
| hdfs-adhoc-k4 | HDFS-5766 Healthy DataNode marked dead | In `DFSInputStream.fetchBlockByteRange` (positional read), after an `InvalidEncryptionKeyException` the client refreshes the key but falls through (no `continue`) and adds the healthy DataNode to `deadNodes`. |
| hdfs-adhoc-k5 | HDFS-10609 Pipeline recovery aborts client | During write-pipeline recovery (`DataStreamer` adding a DataNode / transferring the block to a new DataNode), an `InvalidEncryptionKeyException` from a stale client data encryption key is not caught and retried with a fresh key, so recovery aborts and the client's write fails. |
| hdfs-adhoc-k6 | HDFS-14075 NameNode crashes with NPE | When `startLogSegment` fails during a log roll (too few journals start), `FSEditLog` stays in `BETWEEN_LOG_SEGMENTS`/no open segment; the NameNode keeps running, and the next roll or `endCurrentLogSegment` fails the `isSegmentOpen()` check (or an NPE). The fix terminates the NameNode instead. |
| hdfs-adhoc-k7 | HDFS-14311 DataNode upgrade fails | During a DataNode upgrade with several storage directories, `DataStorage.loadBlockPoolSliceStorage` submits the per-volume upgrade callables while it is still loading other volumes; the callables share one `BlockPoolSliceStorage` and race on its `layoutVersion`/`cTime`, so a later volume's `doTransition` fails the layout-version check. |
| solr-adhoc-k1 | SOLR-9440 Client caches stale state | `ZkStateReader.removeCollectionStateWatcher` (or the watch/unwatch path around it) leaves a stale `DocCollection` in `watchedCollectionStates`/the lazy-collection references, so the cluster state returned for that collection is never updated; `waitForRecoveriesToFinish` keeps seeing old replica states and times out. |
| solr-adhoc-k2 | SOLR-6101 Shard splitting fails | With `legacyCloud=false`, SPLITSHARD creates the sub-shard cores via core-admin CREATE without a `coreNodeName` (the Overseer collection processor does not register the replica in cluster state first), so `CoreAdminHandler` rejects the create. |
| solr-adhoc-k3 | SOLR-6197 Collection migration fails | With `legacyCloud=false`, MIGRATE creates its temporary collection's extra replica via core-admin CREATE without a `coreNodeName`, so `CoreAdminHandler` rejects it. |
| hbase-adhoc-k1 | HBASE-15039 Token authentication fails | A master/region server validates a token whose key id it does not have yet (the ZooKeeper key-update event not yet applied, or missed because the watcher/leader-elector failed); `retrievePassword` throws `InvalidToken` without re-reading the keys from ZooKeeper. |
| hbase-adhoc-k2 | HBASE-20642 Adding column family fails | A client retries an `addColumn` DDL (RPC timeout, master failover) with a **new nonce**, so the master does not recognise the retry of an operation that already added the family and rejects it with `InvalidFamilyOperationException`. |
| zk-adhoc-k1 | ZOOKEEPER-710 Permanent session-moved errors | A client's session revalidation/reconnect on a slow server completes at the leader **after** the client has moved to another server; the stale revalidation sets the session owner back, and the client's live connection gets `SessionMovedException` on every request, permanently (the server does not close the connection). |
| zk-adhoc-k2 | ZOOKEEPER-2886 Multi-op session-moved errors | Same owner divergence, but for a connection that sends only **multi** operations: the session-moved error is returned inside the multi result instead of tearing down the connection, so the client keeps getting it forever. A finding whose connection is torn down and recovers is not this bug. |
