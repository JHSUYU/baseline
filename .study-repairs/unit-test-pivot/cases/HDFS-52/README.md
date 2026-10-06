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

The uninstrumented original JUnit passed in 38.990 s; the instrumented
healthy JUnit passed in 40.573 s. The exact snapshot-count guard ran 20
times: six substantive image saves wrote one through five snapshot records,
and the other invocations were startup saves with zero records. Every
observed count equaled the SnapshotManager count. The campaign uses exact
guard identity and positive snapshot count to retain the substantive saves.
It injects at observed FSImage SnapshotSection serialization writes and HDFS
IPC response reads and records production JaCoCo coverage. The stopped
campaign completed 22 attempts: 16 exact ordered injections, two trials
that reached a substantive count guard after the final fault, and zero
selected count failures. Each attempted trial remains in
`independent/trial-ledger.csv`; the raw-event audit is
`independent/evidence/source-exclusion-audit.json` and the raw archive SHA-256
is in `independent-archive-manifest.json`. The interrupted 23rd attempt was
excluded from the counts.

Source review shows why this check is outside the current I/O exception fault
model in this original JUnit. `checkImage` holds `FSNamesystem.readLock`
around `Saver.save` (`TestFSImageWithSnapshot.java:143-155`), while snapshot
creation changes the manager count under `FSNamesystem.writeLock`
(`FSNamesystem.java:7175-7192`). The saver counts in-memory snapshot records
and compares that count with the manager value
(`FSImageFormatPBSnapshot.java:435-468`). Injecting an exception at a
snapshot-record write aborts the save before the guard. A heartbeat or RPC
response fault can leave a later save reachable, but it cannot make the
locked snapshot count differ. The case is marked `source_excluded`; the 22
attempts are retained as evidence, not presented as an 80-trial negative
bug result.
