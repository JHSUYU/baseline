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
root inode, child name, and old/current object identities. No healthy runtime
guard or fault trial is claimed yet.
