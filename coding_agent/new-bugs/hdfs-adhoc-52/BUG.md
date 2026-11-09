# hdfs-adhoc-52: Replaying the tolerated duplicate OP_DELETE_SNAPSHOT after ordered deletion is turned off still decrements numSnapshots, making it -1 so that every fsimage save/checkpoint fails.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/snapshot/FSImageFormatPBSnapshot.java:466`, `FSImageFormatPBSnapshot.Saver.serializeSnapshotSection(OutputStream)`, throws `java.lang.IllegalStateException` when `Preconditions.checkState(i == sm.getNumSnapshots());   (fails when the count of serialized snapshots differs)`
- Starting test: `org.apache.hadoop.hdfs.server.namenode.TestFSImageWithSnapshot#testSaveLoadImage`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** With dfs.namenode.snapshot.deletion.ordered=true, the test creates s0 and s1 and deletes s1 (only marked), then s0. The GC thread really deletes s1 and logs a second OP_DELETE_SNAPSHOT. The admin then turns ordered deletion off and restarts the NameNode, which replays the edits, and runs saveNamespace.

**Why (root cause in the source):** This is exactly the replay sequence the code comments say it tolerates (DirectorySnapshottableFeature.java:244-261). For the GC's duplicate delete, removeSnapshot returns null without removing anything. SnapshotManager.deleteSnapshot still calls numSnapshots.getAndDecrement() unconditionally (SnapshotManager.java:546-547), so after replay the global counter is -1 while 0 snapshots exist. The fsimage saver's consistency check Preconditions.checkState(i == sm.getNumSnapshots()) (FSImageFormatPBSnapshot.java:466-467) then fails in every saver thread, and saveNamespace fails. Every trigger step is a supported admin action. The counter stays wrong after each restart because the same edits are replayed, so checkpoints (saveNamespace, standby or secondary checkpoints) fail for good and the edit log grows without bound. The snapshot-limit accounting is also off by one.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Every step is a legal operation in a real deployment: turning ordered snapshot deletion off and restarting is an admin action the code explicitly supports (removeSnapshot has special handling for exactly this duplicate-delete replay). The edit-log replay is meant to tolerate the duplicate delete as a no-op, but the global snapshot counter is decremented even though no snapshot was removed. The in-memory SnapshotManager counter then disagrees with the actual snapshot lists, and the check correctly reports corrupted coordinated state that the system itself produced. Consequences: the NameNode can no longer write an fsimage. saveNamespace fails, and the Standby/Secondary checkpoints and the checkpoint at the end of an upgrade fail the same way, so edit logs grow without bound and restarts get slower and slower. The file-system snapshot limit accounting (checkFileSystemSnapshotLimit) is also off by one per such duplicate delete.

**Execution (agent):** 1) A NameNode (MiniDFSCluster, 1 DN) runs with dfs.namenode.snapshot.deletion.ordered=true (GC period 10 ms). Make /dir snapshottable and create snapshots s0 and s1. 2) Delete s1. It is not the earliest snapshot, so it is only marked as deleted (an xattr is set and it is renamed in memory); the edit log gets OP_DELETE_SNAPSHOT(/dir, s1). 3) Delete s0, the earliest snapshot, so it is really removed: OP_DELETE_SNAPSHOT(/dir, s0). 4) The SnapshotDeletionGc thread then really deletes the marked s1 via FSNamesystem.gcDeletedSnapshot, which logs a second OP_DELETE_SNAPSHOT(/dir, <deleted name of s1>). In memory numSnapshots=0 and there are 0 snapshots, which is consistent. 5) The admin sets dfs.namenode.snapshot.deletion.ordered=false and restarts the NameNode with no checkpoint in between, so the edits are replayed. Replay with ordered deletion off removes s1 at its OP_DELETE_SNAPSHOT (numSnapshots 2->1) and s0 (1->0). For the GC's OP_DELETE_SNAPSHOT, DirectorySnapshottableFeature.removeSnapshot finds no such snapshot; because ordered deletion is off and the image is not yet loaded, it deliberately ignores this and returns null (the HDFS-16972-style tolerance described in its comment). But SnapshotManager.deleteSnapshot still runs numSnapshots.getAndDecrement(), so numSnapshots becomes -1 while 0 snapshots exist. 6) Any later checkpoint fails. Here the test runs safemode enter + saveNamespace: FSImageFormatPBSnapshot.Saver.serializeSnapshotSection serializes i=0 snapshots, Preconditions.checkState(0 == -1) throws IllegalStateException in every FSImageSaver thread, and saveNamespace fails with 'Failed to save in any storage directories'. (The check statement is at line 467 of this tree.)

**Stack frame (agent):** at org.apache.hadoop.hdfs.server.namenode.snapshot.FSImageFormatPBSnapshot$Saver.serializeSnapshotSection(FSImageFormatPBSnapshot.java:467)

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.namenode.snapshot.TestSaveImageAfterOrderedDeletionDisabled#testSaveNamespaceAfterDisablingOrderedDeletion`
- Command: `source /bulk/codingagent/cases/hdfs-adhoc-52/agent/env.sh && mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.namenode.snapshot.TestSaveImageAfterOrderedDeletionDisabled#testSaveNamespaceAfterDisablingOrderedDeletion' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/snapshot/TestSaveImageAfterOrderedDeletionDisabled.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.lang.IllegalStateException`, frame `at org.apache.hadoop.hdfs.server.namenode.snapshot.FSImageFormatPBSnapshot$Saver.serializeSnapshotSection(FSImageFormatPBSnapshot.java:467)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h05m | 7 | 793,961 | 40 | 16,407 | 49,330 | 728,184 | $0.87 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
