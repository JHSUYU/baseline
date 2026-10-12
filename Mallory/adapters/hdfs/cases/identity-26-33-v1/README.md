# HDFS-26 and HDFS-33 DataNode identity overlay

The source proposal is now built in an isolated adapter copy. `prepare.py` SHA-checks the original HDFS adapter and reads the prior healthy results, then regenerates two adapter patches, two config templates, and `preflight.json`. `run_focused_audit.py` tests the **shaded production JAR** against seven real Hadoop 3.4.3 class files without starting a cluster. `audit-receipt.json` pins the JAR, patched source, exact input class bytes, and passing ASM verification output. `build-preflight.json` pins the two materialized healthy configs. Nothing here changes a running adapter, canonical checklist, or HDFS source tree.

## Observed gap

The original healthy tests reached the exact nonthrowing target: three HDFS-26 invocations (six branch events) and one HDFS-33 invocation (two branch events). All had actor `unknown`; neither run is a valid named-node seed. The v13 configs included the target classes but omitted `MiniDFSCluster`, its `Builder`, `DataStorage`, and `DataNode`, so the adapter's concrete DataNode registration path could not execute.

HDFS-26 tests rollback during a new DataNode startup. `MiniDFSCluster.startDataNodes` calls `DataNode.instantiateDataNode`; the `DataNode` constructor enters `startDataNode`, which calls `BlockPoolManager.refreshNamenodes`. Block-pool actor threads can reach `BlockPoolSliceStorage.doRollback` before the existing `dataNodeStarting` hook at the later `runDatanodeDaemon` call. HDFS-33 invokes `DataStorage.VolumeBuilder.build` while hot-adding a volume to the already built cluster; `VolumeBuilder.storage` is the concrete `DataStorage` of that DataNode.

## Binding rule

The overlay tags the exact `Configuration` object passed by `MiniDFSCluster.startDataNodes` to `DataNode.instantiateDataNode` with the cluster's next DataNode index and epoch. Immediately before `BlockPoolManager.refreshNamenodes`, it uses the same `DataNode.getConf()` object to register that DataNode, its `DataStorage`, and its `BlockPoolManager`. The existing `DataStorage.getBlockPoolSliceStorage` hook then registers the concrete block-pool slice; the existing `BlockPoolSliceStorage` and `VolumeBuilder` scopes use their registered receiver/storage object to name the target actor. The later `dataNodeStarting` hook must agree on the same cluster/index/epoch and clears the provisional config mapping. Constructor retries with the same config retain the same logical startup identity.

The binding is an object-identity relation from the actual MiniDFSCluster startup path. It does not infer a DataNode from a thread name, method name, target class, or coarse root. Other DataNode construction paths have no staged config and receive no new binding.

## Healthy-only admission

1. The adapter was built from an isolated source copy at `data/mallory/adapter-builds/identity-26-33-v1`, using the frozen agent. Both patches passed `git apply --check`. The two existing adapter unit tests passed. The production shaded JAR transformed and ASM-verified `MiniDFSCluster`, `DataNode`, `MiniDFSCluster$Builder`, `DataStorage`, `BlockPoolSliceStorage`, `DataStorage$VolumeBuilder`, and `BPServiceActor` from the pinned Hadoop 3.4.3 compiled tree. This checks the hook placement and bytecode integrity, not runtime node identity.
2. The materialized `HDFS-26-healthy-only.json` and `HDFS-33-healthy-only.json` pin that JAR and compiled target classes and pass `Mallory.core.campaign.validate_config`. They currently point to `/users/ZhenyuLi/.mallory-worktrees/hdfs`; dispatch must reserve that HDFS source tree exclusively or re-materialize for another isolated tree with matching class SHA. The templates remain available for re-materialization. Use the frozen agent and core receipts already specified there.
3. Admit one fault-free JUnit per case. Require exactly one passing JUnit, the exact nonthrowing target on a named `hdfs-cluster-*/dn*` actor, no unknown target event, and a root-free event-time graph path. Check that HDFS-26's multiple target events belong to a concrete registered actor/epoch; check HDFS-33's builder resolves through its `DataStorage` object. Record any transformer or registration error as a failed calibration.
4. Do not launch a fault trial or promote a campaign from this overlay. A healthy named-target result is prerequisite evidence for later fault-door selection and closure auditing.

Source, config, patch, and prior-result hashes are in `preflight.json`.
