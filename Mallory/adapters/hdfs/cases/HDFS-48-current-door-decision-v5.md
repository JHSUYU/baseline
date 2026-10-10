# HDFS-48: target-retaining I/O decision (Hadoop 3.4.3)

This is a source and archived-trace audit. It started no JVM or fault trial and
does not change the 102-case checklist. Source is Hadoop commit
`9d50c6884666e794e45102260a4017bb31802e1b`.

## Selected check and test

The exact target is the `Preconditions.checkState` identity condition in
`INodeDirectory.replaceChild` at lines 356-358. The test
`TestRenameWithSnapshots#testRenameUndo_1` constructs one NameNode and three
DataNodes, creates a snapshot, calls `root.replaceChild` directly in its client
setup at line 1357, then calls `hdfs.rename` at line 1360. The direct call is
not the selected NameNode occurrence. The archived v14 healthy trace separately
records the client setup check at event 2587 and the named
`hdfs-cluster-1/nn0` check at event 2788. The latter is reached because
`FSDirRenameOp.RenameOperation` sees `isSrcInSnapshot` and calls
`replaceChild4ReferenceWithName`, which calls `replaceChild`.

## Why the current full package is a dead end

The v14 full package uses `Server$RpcCall.run@1246` as its typed
`IOException` door. That call is inside the `Throwable` catch surrounding
`Server.call`, before the rename handler. In the archived pilot, **10 effective
faults produced zero postfault named targets and zero selected exceptions**.
The original test has no catch around its one selected `hdfs.rename` call and
does not enable non-HA client retries. Reusing that door for an 80-trial full
campaign does not create a target-retaining route. This is a measured result
for this door and test, not a claim that the HDFS check cannot be faulted.

## Best unchanged-test candidate

The existing isolated `hdfs48-heartbeat-response-node2-v2` package uses the
typed `Client.call#getRpcResponse` operation boundary at line 1529. A named
DataNode `BPServiceActor` executes heartbeats concurrently with the rename.
`BPServiceActor.offerService` catches an `IOException`, sleeps, and loops, so
this exception can leave the test alive until the later named NameNode check.
The historical, graph-free CrashFuzz actor audit reports 107 actor-joined
heartbeat-response faults with the target retained; none threw the selected
`IllegalStateException`. Those trials are prior target-retention evidence,
not a Mallory closure proof. This boundary is the response operation before
`getRpcResponse`, not the physical `IpcStreams.readResponse` byte read.

The package's static preflight passed locally and its config/site SHA-256 are
`c535841283a0075b1a380f9066f6446a2948c6458b3af0367730a41f9e42be7e`
and `5917ce1576433e46af746d9f4ac601c99d7894e891d272b6d504c9c5675d9458`.
It has **no fresh Mallory healthy trace or fault result**. Dispatch should run
one isolated node2 healthy JUnit when the HDFS lane is free. Admission requires
Surefire 1/0/0, the exact target on `hdfs-cluster-1/nn0`, a named DataNode
heartbeat response door before it, and an audited event-time path from that
door to the target. An endpoint match and event order alone do not establish
the Mallory closure. If the path is absent, keep target retention and causal
coverage distinct; do not promote a full Mallory campaign.

## More direct causal candidate, requiring a changed test configuration

The physical client write for the rename request is
`Client$Connection$RpcRequestSender.run:1133`, specifically the
`ipcStreams.sendRequest(buf.toByteArray())` invocation. The compiled 3.4.3
method holds the current `Pair<Call, ResponseBuffer>` in local slot 2, so a
method-aware hook can identify `ClientProtocol.rename` from that pair's
`Call.rpcRequest` immediately before the write. This is inside the existing
`IOException` catch and output lock. A pre-write fault is caught by the sender,
calls `markClosed`, and the connection cleanup completes the pending call with
a local error. With `dfs.client.retry.policy.enabled=true`, the non-HA client
policy can retry a local `IOException` and the successful later request can
reach the NameNode check. This requires a separate isolated adapter/test build
and a new healthy and single-fault pilot; it is not an original-JUnit result.
The older staged `sendRpcRequest` entry patch throws before sender cleanup and
has an unanswered-call risk, so it should not be used as proof of this physical
write model. A sender-thread hook must also preserve the named client actor and
match the successful retry's RPC token to the NameNode target.

## Decision

Prioritize the already staged unchanged-JUnit heartbeat **healthy-only** run.
Hold its full campaign until the trace proves an event-time target closure and
a bounded fault pilot retains the named target. Hold the v14 ingress full
package. If the heartbeat door has no closure, stage the physical rename-write
variant in an isolated worktree with opt-in retry, then require a fresh healthy
path and a single-fault target-retention pilot. No new HDFS bug is established
by this audit.

Archived receipts: `data/mallory/calibration_v14_node0/HDFS-48/result.json`
(SHA-256 `2bd670b4845e4964fa12bbd4301cece66306eb2a094d963dc712b729ce7c8291`),
`data/mallory/pilots_v14/HDFS-48-nn-only/result.json`
(`43d9e70438bd944480f2c0084618cd0d9d443fd5f4e50dd24fded3b27c6dfed8`),
and `hdfs48-original102-reaudit-v2/source-receipt.json`. Static receipt
verification: `python3 hdfs48-original102-reaudit-v2/verify_receipt.py`
reports `source_reaudit_pass` with 18 pinned artifacts and no JVM launch.
