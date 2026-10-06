# HDFS-48: inode replacement during snapshot rename rollback

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
the exact guard: direct replacement of `/dir2`, then rollback replacement of
`/dir1/foo`. The campaign selects the latter using its parent path and child
name. It injects observed HDFS IPC response-read exceptions before that
guard, records production JaCoCo coverage and target identity, and resumes
from an atomic checkpoint in `independent/evidence`. A fault trial is counted
as target-relevant only when the exact ordered injection was applied and the
selected rollback guard ran afterward. The campaign is still running; a
passing healthy check or a test failure elsewhere does not establish a bug.
