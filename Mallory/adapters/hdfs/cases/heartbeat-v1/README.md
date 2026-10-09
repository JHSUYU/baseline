# HDFS-19/20 named DataNode reply and command queue bridge (staged)

This directory is an isolated HDFS 3.4.3 adapter overlay. It has been built in
an isolated adapter project and has not been installed in the active adapter
or used in a cluster run.
The two Java files under `overlay/` are complete candidate sources copied from
the active adapter at the pinned base hashes in `preflight.json`. The active
adapter and all result/checklist files remain untouched by this staging.

## Concrete causal handoffs

HDFS-20 uses `TestStandbyIsHot#testStandbyIsHot`. On each named DataNode,
`BPServiceActor.offerService` calls `sendHeartBeat`, then passes the returned
`HeartbeatResponse.haStatus` to
`BPOfferService.updateActorStatesFromHeartbeat` (selected check at line 606).
The overlay scopes `DatanodeProtocolClientSideTranslatorPB.sendHeartbeat`,
records the *completed* Hadoop IPC response correlation when
`Client.getRpcResponse` returns, and associates that token with the exact
decoded `NNHAStatusHeartbeat` object. The check method consumes this identity
to enter the response context. A failed RPC or an unmatched status provides no
graph edge.

HDFS-19 uses `TestDFSFinalize#testFinalize`. Its `DNA_FINALIZE` command is
returned from `NameNodeRpcServer.blockReport` when the image upgrade is
finalized. `DatanodeProtocolClientSideTranslatorPB.blockReport` decodes the
concrete `FinalizeCommand`. `BPServiceActor.blockReport` adds it to a list;
`CommandProcessingThread.enqueue` places a concrete `Runnable` on a queue;
`processQueue` takes and runs that same object; and
`BPOfferService.processCommandFromActive` reaches the selected check at lines
768–769. The overlay associates decoded commands with the exact IPC reply,
emits `TASK_SUBMIT` immediately before `BlockingQueue.put` can expose the
Runnable to the worker, and emits
`TASK_CLAIM` around the exact dequeued `Runnable.run`. A failed put leaves an
unmatched submit that forms no graph edge. When a block report
returns multiple commands, the queue edge remains valid but the submit is not
attributed to any one reply; each command carries its own response token.

The existing cluster JUnit methods and target sites are unchanged. Healthy
admission requires a passing JUnit run, a named target actor, a matched
response SEND/RECV tuple, and an observed time-respecting path from at least
one eligible I/O door to the selected target. HDFS-19 additionally requires a
matched command `TASK_SUBMIT`/`TASK_CLAIM` for the corresponding worker.
Only then may a separate fault campaign be promoted; the staged JSON files
are healthy-only and explicitly disable automatic promotion.

## Validation

The isolated Maven build and three focused JUnit checks passed (3/0/0). The
checks cover the synthetic queue bytecode order, a concurrent producer/worker
race with 100 exact Runnable identities, and transformation of the pinned
Hadoop `CommandProcessingThread`, `BPOfferService`, and RPC translator class
images. `preflight.json` pins the release JAR, agent JAR, source files,
compiled class images, and test report by SHA-256.

Still required:

1. Run the two healthy-only configs on separate free lanes. Verify the
   reply/queue joins in trace, not just a target count.
2. If either test's selected guard is already throwing in the healthy run,
   record that fact and choose another existing cluster JUnit workload before
   considering fault injection.

The overlay's identity maps currently retain a command if the cluster shuts
down before it is processed. This is bounded by one test JVM lifetime; the
release build should confirm the memory effect under the selected tests.
