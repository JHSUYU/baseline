# HDFS 3.4.3: 50-candidate CrashFuzz-style baseline

## Sample and procedure

GraphChecker marked 532 of 10,718 HDFS sites as candidate ad hoc
coordination. We froze a seeded random sample of 50 (`selected50.json`,
seed `20261001`) before running the experiments. The first ten preserve the
earlier sample; the remaining 40 were drawn without replacement from the
other 522. `mapped50.json` records the compiled HDFS 3.4.3 oracle for every
site: 43 unique source-line throws, six exact precondition calls, and one
source line with three compiled throws (draw 40).

For each reachable target we ran an independent healthy seed and bounded
crash/reboot mutations. Normal, short-circuit/RAM_DISK, cache, rich HDFS,
snapshot, disk-balancer, corrupt-block, encryption-zone, and QJM workloads
exposed different methods. Targeted quota and directory-snapshot workloads
reached calls missed by the initial workloads. The agent recorded methods,
branches, calls, state accesses, and transport/async events; the scheduler
ranked observed fault points using the target closure and kept exploratory
choices. We separately audited whether the target method, a mapped guarding
branch or exact call, the scheduled fault, and the target exception occurred.
For throw sites, the current target anchor is method entry when one guarding
branch cannot be mapped reliably; closure guidance is therefore weaker for
those sites than for exact precondition-call targets.

The initial additional batch used one healthy seed plus one fault trial per
reachable site. Focused retries used up to three fault trials. Five methods
absent from healthy discovery received crash/reboot searches; four also had
fault points restricted to late write-block events. Every trial retained its
raw trace, fault sequence, graph feedback, workload result, and readback
checker result.

## Results

| Measure | Result |
| --- | ---: |
| Random sites selected | 50 / 532 candidates |
| Sites with at least one matched fault trial | 50 / 50 |
| Matched fault trials / planned fault trials across all attempts | 89 / 104 |
| Healthy discovery entered the target method | 45 / 50 |
| Target method entered in any run | 47 / 50 |
| Mapped direct guard or exact precondition call observed | 34 / 50 |
| Target method still unobserved | 3 / 50: draws 18, 43, 47 |
| Distinct sites with an exact target throw | 1 / 50: draw 42 |
| Confirmed ad hoc coordination failures | 0 |

The direct-guard figure is **conservative**: it uses the nearest bytecode
branch that skips the selected throw. All 47 entered methods had some branch
events, but a branch elsewhere in a method does not prove that its selected
check executed. The per-site evidence is in `audit50.json`.

Two checks demonstrate the intended CrashFuzz recovery feedback:

| Draw | Healthy run | Faulted run | Outcome |
| --- | --- | --- | --- |
| 17 | `recoverRbwImpl` absent | Crash dn1 at `BlockReceiver.receivePacket`; dn2 and dn3 entered `recoverRbwImpl` and its mapped B6 guard | No target throw; readback passed |
| 41 | `checkUCBlock` absent | Crash dn2 at `BlockReceiver.receivePacket`; NameNode entered `checkUCBlock` twice and its mapped B4 guard | No target throw; readback passed |

Draw 42 produced an exact-location `IOException` after crashing dn1 at the
`BlockReceiver.receiveBlock` entry. Both automatic replays reproduced the
throw, and the faulted run and both replays passed HDFS readback. Bytecode
offset 1724 is a compiler-generated rethrow after `finally` cleanup at source
line 1115. The observation is expected pipeline fault propagation, **not evidence of a
coordination defect**. The original healthy run did not throw there.

## Coverage limits

- Draws 18 and 43 (`updateReplicaUnderRecovery` overloads) stayed
  unobserved even after matched crashes at late packet-receive points; they
  may require a lease or replica recovery scenario with an unfinished file.
- Draw 47 needs a client state that marks a DataNode as restarting. The
  bounded Docker crash/reboot runs did not reach that state.
- Thirteen sites entered their method but had no event at the conservatively
  mapped direct guard or exact call. Draw 16, for example, needs registration
  with a second block pool to execute its inconsistent-token configuration
  branch. These are method coverage, not established check coverage.
- Draw 40 maps to three `athrow` instructions on one source line; future
  exceptions there need bytecode-offset attribution.
- Draw 4 was rerun with its corrected bytecode throw at line 1827: two
  fault trials matched, the guard ran, and no exact target throw occurred.

The budget and workloads bound these negative observations. No result here
proves a selected check safe under all crash sequences.

## Per-site audit

`audit50.json` is the machine-readable source for the following compact
table. “Direct check” means the mapped guarding branch or exact precondition
call had an event. “Matched” counts fault **trials**, excluding healthy seeds
and confirmation replays. A method seen only after a fault is marked
`fault only`.

| # | Method | Method reach | Direct check | Matched | Exact throw |
| ---: | --- | --- | --- | ---: | --- |
| 01 | `ShortCircuitRegistry.registerSlot` | healthy | yes | 3 | no |
| 02 | `RamDiskAsyncLazyPersistService.addVolume` | healthy | yes | 2 | no |
| 03 | `FSDirAclOp.unprotectedRemoveAcl` | healthy | yes | 3 | no |
| 04 | `FSEditLog.checkForGaps` | healthy | yes | 6 | no |
| 05 | `BlockManager.dumpBlockMeta` | healthy | yes | 3 | no |
| 06 | `StorageTypeStats.addStorage` | healthy | yes | 2 | no |
| 07 | `BlockSender.<init>` | healthy | yes | 1 | no |
| 08 | `BlockTokenSecretManager.retrieveDataEncryptionKey` | healthy | yes | 3 | no |
| 09 | `CacheReplicationMonitor.addNewPendingCached` | healthy | yes | 5 | no |
| 10 | `CachePoolInfo.validate` | healthy | yes | 2 | no |
| 11 | `DataNode.getDNRegistrationForBP` | healthy | yes | 1 | no |
| 12 | `NameNodeRpcServer.verifySoftwareVersion` | healthy | no | 1 | no |
| 13 | `FSDirectory.getStorageTypeDeltas` | healthy | yes | 2 | no |
| 14 | `DiskBalancer.createWorkPlan` | healthy | yes | 1 | no |
| 15 | `EditsDoubleBuffer.close` | healthy | yes | 1 | no |
| 16 | `DataNode.registerBlockPoolWithSecretManager` | healthy | no | 1 | no |
| 17 | `FsDatasetImpl.recoverRbwImpl` | fault only | yes | 4 | no |
| 18 | `FsDatasetImpl.updateReplicaUnderRecovery` | unreached | no | 4 | no |
| 19 | `FSEditLogLoader.addNewBlock` | healthy | yes | 1 | no |
| 20 | `DataXceiver.requestShortCircuitFds` | healthy | yes | 1 | no |
| 21 | `RamDiskAsyncLazyPersistService.queryVolume` | healthy | yes | 1 | no |
| 22 | `DataStreamer.run` | healthy | no | 1 | no |
| 23 | `ShortCircuitRegistry.createNewMemorySegment` | healthy | yes | 1 | no |
| 24 | `FsDatasetImpl.getBlockInputStream` | healthy | yes | 1 | no |
| 25 | `FsDatasetImpl.createTemporary` | healthy | no | 3 | no |
| 26 | `XAttrFormat.toBytes` | healthy | yes | 1 | no |
| 27 | `INodeReference$WithName.assertReferences` | healthy | no | 1 | no |
| 28 | `DataNode.getBPOSForBlock` | healthy | yes | 1 | no |
| 29 | `FSDirConcatOp.verifySrcFiles` | healthy | yes | 1 | no |
| 30 | `FSEditLogLoader.applyEditLogOp` | healthy | no | 1 | no |
| 31 | `LightWeightHashSet$LinkedSetIterator.next` | healthy | yes | 1 | no |
| 32 | `QuorumCall.checkAssertionErrors` | healthy | no | 1 | no |
| 33 | `INodeReference$DstReference.destroyAndCollectBlocks` | healthy | yes | 1 | no |
| 34 | `FSEditLogLoader.addNewBlock` | healthy | yes | 1 | no |
| 35 | `FileDiffList.saveSelf2Snapshot` | healthy | yes | 1 | no |
| 36 | `BlockManager.findAndMarkBlockAsCorrupt` | healthy | yes | 1 | no |
| 37 | `BlockInfoContiguous.numNodes` | healthy | yes | 1 | no |
| 38 | `SnapshotManager.checkNestedSnapshottable` | healthy | no | 1 | no |
| 39 | `FSDirectory.verifyMaxDirItems` | healthy | no | 2 | no |
| 40 | `BlockReceiver.receiveBlock` | healthy | no | 1 | no |
| 41 | `FSNamesystem.checkUCBlock` | fault only | yes | 4 | no |
| 42 | `BlockReceiver.receiveBlock` | healthy | no | 1 | yes |
| 43 | `FsDatasetImpl.updateReplicaUnderRecovery` | unreached | no | 5 | no |
| 44 | `PBHelperClient.convert` | healthy | no | 1 | no |
| 45 | `DirectorySnapshottableFeature.renameSnapshot` | healthy | yes | 1 | no |
| 46 | `INodeFile$HeaderFormat.getBlockLayoutRedundancy` | healthy | no | 1 | no |
| 47 | `DataStreamer$ErrorState.checkRestartingNodeDeadline` | unreached | no | 3 | no |
| 48 | `FsDatasetAsyncDiskService.addVolume` | healthy | yes | 1 | no |
| 49 | `FileJournalManager.recoverUnfinalizedSegments` | healthy | yes | 1 | no |
| 50 | `INodeReference$DstReference.destroyAndCollectBlocks` | healthy | yes | 1 | no |
