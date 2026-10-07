# HDFS31/32 actor-aware continuation: offline source and raw mapping

This is a read-only design audit. No new original JUnit, healthy calibration,
or fault trial has run. The earlier HDFS31/32 80-attempt results remain
historical and contribute **zero** to a new actor-proven budget.

## Why the old RPC key is insufficient

Both old probes instrument `Client.getRpcResponse` at method entry and select
on a thread name after replacing every port and digit, then append a shared
ordinal (`Hdfs31Probe.java:36–51`, `Hdfs32Probe.java:34–49`). The old bytecode
hook passes neither the method's `Connection` parameter nor the calling
DataNode. The original `Client.getRpcResponse(Call, Connection)` method has
the connection in local 2, and `Connection.getRemoteAddress()` returns its
real RPC server address (`Client.java:1594`, `:1110`). Thus the endpoint is
available at the hook but was discarded.

The archived healthy HDFS31 trace has an initial `POOL_ADD` on one DataNode
before a second `POOL_ADD` on another; the selected `TRANSFER_BLOCK` and
`TARGET_GUARD` use the first DataNode object. The same trace mixes BP actor,
`main`, and setup-thread RPCs before the guard. The archived healthy HDFS32
trace has four `POOL_ADD` events from two DNs and two federated NNs. Two
distinct BP heartbeat endpoints, `localhost:41443` and `localhost:44095`,
share the old normalized selector and ordinal stream. Its first target
`deleteBlockPool` guard is on one DN and the first block pool. The two
`TARGET_THROW` events in the healthy trace are intentionally expected by the
JUnit. These observed ports are evidence for that one run, not replay keys.

## Original workloads and selected checks

| Case | Original embedded-cluster JUnit | Selected production check | Healthy expectation |
| --- | --- | --- | --- |
| HDFS31 | `TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` | `DataNode.getBPOSForBlock(ExtendedBlock)`: `blockPoolManager.get(block.getBlockPoolId())`, then `bpos == null` throws at `DataNode.java:1832–1835` | The test starts another DN, then invokes `dn0.transferBlock(...)`; the selected `dn0` guard is present and does not throw. See `TestDiskError.java:241–285`. |
| HDFS32 | `TestDeleteBlockPool#testDeleteBlockPool` | `DataNode.deleteBlockPool(String, boolean)`: `blockPoolManager.get(blockPoolId) != null` throws at `DataNode.java:3819–3822` in the released case source | The test creates two federated NNs and two DNs. It deliberately expects the first running-pool deletion to throw on each DN before `refreshNamenodes`; a later deletion on the same DN and BP succeeds. See `TestDeleteBlockPool.java:43–130`. |

Both original case source trees have Hadoop release commit
`9d50c6884666e794e45102260a4017bb31802e1b`. The HDFS32 line numbers
above refer to that frozen source tree, not another local Hadoop checkout.

## V3 hook and identity contract

1. Reuse the **mechanism** proven in the isolated HDFS storage V2, with a
   separate overlay digest and evidence directory: increment a startup episode
   in the deepest `MiniDFSCluster.startDataNodes` overload; synchronously
   register each `DataNode` object, configured storage directories, and slot
   before `startDataNode` creates its BP threads. Do not infer an actor from a
   thread name or a path suffix. The V2 source hooks are
   `PatchHdfsStorage.patchCluster/patchDataNode` and
   `HdfsStorageProbe.registerDataNode`.
2. On `BPServiceActor.run`, bind its actual `dn` field and `nnAddr` field to
   the current thread; both are present in released `BPServiceActor.java:96,
   116, 881`. `BPOfferService` is constructed with that DN and one actor per
   NN address (`BPOfferService.java:124–141`). Record the raw DN UUID, BP ID,
   nameservice/NN ID when available, and endpoint as evidence. The stable
   selector uses startup episode + DN slot/directories + **federated NN
   role** (HDFS32) or NN0 (HDFS31); every role must be resolved to exactly
   one raw endpoint in each run. Clear thread context at exit.
3. At `Client.getRpcResponse`, pass local 2 `Connection.getRemoteAddress()`
   to the hook. An RPC fault is eligible only when the call is executing in
   the bound BP actor thread and its actual endpoint equals the actor's
   configured NN endpoint. Record both raw addresses. Do not select generic
   `main` or setup-thread RPCs as same-DN BP faults: a client call's endpoint
   alone does not identify the DataNode that later runs a direct target call.
4. At HDFS31 `TRANSFER_BLOCK`, guard, and throw hooks, resolve the passed
   `DataNode` object to its registered logical actor and record raw DN UUID,
   BP ID, block ID, and service identity. At HDFS32 guard and throw, resolve
   the passed DataNode plus raw BP ID and `force`; `POOL_ADD/REMOVE` records
   the manager-to-service-to-DN/BP join. `datasetDelete` is a separate
   downstream outcome. No unregistered or ambiguous target receives credit.
5. Count an effective trial only after every ordered fault matches its
   actor, NN role, endpoint, call site, and occurrence in raw trace, and the
   exact target check occurs later on the **same DN and BP**. HDFS32 compares
   `(DN, BP, force, guard outcome, exception)` with both healthy seeds before
   calling a target throw novel. A JUnit exit by itself is not this oracle.

The old selector could interleave `BP...:41443` and `BP...:44095` into one
ordinal. The V3 scheduler must maintain an ordinal per logical DN/NN-role
I/O key, preserve observed order in each trial, and fail closed if a planned
role has no unique current-run raw endpoint. Production coverage and newly
observed actor-bound I/O then guide mutation. Faults may increase in depth
up to eight (conditional ten); each check has 80 effective as base and
conditional 128 effective, with explicit attempt/time caps and atomic
checkpoint. The historical 80 attempts per case are kept only as ancestry.

## Before any V3 fault campaign

Build and `-Xverify:all` the new overlay offline. Run two original JUnit
healthy calibrations for each case in isolated scratch directories. Require
identical overlay SHA, exact registered DN/NN-role mapping, a stable eligible
BP RPC I/O family preceding the selected target, and matching healthy target
signatures. If the original JUnit exposes no such actor-bound I/O before a
target, mark that fault family ineligible and inspect a concrete DN-local
file/RPC family; do not relax the identity rule. Keep the old raw archives,
SHA receipts, results, and checklist counters unchanged until a new actor
campaign has its own independent audit.
