# HDFS-31/32 actor-aware RPC repair plan

This is an offline source and bytecode mapping for two reopened Hadoop 3.4.3
checks. The old case-local campaigns each ran 80 original JUnits, but their
`Client.getRpcResponse` key was a thread name with digits and ports erased,
plus an ordinal. Those old trials remain historical evidence and contribute
zero to a new actor-aware effective-trial denominator. The raw archives and
old checkpoints are left untouched.

## Exact original targets and workloads

| Case | Original JUnit | Target guard and expected healthy result |
| --- | --- | --- |
| HDFS-31 | `TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` | `DataNode.getBPOSForBlock(ExtendedBlock)` at `DataNode.java:1829–1838`: `blockPoolManager.get(block.getBlockPoolId()) == null` throws `IOException`. The test's `dn0.transferBlock(block, ...)` reaches the guard with a present service; no selected throw is expected. The test starts a second DN after writing and corrupting the block metadata. |
| HDFS-32 | `TestDeleteBlockPool#testDeleteBlockPool` | `DataNode.deleteBlockPool(String, boolean)` at `DataNode.java:3814–3828`: a still registered `BPOfferService` causes the selected `IOException`. The original test creates two NNs and two DNs, deliberately catches this exception on each DN, refreshes the nameservice, and later removes the block pool. The selected first guard on the second DN has an **expected** throw; actor, block-pool role, `force`, service-presence branch, and source site must enter its healthy signature. |

Source: `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java`,
`.../src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDiskError.java:241–286`, and
`.../src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDeleteBlockPool.java:43–136`
in `/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3`.

## Bytecode and runtime identity changes

1. Keep the exact guard and `ATHROW` hooks from each historical ASM patcher,
   but write new patches in an isolated overlay. At the entry of
   `Client.getRpcResponse(Call, Client.Connection, long, TimeUnit)`
   (`Client.java:1566`), load local slot 2 (`Connection`), call its public
   `getRemoteAddress()` (`Client.java:1064`), and pass the raw
   `InetSocketAddress` to the new probe. This is the endpoint already used
   by Hadoop to wrap local RPC exceptions at lines 1587–1595. Do not infer
   it from the thread name or erase its port. Require exactly one patched
   method with the expected descriptor and verify the class with ASM and
   `-Xverify:all`.
2. Bind each `DataNode` object to a logical startup episode, DN slot, and
   configured data directory before its background service actors start.
   Register its real IPC listener from `DataNode.getIpcPort()` and its
   transfer endpoint from `getXferAddress()` (`DataNode.java:2319–2327`).
   Bind the two actual NameNode RPC endpoints to NN0/NN1 and their runtime
   block-pool IDs. Retain all raw addresses in the receipt; map to stable
   logical roles only when exactly one endpoint matches. Unknown or
   ambiguous addresses fail closed.
3. HDFS-31 records the `dn0.transferBlock` owner, raw block-pool ID and
   block ID; the later guard must have that exact runtime tuple. HDFS-32
   selects the first target guard on the **second distinct registered DN**,
   then binds its raw block-pool ID, `force` argument, and service-present
   branch. An object hash alone is insufficient across a restart or test
   iteration. Do not merge the two federated NNs under one `NN` key.
4. An eligible RPC fault must carry its raw endpoint, unambiguous logical
   peer, call site, call ordinal, and owner evidence. An RPC to a DataNode's
   IPC endpoint can be tied to that DN; an RPC to an NN is eligible only when
   the caller is bound to the selected DN's BPOfferService and the matching
   block pool. A client-side NN RPC on an unrelated thread is not evidence
   for that DN. If the original workload exposes no such RPC before the
   target, add a block-pool-specific file or data-transfer I/O hook, or mark
   this workload as having no eligible fault point. Do not silently relax
   endpoint matching.

## Launch and audit gate

One shared overlay can implement the endpoint/actor registry and the two
target hooks, while preserving separate original JUnit methods and
checkpoints. First run offline bytecode and mismatch tests. Then run each
unchanged JUnit twice with no faults in isolated scratch directories and
port-0 MiniDFSCluster listeners. Both healthy receipts must have the same
overlay digest, stable logical actor/peer selectors, exact target identity,
production JaCoCo and branch feedback, and the same expected throw signature.
Use fresh raw endpoint values per run; never require ephemeral ports to be
numerically equal between runs.

For each fault trial, require the full ordered plan to match and apply, a
same-actor eligible I/O sequence, and the chosen guard after the final fault.
Compare target throws to the healthy actor/guard signature, then replay and
read source before marking a new bug. Target loss or a JUnit failure caused
before the selected guard is an attempted, non-effective trial. Start new
per-case budgets at **zero**: 80 effective trials with at most eight faults,
conditionally 128 effective with at most ten faults. Preserve the old
80-attempt raw archives and results separately.
