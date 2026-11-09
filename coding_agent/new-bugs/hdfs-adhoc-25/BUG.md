# hdfs-adhoc-25: Concurrent hot-swap volume adds race on shared BlockPoolSliceStorage fields, so a healthy volume is rejected with a spurious cTime mismatch and reported as failed.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java:185`, `BlockPoolSliceStorage.loadStorageDirectory(NamespaceInfo, StorageLocation, StartupOption, List<Callable<StorageDirectory>>, Configuration)`, throws `java.io.IOException` when `!doTransition(sd, nsInfo, startOpt, callables, conf) && getCTime() != nsInfo.getCTime()`
- Starting test: `org.apache.hadoop.hdfs.TestDFSStartupVersions#testVersions`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** After a non-rolling NN upgrade (new cTime), the admin hot-adds in one reconfiguration an old disk that missed the upgrade (old cTime) and a brand-new disk. DataNode.refreshVolumes runs addVolume for each in parallel threads, and spy delays on NamespaceInfo.getCTime pin a real interleaving.

**Why (root cause in the source):** DataNode.refreshVolumes (DataNode.java ~L1312-1323) submits FsDatasetImpl.addVolume for every new location to a thread pool. DataStorage.prepareVolume (DataStorage.java L324-346) is unsynchronized and calls loadBpStorageDirectories on the one shared BlockPoolSliceStorage per block pool. loadStorageDirectory/doTransition (BlockPoolSliceStorage.java L149-195, L369-419) keep per-directory state read by readProperties (layoutVersion/cTime/namespaceID) in shared instance fields. The stale volume's readProperties overwrites this.cTime between the new volume's doTransition comparison (L404-406) and the re-check at L184-186. The healthy, just-formatted volume is then rejected with 'Datanode CTime ... is not equal to namenode CTime', and FsDatasetImpl.addVolume records a volume failure (L521-524). The spies only delay and return real values, so this is an interleaving the scheduler can produce. The reverse interleaving can also make a stale volume skip its upgrade and get the NN cTime written to its VERSION.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The check is meant to reject a block-pool storage directory whose own VERSION cTime differs from the NN's. Here the directory being checked (data3) is correct: it was just formatted with cTime = NN cTime and doTransition confirmed that. The check fails only because BlockPoolSliceStorage keeps per-directory state (layoutVersion/cTime read by readProperties) in fields shared by all volumes of the block pool, and concurrent hot-swap loading (refreshVolumes adds volumes in parallel threads; prepareVolume and BlockPoolSliceStorage.loadStorageDirectory are unsynchronized) lets another volume's VERSION overwrite the field between doTransition and the check. All steps can happen in a real deployment: an NN upgrade changes cTime, a disk that was offline during the upgrade is re-added together with a new disk via 'hdfs dfsadmin -reconfig datanode ... start'. Consequence: the reconfiguration reports 'FAILED TO ADD' for a healthy volume, the volume is recorded as a volume failure, and capacity is lost until an operator retries. The same race can also flip the other way (a stale cTime seen by doTransition's comparison), wrongly making an up-to-date volume take the upgrade path or causing other spurious hot-swap failures.

**Execution (agent):** 1) A MiniDFSCluster with 1 NN and 1 DN that has two volumes, data1 and data2, is formatted, and a file is written. Both volumes' block-pool VERSION files get cTime = C0. Everything is shut down. 2) The NN is restarted with -upgrade, which gives it a new namespace cTime C1 = now() != C0. The DN restarts with only data1 (data2 is offline/unmounted, as when a disk is out during an upgrade). data1's block-pool storage is upgraded to cTime C1. data2 keeps cTime C0. 3) The admin hot-adds two volumes in one reconfiguration: the old disk data2 and a brand-new empty disk data3. DataNode.refreshVolumes calls FsDatasetImpl.addVolume for every new location in its own thread. The test makes the same two concurrent addVolume calls with the real NamespaceInfo from versionRequest(); the Mockito spies only delay getCTime() to fix the interleaving. Both threads call DataStorage.prepareVolume, which is not synchronized, and then the same shared BlockPoolSliceStorage object (one per block pool) through loadBpStorageDirectories -> loadStorageDirectory. 4) Thread A (data3): the directory is NOT_FORMATTED, so format() writes cTime C1. doTransition -> readProperties sets the shared field this.cTime = C1. It evaluates `this.cTime == nsInfo.getCTime()`: it has read this.cTime = C1 and is now inside the getCTime() call. 5) Thread B (data2): doTransition -> readProperties sets the shared this.cTime = C0, since its VERSION is pre-upgrade. It then goes on to the upgrade path (C0 < C1). 6) Thread A finishes its comparison (C1 == C1), so doTransition returns false (regular startup). Line 184 then re-reads getCTime() = C0 (written by thread B) != C1, and IOException 'Datanode CTime (=C0) is not equal to namenode CTime (=C1)' is thrown at BlockPoolSliceStorage.java:185. Hot-adding data3 fails even though its VERSION was just written with the NN's cTime. data2's upgrade succeeds.

**Stack frame (agent):** at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.loadStorageDirectory(BlockPoolSliceStorage.java:186)  (this is the `throw new IOException(...)` statement that begins on line 185: javap shows `new IOException` at bci 158 mapped to line 185 and the <init> call at bci 175, where the stack trace is captured, mapped to line 186 because the argument nsInfo.getCTime() is on that line; condition getCTime() != nsInfo.getCTime() on line 184)

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.datanode.TestBlockPoolSliceStorageConcurrentHotSwap#testConcurrentHotSwapOfStaleAndNewVolume`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.datanode.TestBlockPoolSliceStorageConcurrentHotSwap#testConcurrentHotSwapOfStaleAndNewVolume' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestBlockPoolSliceStorageConcurrentHotSwap.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: java.io.IOException: Datanode CTime (=1794074363355) is not equal to namenode CTime (=1794074367602)`, frame `at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.loadStorageDirectory(BlockPoolSliceStorage.java:186)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h05m | 1 | 664,462 | 28 | 22,004 | 58,691 | 583,739 | $1.03 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
