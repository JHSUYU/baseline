# HDFS-48 original-102 bounded source re-audit

Source is Hadoop 3.4.3 commit `9d50c6884666e794e45102260a4017bb31802e1b`.
`source-receipt.json` pins every source and archived artifact used here by
SHA-256. This audit is limited to the named snapshot rename tests, the retry
cache HA rename tests, the selected NameNode path, and the two IPC boundaries
below. `verify_receipt.py` checks the pins without launching Java.

## Exact selected occurrence

`INodeDirectory.replaceChild` lines 356-358 asserts that `oldChild` is the
installed child or the inode behind two reference layers. The configured
check sites are `@356:branch:2` and `@358:branch:3`; the selected call throw
is `@356:callthrow:11`. The first operand short-circuits the second when true.
The archived v14 healthy run passed JUnit 1/0/0 and observed a direct setup
check on `hdfs-client` (event 2587) and the selected nonthrowing check on
`hdfs-cluster-1/nn0` (event 2788). The client occurrence is not the target.
The nn0 occurrence follows the snapshot source path through
`FSDirRenameOp.RenameOperation` lines 655-679 and
`replaceChild4ReferenceWithName` lines 381-399.

## Unchanged MiniCluster JUnits rechecked

| Candidate | Exact target and retry finding |
| --- | --- |
| `TestRenameWithSnapshots#testRenameUndo_1` | Proven nn0 target in archived healthy run. The test directly installs its spy at line 1357, then makes one selected `hdfs.rename` at line 1360 and expects `false`; it has no catch/retry around that call. Its `@Before` creates a single NameNode and three DataNodes. |
| `#testRenameUndo_2` | Creates `foo` after snapshot, so its failed rename does not satisfy `isSrcInSnapshot`; the direct `root.replaceChild` at line 1427 is only the client setup occurrence. |
| `#testRenameUndo_3` | Its first rename may enter the snapshot reference path; a fault on that RPC aborts before later renames. A fault on a later rename cannot count a check from the earlier rename as postfault retention. The line 1491 direct replacement is also client setup. |
| `#testRenameUndo_4` | Has snapshot reference renames, but catches only an expected failure message at lines 1599-1606, then checks undo. A generic physical RPC `IOException` does not satisfy that assertion and there is no retry. |
| `#testRenameUndo_5` to `_7` | The tests either expect one failed rename and inspect undo state or catch a particular injected/reserved-name error. None has a second attempt after a physical `IOException` that is source-proven to reach this exact nn0 check. |
| `TestRetryCacheWithHA#testRename`, `#testRename2` | The explicit failover/retry harness is useful, but `RenameOp.prepare` and `Rename2Op.prepare` create an ordinary file without a snapshot. `isSrcInSnapshot` is false, so the selected reference replacement is not established. |
| `TestRetryCacheWithHA#testRenameSnapshot` | Calls `client.renameSnapshot`, which renames snapshot metadata, not an inode path through `FSDirRenameOp.RenameOperation`. |

This is a bounded candidate review, not an exhaustive claim about every HDFS
test. In this source the non-HA client retry policy defaults to disabled
(`HdfsClientConfigKeys.Retry.POLICY_ENABLED_DEFAULT=false`); the original
JUnit sets no opt-in retry policy. Changing that configuration or JUnit would
be a separate workload, not an unchanged-test result.

## Typed physical I/O doors

1. **Named rename RPC ingress, rejected for target retention.** The v14
   `Server$RpcCall.run` door at line 1246 throws before `Server.call` under a
   `Throwable` catch. The handler returns an RPC error before the named nn0
   check. Its ten effective pilot faults produced zero postfault named
   targets. `FSNamesystem.renameTo` syncs the edit log only after a successful
   `renameToInt`; the selected test's rename returns `false`, so this is not
   an alternate pretarget file-I/O door.
2. **DataNode heartbeat response read, conditional retention candidate.**
   `Client$IpcStreams.readResponse` at lines 1922-1943 physically reads the
   response length and bytes (`in.readInt`, `in.readFully`) and declares
   `IOException`. `Client$Connection.receiveRpcResponse` catches it and
   closes the connection, completing outstanding calls with a local error;
   the DataNode's `BPServiceActor.offerService` catches `IOException`, sleeps,
   and continues. An isolated, method-matched heartbeat response read fault
   before the selected rename can therefore plausibly retain the later nn0
   check on the **unchanged** JUnit. However, the read runs in a connection
   receiver thread, not the `BPServiceActor` caller. Admission requires a
   call-ID/request-method/endpoint join and proof that no other outstanding
   RPC is unintentionally faulted. A response read on the *rename* RPC is
   after the NameNode check and is not pretarget.

The archived CrashFuzz actor audit reports 107 original-JUnit heartbeat
response-operation faults with a later selected guard and passing JUnit. That
hook was at `Client.getRpcResponse` entry in a named DataNode caller, not at
`in.readInt` or `in.readFully`. It supports target retention under its
operation-entry fault model but does not prove a physical byte-read site or a
Mallory event-time causal path. The existing HDFS-48 node2 heartbeat package
is healthy-only and likewise has no fresh node2 runtime receipt. The separate
client socket-write/retry proposal can give a more direct causal route, but
requires opt-in retry and adapter/test changes; it is not an unchanged-JUnit
alternative.

## Admission decision

**GO only for one queued healthy-only, unchanged-JUnit calibration** using
the staged `hdfs48-heartbeat-response-node2-v2` package when dispatch grants
an isolated HDFS lane. Require JUnit 1/0/0, exact nonthrowing
`@356:branch:2` on `hdfs-cluster-1/nn0` after the matched rename, separate
client setup occurrence, named `BPServiceActor` response door before the
target, and same NameNode endpoint. Record whether a root-free event-time
path actually exists; do not infer it from shared endpoint and elapsed order.

**HOLD physical-read pilot and full campaign.** First build or identify a
typed `IpcStreams.readResponse` read-boundary site and verify on a healthy
trace that the receiver's pending call is uniquely the heartbeat from a
named DataNode to nn0. Then a bounded one-fault pilot must show the injected
`IOException`, connection cleanup, `offerService` recovery, JUnit pass, and
the exact named target after the fault. If no event-time path is established,
report target retention separately from causal Mallory coverage. No selected
`IllegalStateException` has been observed in these receipts.
