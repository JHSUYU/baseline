# HDFS-24 independent original-JUnit fault campaign

- Target: `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java:424` in `BlockPoolSliceStorage.doTransition(StorageDirectory,NamespaceInfo,StartupOption,List<Callable<StorageDirectory>>,Configuration)`; guard `getLayoutVersion() > HdfsServerConstants.DATANODE_LAYOUT_VERSION || getCTime() < nsInfo.getCTime()`. Exact bytecode sites: `BlockPoolSliceStorage.doTransition#L414-IF_ICMPGT`, `BlockPoolSliceStorage.doTransition#L415-IFGE`.
- Workload: unchanged Hadoop 3.4.3 `org.apache.hadoop.hdfs.TestDFSUpgrade#testUpgrade` (MiniDFSCluster).
- Healthy run: 18 exact branch events, 3 target exceptions.
- Fault campaign: 80 trials in 3092.597 attributed JUnit seconds; 78 exact ordered injections; 53 target-retaining trials.
- Post-fault target exceptions: 123; 49 trials matched the expected version guard. Bug mark: `none`.
- New production coverage with target retained: 31 methods, 121 covered-branch counts, 290 probes, 282 lines.
- Post-fault target branch outcomes by exact bytecode site: `{"BlockPoolSliceStorage.doTransition#L414-IF_ICMPGT": {"false": 301, "true": 0}, "BlockPoolSliceStorage.doTransition#L415-IFGE": {"false": 123, "true": 178}}`.
- Status: `quality_complete`; budget 80 trials / 8 ordered faults.

- Tested sequence depths: `{1: 57, 2: 1, 3: 2, 4: 7, 5: 8, 6: 5}`; target-retaining depths: `{1: 43, 2: 1, 3: 2, 4: 3, 5: 4}`; applied fault types: `{'EOFException': 37, 'FileNotFoundException': 7, 'IOException': 40, 'SocketTimeoutException': 67}`.

The case-local ASM 9.6 overlay instruments original Hadoop classes; JaCoCo 0.8.15 records production coverage. Fault selection uses only observed RPC/VERSION-file I/O and production coverage feedback. No GraphChecker prewoven classes, runtime jar, region skeleton, static I/O map, causal graph, closure, Docker cluster, or handwritten workload is used. Target-lost trials count toward the budget but provide no feedback.

Source review: doTransition compares on-disk DataNode layout version and cTime with NameNode NamespaceInfo. Its IOException explicitly rejects storage newer than the namespace. TestDFSUpgrade intentionally includes incompatible upgrade variants; a matching rejection alone is expected behavior.

Evidence: [result](result.json), [trial ledger](trial-ledger.csv), [checkpoint](independent/evidence/campaign-state.json), [healthy manifest](independent/evidence/healthy/manifest.json), [ASM probe](independent/src/HdfsStorageProbe.java), [patcher](independent/src/PatchHdfsStorage.java).
