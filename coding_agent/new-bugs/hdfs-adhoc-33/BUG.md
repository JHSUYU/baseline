# hdfs-adhoc-33: A volume hot-add that races with block-pool removal (refreshNamenodes) fails with AssertionError/NPE in VolumeBuilder.build and leaves the new volume's storage directory locked, so the disk cannot be added until the DataNode restarts.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java:259`, `DataStorage.VolumeBuilder.build()`, throws `java.lang.AssertionError` when `assert bpStorage != null;   (bpStorage = this.storage.bpStorageMap.get(bpid))`
- Starting test: `org.apache.hadoop.hdfs.server.datanode.TestDataNodeHotSwapVolumes#testAddOneNewVolume`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** On a federated DataNode, an admin hot-adds a data volume with reconfig dfs.datanode.data.dir. While FsDatasetImpl.addVolume loads the block pools on the new disk (a slow du, simulated by a latch in a GetSpaceUsed plugged in through fs.getspaceused.classname), the admin also runs refreshNamenodes with one nameservice removed, which shuts that block pool down.

**Why (root cause in the source):** DataNode.refreshVolumes takes an nsInfos snapshot outside any lock (datanode/DataNode.java:1284-1289). FsDatasetImpl.addVolume calls prepareVolume, which registers per-pool storage, and later builder.build() (fsdataset/impl/FsDatasetImpl.java:515-561). Nothing serialises this with DataNode.shutdownBlockPool -> DataStorage.removeBlockPoolStorage (DataNode.java:2151-2170, DataStorage.java:1421). So build() looks up a block pool that is no longer in bpStorageMap and hits 'assert bpStorage != null' (DataStorage.java:259). With assertions off, the next line bpStorage.addStorageDir throws a NullPointerException. That unchecked error escapes addVolume's IOException cleanup: sd.unlock() is never called, the volume reference and lazy-persist thread are leaked, and the volume is never registered. refreshVolumes reports 'FAILED to ADD' (DataNode.java:1343-1347). A retry of the hot-add then finds the storage directory still locked by this JVM: Storage.tryLock catches OverlappingFileLockException and returns null, which leads to 'already locked' (common/Storage.java:950-956). The disk cannot be added until the DataNode restarts. Both admin operations are valid, and the latch only widens a window that real disk I/O can produce.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Both operations are valid admin actions that a real deployment can run at the same time: hot-swapping a disk (dfsadmin -reconfig datanode) and removing a federated nameservice (dfsadmin -refreshNamenodes, or a block pool shutting down). The hot-add path coordinates per-block-pool state in two steps. prepareVolume() registers or reads the BlockPoolSliceStorage, and build() later expects it to still exist. Nothing stops shutdownBlockPool() from removing it in between, and refreshVolumes keeps using a stale nsInfos snapshot. So the state build() receives is one that correct coordination should never produce (a builder holding storage dirs for a block pool that DataStorage no longer has), and the request itself was valid. Consequence: the volume hot-add fails with an unchecked error rather than skipping the removed block pool. With assertions off (production), build() goes on to bpStorage.addStorageDir() and throws a NullPointerException. That error escapes addVolume's IOException handling, so the new volume is left half-added: the storage directory was locked and formatted by prepareVolume but is never registered in DataStorage, and sd.unlock() is never called. FsDatasetImpl.addVolume also obtains a volume reference and sets up a lazy-persist thread before build() and never undoes either. A retry of the reconfiguration may then fail because the directory is still locked; this last point follows from reading the code and was not tested. The fix is to skip or tolerate block pools that were removed in the meantime, or to serialize block-pool removal with volume addition.

**Execution (agent):** Federated MiniDFSCluster: 2 nameservices (ns1, ns2), 1 DataNode with 2 volumes, serving block pools BP1 (ns1) and BP2 (ns2). (1) Admin hot-adds a disk: reconfigure dfs.datanode.data.dir (DataNode.reconfigurePropertyImpl -> refreshVolumes). refreshVolumes takes a snapshot nsInfos=[BP1,BP2] and runs FsDatasetImpl.addVolume on an executor thread. addVolume calls DataStorage.prepareVolume, which calls getBlockPoolSliceStorage() for BP1 and BP2 (registering both in bpStorageMap) and loads the per-bp storage dirs into the VolumeBuilder. Then it runs fsVolume.addBlockPool/getVolumeMap for each bp on the new disk. That step does disk I/O and can be slow (du, scanning replicas). The test widens this window with a GetSpaceUsed implementation set through the standard fs.getspaceused.classname setting, which waits on a latch while the new volume's BlockPoolSlice is built. (2) At the same time, the admin removes ns2 from the DataNode's config and runs refreshNamenodes (dfsadmin -refreshNamenodes). BlockPoolManager stops the BPOfferService of ns2. Its actor thread exits and calls DataNode.shutdownBlockPool(BP2), which calls FsDatasetImpl.shutdownBlockPool(BP2) and then DataStorage.removeBlockPoolStorage(BP2), so BP2 leaves bpStorageMap. No lock or check coordinates this with the in-flight addVolume. (3) The latch is released. addVolume finishes loading the block pools and calls VolumeBuilder.build(). build iterates its bpStorageDirMap (still holding BP2 from the stale snapshot) and looks up bpStorageMap.get(BP2), which returns null. 'assert bpStorage != null' fails with java.lang.AssertionError at DataStorage.java:259 (FsDatasetImpl.addVolume:559 <- DataNode$2.call:1322). The reconfiguration fails with 'FAILED to ADD ... java.util.concurrent.ExecutionException: java.lang.AssertionError'.

**Stack frame (agent):** at org.apache.hadoop.hdfs.server.datanode.DataStorage$VolumeBuilder.build(DataStorage.java:259)

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.datanode.TestDataNodeHotSwapVolumesRefreshNamenodesRace#testAddVolumeRacesWithBlockPoolRemoval`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.datanode.TestDataNodeHotSwapVolumesRefreshNamenodesRace#testAddVolumeRacesWithBlockPoolRemoval' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDataNodeHotSwapVolumesRefreshNamenodesRace.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: java.lang.AssertionError`, frame `at org.apache.hadoop.hdfs.server.datanode.DataStorage$VolumeBuilder.build(DataStorage.java:259)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h11m | 1 | 1,498,985 | 62 | 25,537 | 71,826 | 1,401,560 | $1.37 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
