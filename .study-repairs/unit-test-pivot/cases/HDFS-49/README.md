# HDFS-49: snapshot quota guard, original JUnit feasibility

Selected check: `DirectorySnapshottableFeature.addSnapshot`, Hadoop 3.4.3,
`if (n + 1 > snapshotQuota)` at line 188 (exception begins at line 189).

The original `TestSnapshot#testSnapshot` uses `MiniDFSCluster` in `setUp`
(`TestSnapshot.java:120-123`). Its 20 iterations each create a snapshot on
`/TestSnapshot` and one on another directory (`TestSnapshot.java:91,163-184,
236-271`; `SnapshotTestHelper.java:525`). The helper calls `allowSnapshot`
before every creation (`SnapshotTestHelper.java:333-341`), so these calls
execute the selected quota guard on its false arm. Snapshot names are unique
(`TestSnapshot.java:669-671`). The default quota is 65,536 per directory,
while no directory receives more than 20 snapshots in this test
(`DirectorySnapshottableFeature.java:62,70-71,184-191`). This reachability is
inferred from source; no runtime target trace was collected for HDFS-49.

The apparent quota test `TestSnapshotCommands#testMaxSnapshotLimit` starts a
`MiniDFSCluster` with `DFS_NAMENODE_SNAPSHOT_MAX_LIMIT=3` and attempts a fourth
snapshot (`TestSnapshotCommands.java:49-54,118-134`). It expects the *per
directory snapshot limit* error from
`SnapshotManager.checkPerDirectorySnapshotLimit`, which runs **after**
`DirectorySnapshottableFeature`'s quota guard
(`SnapshotManager.java:448-479`); it does not exercise the selected exception.

The root directory starts with quota 0 (`FSDirectory.java:113-125`) and
`resetSnapshottable` restores quota 0 when disallowing snapshots on root
(`SnapshotManager.java:294-304`). `TestSnapshot#testAllowAndDisallowSnapshot`
checks that state but does not create a root snapshot then
(`TestSnapshot.java:420-458`). `setSnapshottable` restores the default quota
before a permitted root snapshot (`SnapshotManager.java:252-257`). A search of
the Hadoop 3.4.3 HDFS test source found no `setSnapshotQuota` call and no test
expecting the selected `snapshot quota is` message.

**Disposition:** `no_usable_cluster_test`. An original cluster JUnit reaches
the check, so `no_cluster_test` was inaccurate. The available original tests
do not establish the selected quota-exceeded state. Under this baseline's
unchanged-test, I/O-exception-only model, exceptions cannot directly change
the local `snapshotQuota` field or make this test create 65,536 snapshots per
directory. No JVM run or fault trial was performed in this review; the case
retains `target_reached=false` because runtime reach has not been verified.
