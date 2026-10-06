# HDFS-34 independent original-JUnit fault campaign

- Target: `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java:744` in `DataStorage.doTransition(StorageDirectory,NamespaceInfo,StartupOption,List,Configuration)`; guard `!federationSupported && getNamespaceID() == nsInfo.getNamespaceID()`.
- Workload: unchanged Hadoop 3.4.3 `org.apache.hadoop.hdfs.TestDFSStartupVersions#testVersions` (20 VERSION variants, MiniDFSCluster).
- Healthy run: 6 exact target checks; 3 target IOExceptions.
- Fault campaign: 80 trials in 3245.356 attributed JUnit seconds; 78 exact ordered injections; 20 target-retaining trials.
- Post-fault target IOExceptions: 32; 20 trials matched the expected incompatible VERSION guard response. New-bug mark: `none`.
- New production coverage on target-retaining trials: 5 methods, 35 covered-branch counts, 82 probes, 59 lines.
- Final status: `quality_complete`; budget 80 trials / 8 ordered faults.

The probe is a case-local ASM 9.6 overlay on the original Hadoop jars. JaCoCo 0.8.15 records production coverage. Runtime fault selection uses observed RPC and VERSION-file I/O identities plus coverage feedback. No GraphChecker prewoven classes, runtime jar, region skeleton, static I/O map, causal graph, closure, Docker cluster, or handwritten workload is used. A fault that prevents the exact target from executing is counted as a trial but contributes no fuzz feedback.

Source review: TestDFSStartupVersions.testVersions intentionally starts DataNodes with 20 VERSION variants. The selected storage guards compare VERSION namespaceID, blockpoolID, clusterID, or CTime with NameNode NamespaceInfo. The original test expects many incompatibilities and checks whether each DataNode starts; a matching version rejection alone is not a new bug.

Evidence: [machine-readable result](result.json), [per-trial ledger](trial-ledger.csv), [shared campaign state](../HDFS-22/independent/evidence/campaign-state.json), [healthy manifest](../HDFS-22/independent/evidence/healthy/manifest.json), [ASM probe](../HDFS-22/independent/src/Hdfs22Probe.java), [patcher](../HDFS-22/independent/src/PatchHdfs22.java).
