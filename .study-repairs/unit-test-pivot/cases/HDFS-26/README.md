# HDFS-26 independent original-JUnit fault campaign

> **Actor identity recheck pending.** The earlier original-JUnit fault campaign matched a normalized RPC thread/port selector, while its target probe did not record the DataNode, storage directory, or startup episode needed to join the fault to this check. The former trial, coverage, and measured-time figures below are retained as historical coarse-actor observations in `result.json` under `legacy_coarse_actor`; they are not counted as current high-quality completion. See the [independent actor audit](../../independent-audits/hdfs-hbase-quality-20261007/actor-identity-screen.md).

- Target: `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java:626` in `BlockPoolSliceStorage.doRollback(StorageDirectory,NamespaceInfo)`; guard `previousLV >= HdfsServerConstants.DATANODE_LAYOUT_VERSION && previousCTime <= nsInfo.getCTime()`. Exact bytecode sites: `BlockPoolSliceStorage.doRollback#L619-IF_ICMPLT`, `BlockPoolSliceStorage.doRollback#L620-IFLE`.
- Workload: unchanged Hadoop 3.4.3 `org.apache.hadoop.hdfs.TestDFSRollback#testRollback` (MiniDFSCluster).
- Healthy run: 6 exact branch events, 0 target exceptions.
- Fault campaign: 80 trials in 3971.045 attributed JUnit seconds; 78 exact ordered injections; 69 target-retaining trials.
- Post-fault target exceptions: 0; 0 trials matched the expected version guard. Bug mark: `none`.
- New production coverage with target retained: 25 methods, 108 covered-branch counts, 285 probes, 246 lines.
- Post-fault target branch outcomes by exact bytecode site: `{"BlockPoolSliceStorage.doRollback#L619-IF_ICMPLT": {"false": 148, "true": 0}, "BlockPoolSliceStorage.doRollback#L620-IFLE": {"false": 148, "true": 0}}`.
- Status: `quality_complete`; budget 80 trials / 8 ordered faults.

- Tested sequence depths: `{1: 57, 2: 6, 3: 8, 4: 4, 5: 2, 6: 1, 7: 1, 8: 1}`; target-retaining depths: `{1: 51, 2: 5, 3: 4, 4: 4, 5: 2, 6: 1, 7: 1, 8: 1}`; applied fault types: `{'EOFException': 34, 'FileNotFoundException': 7, 'IOException': 40, 'SocketTimeoutException': 53}`.

The case-local ASM 9.6 overlay instruments original Hadoop classes; JaCoCo 0.8.15 records production coverage. Fault selection uses only observed RPC/VERSION-file I/O and production coverage feedback. No GraphChecker prewoven classes, runtime jar, region skeleton, static I/O map, causal graph, closure, Docker cluster, or handwritten workload is used. Target-lost trials count toward the budget but provide no feedback.

Source review: doRollback reads the previous VERSION and checks layout version and cTime against the running software and NamespaceInfo. The explicit InconsistentFSStateException rejects rollback to a newer state; a matching rejection alone is expected behavior.

Evidence: [result](result.json), [trial ledger](trial-ledger.csv), [checkpoint](independent/evidence/campaign-state.json), [healthy manifest](independent/evidence/healthy/manifest.json), [ASM probe](../HDFS-24/independent/src/HdfsStorageProbe.java), [patcher](../HDFS-24/independent/src/PatchHdfsStorage.java).
