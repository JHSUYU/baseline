# HDFS-27 independent original-JUnit fault campaign

> **Actor identity recheck pending.** The earlier original-JUnit fault campaign matched a normalized RPC thread/port selector, while its target probe did not record the DataNode, storage directory, or startup episode needed to join the fault to this check. The former trial, coverage, and measured-time figures below are retained as historical coarse-actor observations in `result.json` under `legacy_coarse_actor`; they are not counted as current high-quality completion. See the [independent actor audit](../../independent-audits/hdfs-hbase-quality-20261007/actor-identity-screen.md).

- Target: `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java:510` in `BlockPoolSliceStorage.doUpgrade(String,StorageDirectory,NamespaceInfo,File,File,File,int,Configuration)`; guard `namespaceID == nsInfo.getNamespaceID()`. Exact bytecode sites: `BlockPoolSliceStorage.doUpgrade#L510-IF_ICMPEQ`.
- Workload: unchanged Hadoop 3.4.3 `org.apache.hadoop.hdfs.TestDFSUpgrade#testUpgrade` (MiniDFSCluster).
- Healthy run: 6 exact branch events, 0 target exceptions.
- Fault campaign: 80 trials in 3092.597 attributed JUnit seconds; 78 exact ordered injections; 48 target-retaining trials.
- Post-fault target exceptions: 0; 0 trials matched the expected version guard. Bug mark: `none`.
- New production coverage with target retained: 31 methods, 119 covered-branch counts, 288 probes, 281 lines.
- Post-fault target branch outcomes by exact bytecode site: `{"BlockPoolSliceStorage.doUpgrade#L510-IF_ICMPEQ": {"false": 0, "true": 182}}`.
- Status: `quality_complete`; budget 80 trials / 8 ordered faults.

- Tested sequence depths: `{1: 57, 2: 1, 3: 2, 4: 7, 5: 8, 6: 5}`; target-retaining depths: `{1: 46, 2: 1, 3: 1}`; applied fault types: `{'EOFException': 37, 'FileNotFoundException': 7, 'IOException': 40, 'SocketTimeoutException': 67}`.

Own mapped JUnit healthy probe: `org.apache.hadoop.hdfs.TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout` reaches the exact guard 1 time(s). Original TestDFSUpgrade#testUpgrade reaches the exact HDFS-27 bytecode guard six times and exposes more observed relevant I/O points. Its fault trials are scored separately for HDFS-24 and HDFS-27.

The case-local ASM 9.6 overlay instruments original Hadoop classes; JaCoCo 0.8.15 records production coverage. Fault selection uses only observed RPC/VERSION-file I/O and production coverage feedback. No GraphChecker prewoven classes, runtime jar, region skeleton, static I/O map, causal graph, closure, Docker cluster, or handwritten workload is used. Target-lost trials count toward the budget but provide no feedback.

Source review: doUpgrade links blocks, sets the current layout version, then asserts that stored namespaceID equals NamespaceInfo.namespaceID before writing VERSION. A post-fault AssertionError at this guard requires exact replay and source-state review before any new-bug claim.

Evidence: [result](result.json), [trial ledger](trial-ledger.csv), [checkpoint](../HDFS-24/independent/evidence/campaign-state.json), [healthy manifest](../HDFS-24/independent/evidence/healthy/manifest.json), [ASM probe](../HDFS-24/independent/src/HdfsStorageProbe.java), [patcher](../HDFS-24/independent/src/PatchHdfsStorage.java).
