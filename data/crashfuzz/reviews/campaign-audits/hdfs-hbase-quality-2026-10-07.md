# HDFS/HBase completion audit — 2026-10-07

This is a read-only evidence review of the 50 HDFS/HBase rows that were marked
`quality_complete` in the 104-check table. No JUnit was rerun for this audit.
The 16 rows below are returned to pending review. Their measured attempts,
fault applications, target visits, coverage and elapsed time remain historical
observations; **those counters are not validated actor-aware effective counts**
until the indicated repair is audited. Existing `bug_mark` values are unchanged.

An actor-aware fault must bind the selected I/O operation to the runtime
process/role that performed it, and the post-fault target visit to its selected
object, file, block or procedure. A path, callsite, normalized thread name and
global ordinal alone do not distinguish concurrent DataNodes or Masters.

## Actor identity recheck: 13 cases

| Case | Existing evidence and gap | Raw evidence that can be retained | Required next step |
| --- | --- | --- | --- |
| HDFS-01 | Original `TestPread#testPreadDFS` uses three DataNodes ([README](../cases/HDFS-01/README.md)). [`Hdfs01Probe.io`](../cases/HDFS-01/probe/src/Hdfs01Probe.java) lines 70–86 keys `BlockReaderRemote.read` by `main` thread/site/ordinal, without reader peer, block or stream. All 98 post-fault plans in [`campaign-state.json`](../cases/HDFS-01/evidence/campaign-state.json) contain such reads. | Original trace/JUnit/JaCoCo and the 128 attempted sequences remain valid as call-order observations. The saved trace has no peer field to establish which DN served a read. | Add reader→remote DN UUID/address and block identity to the I/O hook and match; calibrate on the unchanged three-DN JUnit, then rerun plans whose actor cannot be proven. |
| HDFS-07 | [`Hdfs07Probe.ipcResponse`](../cases/HDFS-07/independent/src/Hdfs07Probe.java) lines 85–89 normalizes all RPC ports and digits; the `main` selector cannot distinguish three JournalNodes. [`campaign-state.json`](../cases/HDFS-07/independent/evidence/campaign-state.json) has 43 post-fault plans containing `main` RPC and 10 file-only plans. | File I/O selectors include concrete `journalnode-N` and can be audited directly. Raw RPC `thread` sometimes retains a port, but `main` events lack a peer; preserve all trials as historical evidence. | Bind `Client.Connection` remote endpoint to the runtime JN registration before injection; recount actor-proven trials and rerun unresolved RPC plans. |
| HDFS-09 | Same normalization in [`Hdfs09Probe`](../cases/HDFS-09/independent/src/Hdfs09Probe.java) lines 78–79. The [`checkpoint`](../cases/HDFS-09/independent/evidence/campaign-state.json) has 91 post-fault plans containing `main` RPC and 22 file-only. | Concrete JournalNode file selectors can be retained after raw audit. | Apply endpoint-aware QJM RPC hook and rerun actor-unproven plans. |
| HDFS-10 | Same normalization in [`Hdfs10Probe`](../cases/HDFS-10/independent/src/Hdfs10Probe.java) lines 77–78. The [`checkpoint`](../cases/HDFS-10/independent/evidence/campaign-state.json) has 54 post-fault plans containing `main` RPC and 12 file-only. | Concrete JournalNode file selectors can be retained after raw audit. | Apply endpoint-aware QJM RPC hook and rerun actor-unproven plans. |
| HDFS-16 | Original JUnit has one NN and two DNs ([case README](../cases/HDFS-16/independent-coverage-io/README.md), lines 17–27). [`Probe.io`](../cases/HDFS-16/independent-coverage-io/system-test/Probe.java) lines 138–150 keys RPCs by API/global ordinal only. In the [`checkpoint`](../cases/HDFS-16/independent-coverage-io/campaign/checkpoint.json), 22 of 40 strict same-context post-fault plans contain `registerDatanode`, with no source DN identity. | Client→sole-NN RPC and NN edit-log plans can be separately audited. Healthy raw trace shows `registerDatanode` on both `main` and BP threads, but has no verified DN slot binding. | Add source DN UUID/BP actor registration to DN RPC events; recount and rerun unresolved plans. |
| HDFS-31 | Original `TestDiskError` starts a second DN before the selected `getBPOSForBlock` visit ([README](../cases/HDFS-31/README.md)). [`Hdfs31Probe`](../cases/HDFS-31/independent/src/Hdfs31Probe.java) lines 36–45 normalizes BP thread address/digits and keys RPC by ordinal. | [`raw-runs.tar.zst`](../cases/HDFS-31/independent/evidence/raw-runs.tar.zst) contains actual thread ports and target DataNode/BP object IDs; they may prove individual trials if a source-DN mapping is independently recoverable. Current 41 post-fault visits are not all actor-proven. | Join RPC Connection peer/BPService actor to DN UUID and target DataNode at runtime; rerun cases without a complete raw mapping. |
| HDFS-32 | Original `TestDeleteBlockPool` has two NNs/two DNs ([README](../cases/HDFS-32/README.md)). [`Hdfs32Probe`](../cases/HDFS-32/independent/src/Hdfs32Probe.java) lines 33–45 folds distinct BP heartbeat threads/ports into one ordinal stream. | [`raw-runs.tar.zst`](../cases/HDFS-32/independent/evidence/raw-runs.tar.zst) retains thread endpoints and target object IDs, but the current selector does not bind its 47 post-fault visits to a DN/NN actor. | Add DN role/BPService identity plus remote NN endpoint to selector and target receipt; rerun unresolved plans. |
| HDFS-39 | Original `TestFileAppend#testMultipleAppends` has one NN/four DNs ([README](../cases/HDFS-39/README.md), lines 11–12). [`Probe.io`](../cases/HDFS-39/independent-coverage-io/system-test/Probe.java) lines 120–135 labels every DN `blockReceivedAndDeleted` RPC with destination `nn0`, without sender DN. In the [`checkpoint`](../cases/HDFS-39/independent-coverage-io/campaign/checkpoint.json), 109 of 128 effective-labelled plans contain that DN report fault. | The 19 effective-labelled plans without DN reports and all target file/block/coverage observations can be separately audited. | Add sender DN UUID/role as in HDFS-40 actor V2; replay source-unbound report plans on unchanged JUnit. |
| HDFS-43 | Upstream `TestFileTruncate#testTruncateTwiceTogether` uses three DNs (`TestFileTruncate.java` lines 86, 109–111, 236). [`HdfsStorageProbe`](../cases/HDFS-43/independent/src/HdfsStorageProbe.java) line 130 normalizes BP thread identity. In the [main checkpoint](../cases/HDFS-43/independent/evidence/campaign-state.json), 43 of 49 post-fault plans contain that BP RPC; the equal-branch supplement uses the same overlay. | Target file/branch/expected exception evidence and six main-phase non-BP plans can be audited independently. Raw thread may enable partial mapping. | Register BP actor→DN UUID/slot and bind RPC selector; audit or rerun both phases' ambiguous plans. |
| HDFS-48 | Upstream `TestRenameWithSnapshots` uses three DNs (`TestRenameWithSnapshots.java` lines 77, 105). [`Hdfs48Probe`](../cases/HDFS-48/independent/src/Hdfs48Probe.java) lines 43–52 removes BP identity and port; 128 post-fault plans contain 166 normalized BP RPC faults in the [`checkpoint`](../cases/HDFS-48/independent/evidence/campaign-state.json). | Selected inode/parent identity and original trace/coverage are retained; raw thread names may support only a subset of DN mappings. | Add sender DN/BP actor identity to RPC plan and target trace, then rerun unresolved plans. |
| HBASE-08 | Original [`TestNamespaceAuditor#testTableOperations`](../cases/HBASE-08/README.md) lines 8–17 has two Masters. [`HBase08Agent.io`](../cases/HBASE-08/work/src/HBase08Agent.java) lines 43–65 selects namespace ZK I/O by family/path/callsite/global ordinal with no Master or manager identity. | Logs prove znode and chronological match, not which Master executed it or the later check. | Bind each `ZKNamespaceManager`/watcher to active Master `ServerName` and epoch; apply the same identity to target events, then rerun. |
| HBASE-21 | Original [`TestNamespaceAuditor.testRestoreSnapshotQuotaExceed`](../cases/HBASE-21/README.md) lines 12–24 has two Masters. [`HBase21Agent.io`](../cases/HBASE-21/work/src/HBase21Agent.java) lines 64–86 omits Master identity. Raw `r001.log` in [`node1-work-raw.tar.zst`](../cases/HBASE-21/node1-work-raw.tar.zst) has repeated same-path `writeNamespace` calls and generic procedure threads; source Master cannot be proven. | Preserve the expected quota exception and table/region counts, plus raw timing, as historical observations. | Add manager/Master actor key to I/O and quota target, then rerun ambiguous plans. |
| HBASE-22 | Original [`TestNamespaceAuditor#testTableOperations`](../cases/HBASE-22/README.md) lines 13–20 has two Masters. [`HBase22Agent.io`](../cases/HBASE-22/work/src/HBase22Agent.java) lines 55–77 similarly omits Master identity. | Original ZK path/plan, expected quota exception and JaCoCo traces remain historical evidence. | Add watcher/manager→Master actor registration and target binding; rerun. |

## Budget recheck: 3 cases

| Case | Evidence | Required next step |
| --- | --- | --- |
| HDFS-28 | The shared original `TestBlockRecovery2#testRecoveryTimeout` main phase had 128 attempts, 63 strict, only **18** same-recovery-owner post-fault HDFS-28 visits ([final audit](../cases/hdfs_recovery_shared/phase-v4/final-audit.json)). Its [`campaign-state.json`](../cases/hdfs_recovery_shared/phase-v4/campaign-state.json) still has **789 queued plans**; the [README](../cases/hdfs_recovery_shared/README.md) lines 181–190 documents priority migration without replaying finished trials. | Resume the same actor-aware checkpoint from its next uncompleted plan. Reach 80 effective or document a defensible queue/execution limit; do not count the 128 attempts as 80 effective. |
| HDFS-29 | Same shared campaign: **39** same-owner post-fault visits, 789 pending plans. | Resume shared checkpoint and recount this target separately. |
| HDFS-30 | Main phase had **39** same-owner post-fault visits; HA original `TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization` supplement added only **2** in 24 attempts and retained **60 queued plans** ([README](../cases/hdfs_recovery_shared/README.md), lines 237–253; [HA checkpoint](../cases/hdfs_recovery_shared/ha-control-v1/ha-campaign-state.json)). | Resume original main and/or HA checkpoint without repeating completed attempts; maintain separate source/workload and coverage accounting. |

## Reporting qualifications outside the 16 status changes

- [HDFS-54 README](../cases/HDFS-54/README.md) lines 8–17 still describes a
  `3/80` snapshot, while `result.json` and `original-junit/README.md` record
  terminal `80/80`. The known HDFS-17897 reproduction remains the separate
  adapted differential; an all-nine-DN synthetic failure in the original JUnit
  is the expected exhausted-location path.
- [HDFS-55 README](../cases/HDFS-55/README.md) lines 10–25 correctly separates
  44 unchanged-original-JUnit site-level attempts from two adapted one-node
  known-bug differential runs. Its aggregate table counters must not be
  presented as direct original-JUnit reproduction of HDFS-17899.
- HDFS-50 used the earlier 48-trial/four-fault preset, with 22 target-retaining
  trials and 155 queued plans. Its [result](../cases/HDFS-50/result.json)
  documents no late coverage/I/O novelty and classifies the same-name guard
  as a weak local candidate. This is a budget comparability qualification for
  the uniform effective-80 rule, separate from actor-identity defects.

This audit did not find an equivalent blocker in the other 34 reviewed
HDFS/HBase rows. That is an evidence review, not a claim that their workloads
exhaust all fault sequences or that no future bug exists.
