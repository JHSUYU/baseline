# HDFS MiniDFSCluster adapter

This adapter runs inside the selected HDFS JUnit test JVM. It registers each
MiniDFSCluster NameNode and DataNode under a logical identity before startup
RPCs, and increments the actor epoch when a NameNode or DataNode instance is
replaced. Hadoop IPC request and response events use the on-wire `clientId`,
call ID, and retry count. A DataXceiver read is bound to its owning DataNode.
MiniJournalCluster JournalNodes, IPC servers, and lazy Journals are also
registered. Missing identities remain `unknown`; the adapter does not infer
them from thread names or timestamps.

For synchronous RPC consumers, a scoped reply handoff carries the actual
response correlation through the caller's check and restores the previous
context when the caller returns. HDFS-21's `retrieveNamespaceInfo` is the
first configured consumer. The v4 healthy calibration in
`data/mallory/calibration_v4/HDFS-21/` shows the NameNode response RECV and
the `checkNNVersion` region share the same token: one real NameNode RPC door
enters the target closure (11 observed closure edges). The v3 run had zero
closure edges. `cases/identity-v4/receipt.json` pins this comparison and the
tested adapter JAR. Other response consumers need their own reviewed method
boundary before this hook can be applied.

`overlay-receipt.json` pins the clean, isolated Hadoop 3.4.3 worktree, built
class hashes, agent and adapter JAR hashes, and the Maven command template.
The worktree is precompiled; `surefire:test` uses those compiled classes. Each
case needs an exact target/check configuration and a source-reviewed `sites.json`
with fault doors. HDFS-01 provides a working example in `cases/HDFS-01/`.

For a case campaign, use `agent_transport: "surefire_argline"` and
`agent_arg_property: "maven-surefire-plugin.argLine"`. Set `agent.jar` through
`agent_jar`, and put both `adapter.jar` and `adapter.transformer` in
`agent_properties`. Include the target class, `Server$RpcCall`,
`NameNodeRpcServer`, and `DataXceiver` as applicable. The direct Maven test
selector is `-Dtest=TestClass#method`. Pin the target's compiled class hash as
`expected_target_class_sha256`; the controller rejects an unpinned healthy
seed before fault trial 1.

The HDFS-01 v1 full campaign is preserved at
`data/mallory/HDFS-01/campaigns/v1-full/`. Its 80 fault trials have 79 effective
injections and no target EOFException. An independent audit verifies its raw
archive but rejects its old graph guidance; the result remains available as
calibration evidence. HDFS-01 v2 uses fixed core release `29ab038f...`, a
SHA-pinned healthy recovery site at `DFSInputStream.readBuffer:789`, and a
separate 80-fault-trial budget (`cases/HDFS-01/campaign-v2-full.json`).
NameNode `getBlockLocations` doors enter the exact RPC closure. DataNode
readBlock doors remain exploratory until a unique data-transfer response can
be paired with the target. The v2 controller wrote to private staging and its
watcher published terminal evidence to
`data/mallory/HDFS-01/campaigns/v2-full/`. An independent audit under final
core release `5820a32d...` found 18 healthy observed-path doors, 54 healthy
closure edges, and 64 post-fault target-retaining trials among 80 fault
trials; no exact target exception was observed. The final audit is archived
at `data/mallory/HDFS-01/audits/v2-full-final5820.json`. V2 now appears in
`data/mallory/cases/HDFS-01/` and the generated checklist. V1 remains in its
versioned archive.

Existing alternate MiniDFSCluster healthy seeds for HDFS-43 and HDFS-49 are
recorded in `data/mallory/calibration_v2/`. HDFS-49's smaller
`TestSnapshot#testUpdateDirectory` avoids the trace truncation of the original
20-iteration snapshot test. HDFS-19, HDFS-20, and HDFS-22 calibrations show
named DataNode target checks under the early actor hooks. HDFS-21 requires
the additional response-continuation hook described above.

The v7 adapter scopes `MiniDFSCluster.configureNameService`'s actual
`DFSTestUtil.formatNameNode` call to the future NameNode actor. This identifies
`FSNamesystem` and its `FSImageSaver` workers before `Builder.build` returns.
The saver is connected through its concrete `SaveNamespaceContext`. HDFS-52's
`FSImageFormatProtobuf$Saver` writes the image header before snapshot
serialization, so its calibration includes that class for real file-write
doors. Its final-core healthy audit at
`data/mallory/calibration_v8/HDFS-52/` proves 162 observed-path doors
to the named target. The numbered archive records one passing JUnit run,
28.946 seconds, and per-file SHA-256 values in `calibration-receipt.json`.

The v7 adapter also pairs `BlockManager.enqueueBlockOp` with the exact
`Runnable` consumed by `BlockReportProcessingThread.processQueue`. The
alternate HDFS-17 MiniCluster workload restarts a DataNode while a file is
under construction; its real block-report queue reaches the same
`StatefulBlockInfo` check. The final-core healthy audit at
`data/mallory/calibration_v8/HDFS-17/` proves one observed-path door. The
numbered archive records one passing JUnit run, 19.749 seconds, and per-file
SHA-256 values in `calibration-receipt.json`. Earlier failed calibrations
remain in their original versioned directories. A versioned inventory selects
the alternate test for the isolated lane3 full handoff after HDFS-52.

HDFS-21's lane3 full config under `cases/identity-v4/` was promoted from a
fresh healthy seed under fixed core release `5820a32d...`; it pins the passing
JUnit, exact target catalog, named DataNode and one observed-path NameNode RPC
door.

The HDFS-39 and HDFS-50 source-reviewed alternate tests use the same pinned
target checks as their original inventory rows. Their calibration-only configs
are in `cases/alternate-v8/`; the healthy evidence and per-file SHA-256 receipts
are in `data/mallory/calibration_v9/HDFS-39/` and `HDFS-50/`. Both ran one
passing JUnit test, reached the exact check on a named NameNode, and had no
selected target exception. Final-core audits found seven and thirteen
observed-path doors, respectively. The original selectors and failed healthy
attempts remain recorded. A combined immutable alternate inventory and source
reference under `Mallory/cases/revisions/HDFS-39-50-alternates-v1.*` binds the
new selectors for their separate full campaign queue.

The smaller HDFS-49 `TestSnapshot#testUpdateDirectory` healthy seed is in
`data/mallory/calibration_v2/HDFS-49/`. Replaying its trace under final core
release `5820a32d...` confirmed six observed-path doors and 18 closure edges;
the selected check reached a named NameNode, the JUnit test passed, and the
selected throw stayed dormant. `cases/alternate-v11/` contains the formally
promoted 80-trial full config and receipt. Its durable tmux handoff waits for
the HDFS-50 and HDFS-39 lane2 queue to exit and for HDFS-39's terminal audit
before using the same lane lock. The original, trace-truncated HDFS-49 seed
remains in its earlier calibration archive.

HDFS-10 reached its exact `Journal.checkWriteRequest` throw in nine fault
trials, including six campaign replays. The injected RPC exception skipped
`startLogSegment` on one JournalNode, so that node's subsequent write request
was rejected by the intended writer-epoch guard. The other two JournalNodes
completed the quorum, and all nine JUnit runs passed. Raw plans, traces,
logs, and per-file hashes are preserved in `data/mallory/triage/HDFS-10/`;
this is an expected local guard outcome rather than a confirmed new bug.

`cases/alternate-v10/` has source-reviewed, unrun healthy calibration configs
for HDFS-31, HDFS-32, and HDFS-37. These remain preliminary until an isolated
lane runs the exact test and the fixed-core audit proves a named observed-path
fault door.

The v8 adapter adds receiver scopes for
`BlockPoolSliceStorage.loadStorageDirectory`, its queued eight-argument
`doUpgrade`, and `BlockRecoveryWorker.getDatanodeID`. The exact selected
methods in HDFS-25, HDFS-27, and HDFS-28 can execute after an outer scope
ends or on another thread. Node2 MiniCluster healthy calibrations in
`data/mallory/calibration_v8_node2/` reached all three checks on named
DataNodes, but the final-core causal audit found no observed-path door.

The v10 adapter keeps the actual `versionRequest` RPC response context through
`BPServiceActor.connectToNNAndHandshake` and into storage initialization. It
also pairs each `DataStorage.loadBlockPoolSliceStorage` upgrade Callable with
the exact `BlockPoolSliceStorage$1.call` invocation. Node2 healthy calibrations
in `data/mallory/calibration_v10_node2/` proved six target-path doors for
HDFS-25 and one for HDFS-27, with passing selected JUnit tests and named
DataNodes. The v11 adapter similarly pairs `BlockRecoveryWorker.recoverBlocks`
with its concrete daemon Runnable. Its HDFS-28 healthy calibration in
`data/mallory/calibration_v11_node2/` proved six target-path doors. These
calibrations are preserved; they do not themselves count as fault trials.

Versioned adapter JARs stay separate from the older SHA-pinned JAR used by
HDFS-49. The node2 source tree, compiled target/test classes, agent JAR, and
adapter JARs were checked by SHA-256. An inherited node0-only
`mapping.system_receipt` was removed in the later node2 configs; the clean
source and compiled artifacts are attested directly. The corrected healthy
runs are in `data/mallory/calibration_v12_node2/`; their final-core audits
prove six, one, and seven target-path doors for HDFS-25, HDFS-27, and HDFS-28.
`cases/identity-v12-node2/` contains the exact healthy and promoted full
configs, while `Mallory/cases/revisions/HDFS-25-27-28-node2-v12.manifest.json`
pins their JUnit, source, catalog, adapter, and audit evidence. Full campaigns
require their own terminal fault-trial evidence and offline audit.

Each full HDFS-01 campaign writes to a private staging directory. Run
`python3 -m Mallory.adapters.hdfs.watch_terminal --stage <stage> --destination
<terminal-archive>` in a separate tmux session. The watcher publishes
only a terminal budget or exhausted queue with a valid healthy seed. It checks
the config digest, each completed trial's plan/catalog and raw or compressed
trace/log checksums, then copies the result atomically, runs the offline causal
audit, and regenerates `data/mallory/checklist102.{json,md}`. A crashed
controller can resume from the staged checkpoint without exposing a partial
result in the final table. Audit exit 2 preserves the raw archive but marks
its graph guidance invalid.
