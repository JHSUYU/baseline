# HDFS-52: serialized snapshot count versus SnapshotManager

Selected check: Hadoop 3.4.3
`FSImageFormatPBSnapshot.Saver.serializeSnapshotSection`, line 467, compares
the number of snapshot records written to the FSImage with
`SnapshotManager.getNumSnapshots()` and throws `IllegalStateException` if
they differ.

The original embedded-cluster JUnit
`TestFSImageWithSnapshot#testSaveLoadImage` creates snapshots s1 through
s5. After each change, `checkImage` writes an FSImage, shuts down and
restarts its MiniDFSCluster, reloads the image, and compares namespace state.
It therefore exercises repeated snapshot serialization and a recovery path.
Runtime calibration should record the count pair and snapshot identity for
each saver invocation, plus observed file and RPC I/O before the exact
guard. No runtime or fault result is claimed yet.
