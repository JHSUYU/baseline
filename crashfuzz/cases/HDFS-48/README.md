# HDFS-48: inode replacement during snapshot rename preparation

Selected check: Hadoop 3.4.3 `INodeDirectory.replaceChild`, line 356,
requires the supplied old child to equal the current child or its nested
reference target. Failure throws `IllegalStateException`.

The original MiniDFSCluster test
`TestRenameWithSnapshots#testRenameUndo_1` creates `/dir1` and `/dir2`,
takes a snapshot, wraps `/dir2` with a Mockito spy, and calls
`root.replaceChild(dir2, mockDir2, inodeMap)` before forcing a rename
rollback. This is a direct healthy path to the selected guard. The original
child should satisfy the first disjunct. Runtime identity should include the
root inode, child name, and old/current object identities.

The uninstrumented original JUnit passed in 28.504 s. The instrumented
healthy JUnit passed in 25.188 s and observed two successful invocations of
the exact guard: direct replacement of `/dir2`, then replacement of
`/dir1/foo` while preparing the snapshot rename. `RenameOperation` calls
`replaceChild4ReferenceWithName` in its constructor before the test's spy
forces destination insertion to fail and the rename rolls back. The campaign
selects the second check using its parent path and child name. It injects
observed HDFS IPC response-read exceptions before that
guard, records production JaCoCo coverage and target identity, and resumes
from an atomic checkpoint in `independent/evidence`. A fault trial is counted
as target-relevant only when the exact ordered injection was applied and the
selected rename-preparation guard ran afterward. The campaign is complete; a
passing healthy check or a test failure elsewhere does not establish a bug.
The first checkpoint reached 80 exact target-retaining trials in 132 attempts,
with zero selected target throws. Trial 125 added nine HDFS production coverage
probes within the last eight effective trials, so the same checkpoint resumed
under the predefined extension to 128 effective trials, ten faults, 240 total
attempts, and 14,400 seconds. It stopped after 128 target-retaining trials in
183 attempts over 4,357.59 seconds, with 179 fully applied fault sequences,
2,069 production coverage gains, and zero throws at the selected check. No
completed trial was rerun; each attempt remains in the ledger.

Source review confirms the selected `/dir1/foo` check occurs while the rename
is prepared, before the test's forced destination failure and rollback. Of 57
JUnit failures, 51 lost the selected check after injection; the other six
reached it without its `IllegalStateException`. Trial 001 reports the injected
IPC response exception directly. These are recorded as operation failures,
not as a detected bug at this target.
