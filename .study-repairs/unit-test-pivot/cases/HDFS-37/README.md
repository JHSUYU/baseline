# HDFS-37 independent original-JUnit fault campaign

- Target: `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java:947` in `DataStorage.doRollback(StorageDirectory,NamespaceInfo)`; guard `previousLV >= DataNodeLayoutVersion.getCurrentLayoutVersion() && previousCTime <= nsInfo.getCTime()`. Exact bytecode sites: `DataStorage.doRollback#L940-IF_ICMPLT`, `DataStorage.doRollback#L941-IFLE`.
- Workload: unchanged Hadoop 3.4.3 `org.apache.hadoop.hdfs.TestDFSRollback#testRollback` (MiniDFSCluster).
- Healthy run: 12 exact branch events, 3 target exceptions.
- Fault campaign: 80 trials in 4388.865 attributed JUnit seconds; 77 exact ordered injections; 61 target-retaining trials.
- Post-fault target exceptions: 132; 58 trials matched the expected version guard. Bug mark: `none`.
- New production coverage with target retained: 16 methods, 77 covered-branch counts, 169 probes, 153 lines.
- Post-fault target branch outcomes by exact bytecode site: `{"DataStorage.doRollback#L940-IF_ICMPLT": {"false": 207, "true": 0}, "DataStorage.doRollback#L941-IFLE": {"false": 75, "true": 132}}`.
- Status: `quality_complete`; budget 80 trials / 8 ordered faults.

- Tested sequence depths: `{1: 57, 2: 3, 3: 1, 4: 5, 5: 8, 6: 6}`; target-retaining depths: `{1: 50, 2: 3, 3: 1, 4: 3, 5: 3, 6: 1}`; applied fault types: `{'EOFException': 34, 'FileNotFoundException': 9, 'IOException': 58, 'SocketTimeoutException': 43}`.

The case-local ASM 9.6 overlay instruments original Hadoop classes; JaCoCo 0.8.15 records production coverage. Fault selection uses only observed RPC/VERSION-file I/O and production coverage feedback. No GraphChecker prewoven classes, runtime jar, region skeleton, static I/O map, causal graph, closure, Docker cluster, or handwritten workload is used. Target-lost trials count toward the budget but provide no feedback.

Source review: DataStorage.doRollback reads previous/VERSION and rejects a previous layout version older than running software or a previous cTime newer than NamespaceInfo. TestDFSRollback intentionally writes Long.MAX_VALUE as previous cTime and expects this exact exception. A post-fault guard throw with the same normalized state is an expected version rejection; a novel state must be replayed and reviewed before any bug claim.

Evidence: [result](result.json), [trial ledger](trial-ledger.csv), [checkpoint](independent/evidence/campaign-state.json), [healthy manifest](independent/evidence/healthy/manifest.json), [ASM probe](independent/src/HdfsStorageProbe.java), [patcher](independent/src/PatchHdfsStorage.java).
