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
guard.

The uninstrumented original JUnit passed in 38.990 s; the instrumented
healthy JUnit passed in 40.573 s. The exact snapshot-count guard ran 20
times: six substantive image saves wrote one through five snapshot records,
and the other invocations were startup saves with zero records. Every
observed count equaled the SnapshotManager count. The campaign uses exact
guard identity and positive snapshot count to retain the substantive saves.
It injects at observed FSImage SnapshotSection serialization writes and HDFS
IPC response reads, records production JaCoCo coverage, and resumes from an
atomic checkpoint in `independent/evidence`. A trial is relevant only if its
ordered faults applied and a selected guard ran afterward. This campaign is
still running, so its result is not yet a completed negative finding.
