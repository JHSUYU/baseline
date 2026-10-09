# HDFS-28 shared HA original-JUnit terminal audit

- Workload: unmodified Hadoop 3.4.3
  `TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization`
  (three NameNodes and three DataNodes).
- Target: `BlockRecoveryWorker.getDatanodeID(String)` site `#u12`, the
  `bpos == null` branch. Only a complete exact fault sequence followed by
  the same physical DataNode/recovery-root target check counts as an
  effective HDFS-28 visit.
- Two fresh healthy JUnit runs: 26.766 and 27.308 seconds. Both reached
  the nonfatal target check and established actor-bound RPC/file I/O.
- Natural terminal checkpoint: 512 selected attempts, 125 exact full
  sequences, 49 HDFS-28 effective trials, 0 target-exception candidates.
  Fault JUnit time: 20,581.061 seconds. `active=null` and
  `stop_reason=attempt_cap_inconclusive`; 393 queued plans remained. The
  shared ledger did not reach its own 80-effective goal. No sequence ID
  was restarted or removed to obtain the aggregate result.
- The shared ledger's maximum sequence depth remained eight because this
  ledger did not reach its individual 80-effective extension gate. Do not
  describe the aggregate conditional 128 as a depth-ten exploration.
- Production JaCoCo gain over shared healthy seeds: 1,878 probes,
  400 methods, 773 branch-count entries. These whole-workload gains do
  not by themselves establish new target behavior.
- Independent `audit_raw.py` re-read all 512 manifests, plans, runtime
  traces and JaCoCo evidence: HDFS-28 effective 49, target candidates 0,
  errors 0. Terminal checkpoint SHA-256:
  `a30efda6d02fb60279bdc1c52f2783ecd0a701b4cf71858b7724d802eed57455`;
  raw audit SHA-256:
  `557107257b70e42d58b7faca6171ba47977ccea30a1fc87d62dedcf1ac75a75d`.
- Source SHA-256 matches between node1 and node0: campaign
  `824df96b2fbbcfeb2d29d444443a837f414d183f90e28fdf2789c8a07a40b93b`,
  released-JUnit runner
  `113bda1971e27d9d15eb4d71a54f914d5d1b2c37e0373bdc89af907e8b3a9188`,
  independent auditor
  `0833abe001c9ea065e499e010befcec18e31f6741ac8aaf3564600b6e911bc57`.

The node1 terminal archive contains 5,215 files totaling 4,461,927,173
uncompressed bytes; the nested alternate JUnit ledger and ephemeral
scratch are excluded. The zstd archive is 264,522,592 bytes, SHA-256
`7a9a126b7d8038835635bf0acebf59486b5cbb498960c3bfda9b9dc4976dfbe6`;
its file manifest SHA-256 is
`e326b5f81e09ca32832e27edf2538e307f97606d25a09e01004da9e8d4030002`.
Streaming extraction on node1 and node0 verified all 5,216 tar members
(including the manifest) against expected SHA and length without a second
expanded copy. The expanded node1 raw remains intact. Node0 stores the
terminal checkpoint/raw-audit under separate aliases so the earlier local
checkpoint is not overwritten.
