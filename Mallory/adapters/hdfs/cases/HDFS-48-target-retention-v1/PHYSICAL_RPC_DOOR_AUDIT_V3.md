# HDFS-48 original-102: physical RPC exception door audit

Scope: read-only review of Hadoop 3.4.3 commit
`9d50c6884666e794e45102260a4017bb31802e1b`, the existing
`TestRenameWithSnapshots#testRenameUndo_1`, archived Mallory v14 healthy and
fault receipts, and the staged client-door package in this directory. No JVM,
tmux session, new worktree, or trial was started for this audit.

## Exact target and archived evidence

The selected check is the `Preconditions.checkState` identity invariant in
`INodeDirectory.replaceChild` at lines 356-358. The configured sites are
`@356:branch:2`, `@358:branch:3`, and `@356:callthrow:11`. The first operand
tests `oldChild == children.get(i)`; when true, Java short-circuits the
two-reference operand at line 358. A healthy target check does not imply an
`IllegalStateException` or execution of both branch sites.

The test calls `root.replaceChild(dir2, mockDir2, ...)` directly at line 1357,
then calls `hdfs.rename(foo, newfoo)` at line 1360. The archived calibration
trace has a `TARGET_CHECK` on `hdfs-client` at event `HDFS-48-r0000:2587`
for the direct setup call, and a separate `TARGET_CHECK` on
`hdfs-cluster-1/nn0` at event `HDFS-48-r0000:2788` for the rename RPC. Both
are `@356:branch:2` with `TAKEN` outcome. The named NameNode occurrence is
the required target. It comes from the snapshot rename constructor:
`FSDirRenameOp.RenameOperation` calls
`srcParent.replaceChild4ReferenceWithName`, which calls `replaceChild`
(`FSDirRenameOp.java:655-679`, `INodeDirectory.java:381-399`). The calibration
passed Surefire 1/0/0 and attested the named target class, with 27 eligible
healthy pretarget doors. The event data do not establish a failing check.

The tested `Server$RpcCall.run@1246:door:1` is immediately before `Server.call`
inside a catch for `Throwable` (`Server.java:1235-1254`). An injected
`IOException` becomes an RPC error before the rename handler. The archived
pilot had ten effective injected faults, zero postfault named targets, and zero
selected exceptions. The original test has no catch/retry around its setup
RPCs or selected rename. Its rename expects `false`, while edit-log sync is
after rename processing and conditional on success (`FSNamesystem.java:3300-3330`).
Thus the unmodified test with the currently observed server ingress door has
no source-proven target-retaining pretarget physical I/O exception.

The current `data/crashfuzz/checklist102.json` records a different, historical
physical RPC-response route on the **unchanged** JUnit. The case-local
CrashFuzz hook throws at `Client.getRpcResponse` entry in a DataNode
`BPServiceActor` thread; its actor audit joins the DataNode's RPC port to the
sole NameNode and the later selected handler. It admits 107 original-JUnit
trials with the selected check after the fault; all 107 JUnits passed and none
threw the selected `IllegalStateException`. Hadoop's
`BPServiceActor.offerService` catches `IOException`, sleeps, and continues its
service loop (`BPServiceActor.java:764-805`), so an isolated heartbeat-response
exception need not abort the test's rename. The hook is at response-operation
entry rather than an actual socket-read instruction. This establishes
empirical target retention under that graph-free fault model and endpoint
join. It does **not** establish a Mallory event-time causal path from that
background response fault to the rename check. The v14 Mallory site catalog
observed only `Server$RpcCall.run` doors, so no heartbeat-response door was
admitted there. The 107 trials must not be conflated with the ten failed
Mallory ingress trials.

## Source-backed candidate: client socket write boundary

A closer physical RPC door is the invocation of
`ipcStreams.sendRequest(buf.toByteArray())` in
`Client$Connection$RpcRequestSender.run` (`Client.java:1113-1145`). The sender
has `Pair<Call, ResponseBuffer> pair`; `pair.getLeft().rpcRequest` is a
`RpcProtobufRequest`, whose `toString()` names the protocol and method
(`ProtobufRpcEngine2.java:649-681`). A method-aware adapter hook immediately
before this **specific write invocation**, inside the existing `try` and
`synchronized (ipcStreams.out)`, can expose only
`org.apache.hadoop.hdfs.protocol.ClientProtocol.rename` as a typed
`java.io.IOException` door. The hook must throw before `sendRequest` executes,
so no bytes of that attempt reach the NameNode. This is an injected exception
at a physical socket-write boundary, not evidence of an observed OS failure.

Unlike the staged `sendRpcRequest` entry hook, this placement uses Hadoop's
normal failed-write cleanup: `RpcRequestSender` catches `IOException` and
calls `markClosed`; `Connection.run` then calls `close`, which removes the
connection and invokes `cleanupCalls` to complete outstanding calls with the
local exception (`Client.java:1090-1109, 1138-1145, 1251-1314`). The caller's
`getRpcResponse` converts that error to a local `IOException`
(`Client.java:1563-1595`). `ProtobufRpcEngine2` wraps it in `ServiceException`,
and `ShadedProtobufHelper.ipc` unwraps it for
`ClientNamenodeProtocolTranslatorPB.rename` (`ProtobufRpcEngine2.java:256-273`,
`ShadedProtobufHelper.java:56-64, 158-163`,
`ClientNamenodeProtocolTranslatorPB.java:542-550`). With the opt-in
`dfs.client.retry.policy.enabled=true`, the non-HA `ClientProtocol` proxy's
`RetryUtils.WrapperRetryPolicy` selects `MultipleLinearRandomRetry` for a
local `IOException` (`NameNodeProxiesClient.java:339-390`,
`RetryUtils.java:109-124`). A later successful send can enter the nn0 rename
handler and reach the exact check. This is a source argument, not a runtime
target-retention result.

The existing staged patches instead put a method-aware hook at
`Client$Connection.sendRpcRequest` entry. That is before serialization and
queueing, but `Client.getConnection` has already registered its `Call`
(`Client.java:1620-1649`); throwing at entry skips the sender's
`markClosed`/`cleanupCalls` path. It remains a conditional candidate with a
specific pending-call and shutdown risk. The sender write-boundary candidate
avoids that particular gap. An injected error after any bytes are written
would be ambiguous and is not admitted by this proposal.

The staged retry test patch uses `dfs.client.retry.policy.spec=20,1`.
`RetryPolicies.MultipleLinearRandomRetry` parses this as 20 ms and one
configured retry (`RetryPolicies.java:473-511`), but `searchPair` advances only
when `curRetry > numRetries` (`:440-449`) and `RetryInvocationHandler` starts
at zero, then increments after each retry (`RetryInvocationHandler.java:152`).
Consequently the source permits retry decisions at counts 0 and 1. Count
actual attempts in the trace; do not assume a single retry from the text of
the spec. Inject only one fault, scoped to this rename, regardless of attempts.

## Next runtime admission

1. Dispatch assigns an isolated HDFS and adapter lane. First choose the
   admission objective explicitly: original-JUnit **target retention** can
   test the actor-joined `BPServiceActor` response door, while a Mallory
   root-free causal path to the selected rename check needs additional proof.
   The rename write-boundary candidate supplies a more direct causal route
   but needs the opt-in retry test patch. Pin the source, actual test class,
   adapter JAR, agent JAR, and exact site catalog for either route. For the
   write route, add `Client$Connection$RpcRequestSender` to agent inclusion,
   put the method-aware hook at the write invocation, and distinguish it from
   the staged `sendRpcRequest` entry site. For the original heartbeat route,
   keep the JUnit unchanged and instrument the concrete response-read actor.
2. Run one fault-free selected JUnit. Require Surefire 1/0/0, `hdfs-client`
   for the direct setup check, and the exact nonthrowing `@356:branch:2`
   target on `hdfs-cluster-1/nn0` after a matched rename RPC. Require the
   concrete chosen door in the site catalog. For the write route, require its
   root-free event-time causal closure to the named target. For the heartbeat
   route, require a named `BPServiceActor` actor, the same nn0 endpoint port,
   and an event-time path; if the graph has no path, report target retention
   separately without promoting it as causal Mallory coverage. The client
   setup check is ineligible as a substitute.
3. Only after that gate, run a bounded single-fault pilot at the first rename
   write invocation. Require one effective local `IOException` before any
   write of that attempt, sender `markClosed`/`cleanupCalls`, a local
   `IOException` consumed by retry, a new successful write and matched nn0
   receive, and the named exact target after the fault. Record attempted
   sends, pending calls, connection/thread shutdown, JUnit outcome, and any
   selected `IllegalStateException`. The current `rpcSend` hook fires at
   `sendRpcRequest` entry, before queueing; it cannot by itself prove a
   physical send. A write-completion receipt or equivalent matched receive is
   needed to disambiguate the retry from that early event.
   For a heartbeat pilot, require the exception in the named DataNode RPC
   response operation, `offerService` recovery, the original JUnit pass, and
   the exact nn0 target after the fault. Keep the original 107 actor-joined
   CrashFuzz trials as prior evidence, not as Mallory runtime admission.
4. If the chosen healthy gate cannot establish the named event-time path, or
   the pilot loses the target, classify this as an original-test/fault-model
   gap. Do not count the direct setup check, an unmatched send, or a generic
   RPC error as target retention or as a new HDFS exception.

Evidence: `data/mallory/calibration_v14_node0/HDFS-48/result.json`, its
`trials/r0000/events.jsonl.gz`,
`data/mallory/calibration_v14_node0/HDFS-48/offline-causal-audit.json`,
`data/mallory/pilots_v14/HDFS-48-nn-only/result.json`, and
`Mallory/cases/revisions/HDFS-48-nn-v14.pilot-decision-v2.json`.
Historical independent evidence: `data/crashfuzz/checklist102.json` entry
`HDFS-48`, `crashfuzz/cases/HDFS-48/README.md`,
`crashfuzz/cases/HDFS-48/actor-audit/heartbeat-actor-audit.json`, and
`crashfuzz/cases/HDFS-48/independent/src/Hdfs48Probe.java`.
