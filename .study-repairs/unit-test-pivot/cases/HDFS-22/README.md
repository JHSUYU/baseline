# HDFS-22: actor-qualified original-JUnit fault campaign

**Status: `quality_complete`; new-bug mark: `none`.** The unchanged Hadoop 3.4.3 `TestDFSStartupVersions#testVersions` MiniDFSCluster workload reached this exact guard in both healthy seeds. The two original JUnit seeds passed in 37.944 and 41.562 seconds. At the frozen 88-plan checkpoint prefix, 80 strictly injected trials reached the same DataNode actor's check after the last fault, with zero target exceptions. The remaining eight plans did not satisfy this case's postfault target gate. The campaign continues for HDFS-34/35; later opportunistic observations at this guard remain in that shared checkpoint and do not repeat this base-80 result.

- Source: `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java:396`.
- Function: `BlockPoolSliceStorage.doTransition(StorageDirectory,NamespaceInfo,StartupOption,List,Configuration)`.
- Guard: `getNamespaceID() == nsInfo.getNamespaceID()`.
- Fault model: ordered RPC `IOException`, `SocketTimeoutException`, or `EOFException`, and VERSION-file read exceptions, up to eight faults. All 88 prefix plans were injected in exact order; maximum tested depth was eight.
- Runtime identity: startup episode, DataNode object and slot, configured storage directory, same volume for file I/O, and the actor's exact raw `NN0` RPC endpoint. Missing or ambiguous bindings fail closed.
- Coverage feedback over the 80 effective trials: 51 new production branch IDs, 96 line IDs, 12 method IDs, and 101 JaCoCo probe IDs. The last eight effective trials had no new branch or eligible I/O family, so the conditional 128/10 extension did not activate.
- Measured active time: 5,890.160 seconds for the 88 shared original-JUnit fault attempts plus 79.506 seconds for two healthy seeds, or 5,969.666 seconds attributed to this check. This shared JUnit time is **not additive** across HDFS-22/23/25. Pauses and controller overhead are excluded.

The [V2 source and raw-evidence review](../../hdfs-storage-actor-v2/audit/hdfs22_23_25_base80_review.md) records the exact 80th plan, overlay digest, independent actor/endpoint/target audit, coverage, and original-test interpretation. [Machine-readable result](result.json) has the current counts. Raw V2 traces and JaCoCo artifacts reside on node1 under `.study-repairs/unit-test-pivot/hdfs-storage-actor-v2/evidence/startup-constructor/`.

## Historical coarse-actor run

The earlier campaign's RPC selector normalized thread/port digits, and its target probe lacked DataNode/storage/startup-episode identity. Its 80 trials, 78 strict injections, 57 target-retaining observations, 3,245.356 seconds, and original [trial ledger](trial-ledger.csv) remain under `legacy_coarse_actor` and `trial_results` in `result.json`; they are **excluded** from the V2 counts above. The [identity screen](../../independent-audits/hdfs-hbase-quality-20261007/actor-identity-screen.md) explains the gap.

The 83 completed node0 raw run directories from that historical campaign are preserved in a verified [local and node1 archive](independent/evidence/raw-runs-node0-archive.md); the original directories were removed after the full tar comparison passed. This archive is separate from the actor-qualified V2 evidence on node1.

## Source interpretation

`TestDFSStartupVersions#testVersions` constructs valid and invalid VERSION states and checks expected startup compatibility. This guard compares a stored block-pool field with NameNode `NamespaceInfo`. It is a direct storage-version compatibility condition; the source and test do not establish a multi-hop ad hoc coordination chain at this site. A deliberately incompatible VERSION refusal is expected test behavior. No new target exception was observed in this case's actor-qualified base-budget trials.
