# HDFS-48 bounded cluster-test and I/O admission receipt

Source: Hadoop 3.4.3 commit `9d50c6884666e794e45102260a4017bb31802e1b`,
full source digest `825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7`.
This receipt used source and archived runs only. It started no JUnit, JVM, or
fault trial and did not alter the checklist.

## Selected occurrence and existing runtime evidence

`INodeDirectory.replaceChild:356-358` checks that `oldChild` is the installed
child or the inode reached through two references. The selected call throw is
`@356:callthrow:11` (`IllegalStateException`). Production calls in this source
reach `replaceChild` from `replaceChild4ReferenceWithName:398`; its caller is
`FSDirRenameOp.RenameOperation:676-679`, conditional on
`isSrcInSnapshot`. `TestRenameWithSnapshots#testRenameUndo_1` creates a
single-NameNode, three-DataNode MiniDFSCluster (`:102-112`), installs a spy by
directly calling `root.replaceChild` on the client at `:1357`, then makes the
selected `hdfs.rename` call at `:1360`. The client setup check cannot stand in
for the NameNode target. In the archived v14 healthy trace, Surefire passed
1/0/0 and the exact nonthrowing `@356:branch:2` occurred first on
`hdfs-client` (event 2587), then on `hdfs-cluster-1/nn0` (event 2788). The
healthy trial reported 27 eligible pretarget doors, all from the same outer
`Server$RpcCall.run@1246` site.

The v14 NameNode ingress pilot applied 10 effective `IOException` faults at
that outer RPC site and observed **zero postfault named targets** and zero
selected exceptions. `Server$RpcCall.run:1235-1254` catches the fault before
`Server.call` enters the rename handler. The unchanged test has no catch or
manual retry around `hdfs.rename`; its non-HA retry policy is disabled by
default (`HdfsClientConfigKeys.Retry.POLICY_ENABLED_DEFAULT=false`). That
measured door does not support a target-retaining campaign.

## Additional MiniCluster alternatives checked

A bounded scan of Hadoop HDFS `Test*.java` files found 29 classes containing
`MiniDFSCluster`, `createSnapshot`, and `.rename(` text. This lexical filter
does not prove coverage of every possible test. The more plausible unchanged
JUnits were checked against the `isSrcInSnapshot` production gate:

| Test | Source finding |
| --- | --- |
| `TestRenameWithSnapshots#testRenameUndo_3` | It issues snapshot renames at `:1495-1497` and again at `:1526-1528`, but there is no catch around the first or second rename. An RPC `IOException` on an earlier rename aborts the test before the later one; a pre-fault target cannot count as postfault retention. |
| `TestRenameWithSnapshots#testRenameAndUpdateSnapshottableDirs`, `#testRenameWithNestedSnapshottableDirs` | The tests catch a specific expected error at `:1145-1152` and `:1180-1191`, then rename after removing that error's cause. The source inode `foo` is merely snapshottable and has no snapshot; the first and second renames do not establish `srcChild.isInLatestSnapshot` at `FSDirRenameOp.java:655-679`. A generic transport error also fails the asserted message. |
| `TestRenameWithOrderedSnapshotDeletion#testRename` | A MiniDFSCluster test with snapshot and several renames (`:63-99`), but its `validateRename` catch asserts the specific cross-snapshot-root message (`:101-108`). A generic injected transport `IOException` does not satisfy this expected-error path. Later rename reach after such a fault is therefore unsupported. |
| `TestNamenodeRetryCache#testRename1`, `#testRename2` and `TestRetryCacheWithHA#testRename`, `#testRename2` | They exercise retries (`TestNamenodeRetryCache.java:289-329`), but their rename methods create ordinary source paths without a snapshot. `isSrcInSnapshot` is not established, so retries alone do not establish the selected `replaceChild` occurrence. |

Other snapshot rename tests may reach the guard in fault-free runs, but none
of the reviewed alternatives adds an existing source-backed catch or retry
for a typed pretarget I/O fault while preserving the selected named `nn0`
occurrence. The original JUnit remains the strongest proven healthy mapping.

## Two distinct candidate response boundaries

1. The already staged node2 healthy-only package
   `hdfs48-heartbeat-response-node2-v2` hooks
   `Client.call#getRpcResponse` at `Client.java:1529` and types an
   `IOException` before a named `BPServiceActor` consumes its response.
   This is a response **operation** boundary, not the physical socket read.
   It has not yet produced a fresh Mallory node2 trace. Its SHA-pinned config
   (`c535841283a0075b1a380f9066f6446a2948c6458b3af0367730a41f9e42be7e`)
   passed no-JVM static preflight on node0 and node2, with the same full
   source digest. No healthy admission is implied by static preflight.
2. The physical read is `Client$IpcStreams.readResponse:1922-1943`
   (`in.readInt`, then `in.readFully`) on the connection receiver thread.
   `Client$Connection.receiveRpcResponse:1202-1248` catches an `IOException`
   and closes the connection; `BPServiceActor.offerService:786-788` catches
   its completed heartbeat call error, sleeps, and loops. This gives a
   source-backed *conditional* route for the unchanged test to reach a later
   rename after a heartbeat response read fault. To target **that** read,
   instrumentation must join the receiver's connection and pending call ID
   to the named DataNode `sendHeartbeat` request and nn0 endpoint. A read on
   the rename RPC itself would occur after the NameNode check. Shared endpoint
   and temporal order alone are insufficient for a Mallory causal path.

The historical graph-free CrashFuzz actor audit reports 107 heartbeat
response-operation faults with later selected guards and passing JUnit. Its
hook was at `Client.getRpcResponse` entry in the DataNode heartbeat caller;
it supports target retention for that operation-entry fault model, while
neither proving a physical-byte-read site nor a Mallory event-time path.

A separate source proposal hooks the client `sendRequest` write invocation
inside the sender's `IOException` cleanup and enables non-HA client retry.
That can retry a local failure before the rename request reaches the
NameNode, but requires changing the JUnit configuration and adapter. It is
not an alternative *unchanged* cluster test or an executed Mallory result.

## Decision

The current checklist's `fault_model_no_target_retaining_pretarget_door`
classification remains supported **for the original JUnit and v14 Mallory
server-ingress door**. It is not a no-cluster-test skip and is not evidence
that HDFS has no bug. The existing node2 response-operation package is a
runnable **healthy-only** calibration after dispatch grants the HDFS lane;
run it once, require JUnit 1/0/0, separate client setup and named nn0 target,
the named heartbeat response door, and an audited event-time path. Do not
promote its static preflight or the prior CrashFuzz target retention to a
full Mallory campaign. A physical-read pilot needs the call/connection join
and its own fault-retaining runtime proof first. The staged v14 full package
reuses the ingress door whose 10 effective pilot faults lost the target; its
80-trial budget does not repair that admission gap.

SHA-256 evidence pins: `INodeDirectory.java`
`39636bc2cd045b41aadc631ad0ed8edc7935235422d0cc6decde876392208f50`,
`FSDirRenameOp.java`
`aeb3505380b89896c921642c25e71050717ed185004ec3b1cb220b10b7a41277`,
`TestRenameWithSnapshots.java`
`58c382b17db4855ebc3e105feb72232c086126e3ecb8a71dc8919d5967c8af00`,
`TestRenameWithOrderedSnapshotDeletion.java`
`241f34a27f274f26e8cbc71d9655ff7ac7d1ffb83b78276377ac180cd9976a29`,
`Client.java`
`65427c4d91e7bef56bad8be379f1c583dd90e72083538b2b578b95eb5a0d237c`,
v14 healthy trial result
`fa888832d9e8ff62bf173399aa58366f819972163d8e8c92db562dac398a4dde`,
v14 pilot result
`43d9e70438bd944480f2c0084618cd0d9d443fd5f4e50dd24fded3b27c6dfed8`,
and historical actor audit
`d8db3b7b0f455dcc19a822c1456500122d693006e594b252c9dce170d022d9fd`.
