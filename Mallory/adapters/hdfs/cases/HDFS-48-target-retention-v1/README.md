# HDFS-48 target retention: source-only proposal

This directory stages an isolated alternative for the selected `INodeDirectory.replaceChild` check. It has not run a patched JVM or a fault trial. `prepare.py` verifies SHA-pinned source and the ten earlier pilot results, then regenerates the two adapter patches, the test patch, and `preflight.json`. Dispatch must admit any runtime work to an isolated worktree; do not apply these patches to a shared release or the active HDFS-11 lane.

## Why the old pilot stopped at the target

The v14 healthy `TestRenameWithSnapshots#testRenameUndo_1` reached the exact nonthrowing check on named `hdfs-cluster-1/nn0`. All ten effective NameNode `Server$RpcCall.run` faults in the v14 pilot made the JUnit stop at setup or `hdfs.rename`, before any later exact target. The client receives a `RemoteException(IOException)` for a server-side injected IOException. `RetryUtils` does not retry that RemoteException under the ordinary policy. The target itself is an in-memory step of the rename RPC before edit-log sync, so a NameNode-side exception at the tested ingress does not leave a route to the same check in this JUnit.

## Candidate door

The patch adds a **client-side, method-aware** door at entry to `Client.Connection.sendRpcRequest`, before the existing `rpcSend` hook and before serialization/queueing. `HdfsHooks.rpcBeforeSend` reads the protobuf request name supplied by `RpcProtobufRequest.toString()` and names the site `hdfs:client-send-rpc-request:<method>` only for `ClientProtocol`. The pilot site is `hdfs:client-send-rpc-request:rename`. A fault at this point produces a local `IOException`, with no phantom SEND edge for the request that was never queued.

The test patch enables one bounded client retry with `dfs.client.retry.policy.enabled=true` and `dfs.client.retry.policy.spec=20,1`. The existing test operations remain the same. Source shows `ClientProtocol` uses `RetryProxy`; `ClientNamenodeProtocolTranslatorPB.rename` restores a local `IOException` from the protobuf wrapper; `RetryUtils` sends local IOException to `MultipleLinearRandomRetry`. The retry can therefore send the rename and reach the selected NameNode check after the injected exception. This is a source-backed hypothesis, not a verified runtime result. The pre-send location makes that retry safe from duplicate rename effects.

`Client.call` creates/registers a `Call` before invoking `sendRpcRequest`. The injected path could leave an unanswered local call while the wrapper retries. Watch pending-call cleanup and any timeout in the bounded pilot; a target-retaining trace with leaked-call side effects is not an acceptable healthy baseline.

## Admission and gates

1. Verify SHA pins with `python3 prepare.py` and apply the patches only in a fresh HDFS/adapter worktree. `git apply --check` already passed against the pinned original files. Build a new adapter JAR and HDFS test class, recording both hashes. Include `org.apache.hadoop.ipc.Client$Connection`, `org.apache.hadoop.ipc.Client`, `org.apache.hadoop.hdfs.server.namenode.snapshot.TestRenameWithSnapshots`, `org.apache.hadoop.hdfs.server.namenode.INodeDirectory`, and the existing identity/target classes in the agent include list. The JUnit transform supplies the named `hdfs-client` actor for its RPC calls. Do not reuse the v14 adapter JAR.
2. Run exactly one patched healthy JUnit. Require one passing test, zero failures/errors, exact selected nonthrowing target on named NameNode, and at least one `rename` client door. Inspect the event-time path from the client door through the successful RPC SEND/RECEIVE to the target. Reject if the new door is outside that path or the actor is unknown.
3. If healthy passes, admit at most six **single-fault** trials on site `hdfs:client-send-rpc-request:rename`, with a total pilot cap of eight minutes. Require an effective fault before queueing, a retry with a new RPC call carrying the same rename operation, and the exact named target after the fault. Classify JUnit failures from Surefire XML, because Maven may exit zero despite failed tests. A postfault target alone is not a bug finding.
4. Stop without full fuzz if the target disappears again, the retry is not observed, a path uses a coarse/root fallback, or SHA pins drift. Return the failure as a negative result, with all trial/event artifacts, to dispatch.

All exact source references, hashes, old pilot trial hashes, and bounds are recorded in `preflight.json`. The old ten NameNode trials are negative for target retention; they must not be counted as coverage of this unrun client-door variant.
