# hdfs-adhoc-50: Default snapshot names have only millisecond resolution, so concurrent or back-to-back unnamed createSnapshot calls on one directory fail at random with 'snapshot with the same name already exists'.

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/snapshot/DirectorySnapshottableFeature.java:198`, `DirectorySnapshottableFeature.addSnapshot(INodeDirectory, SnapshotManager, String, LeaseManager, long)`, throws `org.apache.hadoop.hdfs.protocol.SnapshotException` when `i >= 0   (i = searchSnapshot(nameBytes): a snapshot with the same name exists)`
- Starting test: `org.apache.hadoop.hdfs.server.namenode.snapshot.TestNestedSnapshots#testNestedSnapshots`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Eight independent DFS clients call createSnapshot(dir) on the same snapshottable directory at the same moment without a snapshot name, so the NameNode generates the names.

**Why (root cause in the source):** When no name is given, FSDirSnapshotOp.createSnapshot uses Snapshot.generateDefaultSnapshotName() (FSDirSnapshotOp.java:106-107). That name is only a millisecond-precision timestamp, 's'yyyyMMdd-HHmmss.SSS (Snapshot.java:62-65), with no uniqueness guarantee. Two requests serialized under the write lock within the same millisecond get the same name, and the second is rejected by the duplicate-name check (DirectorySnapshottableFeature.java:196-199) although the client never chose a name. The check was meant to reject user-supplied duplicates; here the server's own name generation caused the collision. These are ordinary concurrent client operations. The effect is limited: one request fails with a clear exception, nothing is corrupted, and a client retry succeeds.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The duplicate-name check is supposed to reject a user who asks for a name that already exists. Here no client asked for any name: the NameNode generated the names itself and ensured uniqueness only by timestamp. That breaks as soon as two requests (from different clients, or one client issuing them back-to-back) land in the same millisecond. The check therefore rejects state that the NameNode's own name generation produced, not an invalid user request. In a real deployment, concurrent or rapidly repeated default-named snapshot requests on the same directory (several backup or cron jobs, DistCp-based snapshot-diff tooling, scripted loops) fail at random with a confusing 'snapshot with the same name already exists' error. The snapshot the client asked for is not taken, so a backup or recovery point is silently missing unless the caller retries. Generated names should be unique, e.g. by adding the snapshot id or a sequence number, or by retrying generation under the lock.

**Execution (agent):** 1) A MiniDFSCluster (1 NameNode, 3 DataNodes) runs. A directory /testConcurrentDefaultNameSnapshots/foo with one file is made snapshottable. 2) Eight independent DFS clients (separate FileSystem instances, standing in for cron jobs or backup tools on different hosts) line up on a barrier, then all call FileSystem.createSnapshot(dir) at the same moment WITHOUT a snapshot name. This is the documented 'hdfs dfs -createSnapshot <dir>' usage, in which the NameNode picks the name. 3) Each RPC reaches NameNodeRpcServer.createSnapshot, then FSNamesystem.createSnapshot (the requests are serialized under the FS write lock), then FSDirSnapshotOp.createSnapshot. There snapshotName == null, so Snapshot.generateDefaultSnapshotName() builds the name from new Date() with the pattern 's'yyyyMMdd-HHmmss.SSS, which has only millisecond precision. 4) Handling one createSnapshot under the lock takes well under 1 ms, so two requests handled within the same millisecond get the identical name (e.g. "s20261107-194844.823"). The first creates the snapshot. For the second, SnapshotManager.createSnapshot -> INodeDirectory.addSnapshot -> DirectorySnapshottableFeature.addSnapshot finds searchSnapshot(nameBytes) >= 0 and throws SnapshotException 'there is already a snapshot with the same name'. That exception goes back to the client as the RPC result. In the test this happened in the very first round of concurrent calls.

**Stack frame (agent):** at org.apache.hadoop.hdfs.server.namenode.snapshot.DirectorySnapshottableFeature.addSnapshot(DirectorySnapshottableFeature.java:199)  (the throw statement starting at line 198 spans lines 198-199; javac attributes the constructor call to line 199, where its last argument Snapshot.getSnapshotName(s) is evaluated. It is the 'i >= 0' duplicate-name check.)

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.namenode.snapshot.TestConcurrentDefaultNameSnapshots#testConcurrentDefaultNameSnapshots`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.namenode.snapshot.TestConcurrentDefaultNameSnapshots#testConcurrentDefaultNameSnapshots' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/snapshot/TestConcurrentDefaultNameSnapshots.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.hdfs.protocol.SnapshotException:`, frame `at org.apache.hadoop.hdfs.server.namenode.snapshot.DirectorySnapshottableFeature.addSnapshot(DirectorySnapshottableFeature.java:199)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h03m | 7 | 350,204 | 22 | 12,363 | 34,534 | 303,285 | $0.58 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
