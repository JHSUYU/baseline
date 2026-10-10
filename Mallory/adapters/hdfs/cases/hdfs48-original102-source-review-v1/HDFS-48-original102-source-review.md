# HDFS-48 original-102 independent source review

Source: Apache Hadoop 3.4.3 commit
`9d50c6884666e794e45102260a4017bb31802e1b`. This review only reads
source, the archived v14 receipts, and the existing case-local node2 package.
No JVM or new fault trial was started.

## Selected check and healthy reach

The selected `INodeDirectory.replaceChild(INode, INode, INodeMap)` guard at
`INodeDirectory.java:356–358` checks that `oldChild` is the installed child or
the inode under its two reference layers. `Preconditions.checkState` throws
`IllegalStateException` only when that identity invariant fails. The original
`TestRenameWithSnapshots#testRenameUndo_1` builds a MiniDFSCluster with three
DataNodes, installs a spy using a direct `root.replaceChild` call at test line
1357, then invokes `hdfs.rename(foo, newfoo)` at line 1360. The direct setup
call runs as `hdfs-client`; it is separate from the named NameNode target.

The archived v14 healthy result passed Surefire 1/0/0, observed the exact
nonthrowing check on `hdfs-cluster-1/nn0`, and had 27 eligible pretarget doors.
Its offline audit reported 11 observed path doors. This establishes a suitable
healthy mapping for the original JUnit; a new node2 controller must still
attest its own healthy seed.

## I/O exception door and target retention

The archived path door is `Server$RpcCall.run@1246:door:1`, immediately before
`Server.call` (`Server.java:1243–1254`). An injected `IOException` is caught by
the surrounding `Throwable` handler and returned as an RPC error before the
rename handler reaches `replaceChild`. In the v14 pilot, all ten injected
faults were effective, but none retained the named nn0 target after the fault;
zero selected exceptions occurred. The original JUnit does not catch and
retry its selected `hdfs.rename` call. Its rename expects a `false` return.

The guard's NameNode path is in memory. `FSDirRenameOp.RenameOperation` calls
`replaceChild4ReferenceWithName` only when `isSrcInSnapshot` is true
(`FSDirRenameOp.java:655–679`). The edit-log sync in
`FSNamesystem.renameTo` follows `renameToInt`, and is conditional on a
successful rename (`FSNamesystem.java:3314–3329`); it is not a pretarget door
for the selected unsuccessful rename.

## Existing alternate JUnits reviewed

- `TestRenameWithSnapshots#testRenameUndo_2`, `_3`, and `_4` also call
  `root.replaceChild` directly in test setup (lines 1427, 1491, 1596).
  `_2` and `_3` do not catch the relevant rename RPC `IOException`.
  `_4` catches only the expected failed-rename message and then checks the
  restored inode; a generic injected RPC error does not establish a later
  named target.
- `TestRetryCacheWithHA#testRename` and `#testRename2` exercise retry and
  failover, but their `RenameOp.prepare` creates a plain file and the rename
  methods do not take a snapshot (`TestRetryCacheWithHA.java:489–570,
  1192–1204`). The `replaceChild4ReferenceWithName` path therefore lacks its
  source precondition in these methods. No exact guard reach is established.

No reviewed existing alternate both establishes the exact named NameNode
guard and supplies a source-backed, target-retaining pretarget `IOException`
door. This is a bounded source conclusion, not a claim about all possible
workloads or fault models. The original-JUnit full package already staged in
`hdfs48-node2-full-stage-v1` passed node0 `--static` preflight in this review;
its natural terminal and actual trial counts should be reported as outcomes.

## Frozen evidence

| Item | SHA-256 |
| --- | --- |
| `INodeDirectory.java` | `39636bc2cd045b41aadc631ad0ed8edc7935235422d0cc6decde876392208f50` |
| `FSDirRenameOp.java` | `aeb3505380b89896c921642c25e71050717ed185004ec3b1cb220b10b7a41277` |
| `TestRenameWithSnapshots.java` | `58c382b17db4855ebc3e105feb72232c086126e3ecb8a71dc8919d5967c8af00` |
| `TestRetryCacheWithHA.java` | `2987b194f96b59e19766802e591c216630365cc763be735c4e3c15fdd0bcd42e` |
| archived healthy result | `2bd670b4845e4964fa12bbd4301cece66306eb2a094d963dc712b729ce7c8291` |
| archived ten-trial pilot result | `43d9e70438bd944480f2c0084618cd0d9d443fd5f4e50dd24fded3b27c6dfed8` |
| existing node2 full config | `ce439b1679892b35f313cc909d1417195aa1cad2f6a61a9c0303251ba7dbbfb1` |
| existing node2 package manifest | `b33d4bec3931f8476016bbb647d1f70e31588b4f81b3336dc867bd5eb789c776` |
