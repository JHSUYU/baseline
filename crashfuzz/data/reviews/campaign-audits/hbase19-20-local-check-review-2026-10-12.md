# HBASE-19/20 check and workload review (2026-10-12)

This review concerns the two original-102 sites in HBase 2.6.6
`ModifyTableProcedure.preflightChecks` at source lines 135 and 139. It is a
source and healthy-trace review, not a terminal fuzz result.

The HBase source at commit `d5f63f523c065f963992ea4e74db268d17816631`
(`hbase-server/src/main/java/org/apache/hadoop/hbase/master/procedure/ModifyTableProcedure.java`,
SHA-256 `186e34a72dcffdbe853abaa0068ca0af6e899f44e28005710301688bbbdaf7b3`)
shows two local descriptor validations under `!reopenRegions`:

- HBASE-19 compares the column-family counts of `unmodifiedTableDescriptor`
  and `modifiedTableDescriptor`.
- HBASE-20 calls `isCoprocModified`, which compares the coprocessor descriptor
  collections stored in those same two procedure fields.

Neither condition reads a remote node or shared coordination state. These are
local API restrictions for table modifications that will not reopen regions,
so the two sites are likely false positives for the ad hoc coordination
classification even though an earlier descriptor acquisition can involve RPC.

The campaign workload creates a table, reads its descriptor, changes one
unrelated table property, and submits `ModifyTableProcedure` with
`reopenRegions=false` (`crashfuzz/cases/HBASE-19/workload/TestModifyNoReopenCrashFuzz.java`).
The healthy HBASE-19 trace reaches the selected method four times (event
sequences 532, 673, 690, 699). Its first selected I/O is master startup's
`HMaster.tryMigrateMetaLocationsFromZooKeeper -> ResultScanner.next` at
sequence 98. The first two strictly applied trial faults occur in the
`becomeActiveMaster` actor before the workload reaches the target, and both
lose the target. The checkpoint snapshot after 39 completed trials contains
22 `lost_target` and 17 `unmatched` outcomes, with no valid post-fault target
trial. The live campaign continues under its configured budget; these counts
are a snapshot, not its final outcome.

Raw evidence: node1
`/users/ZhenyuLi/static-rerun/results/HBASE-19/healthy/runtime_trace.jsonl`
(SHA-256 `ef67395fe3707ba08020aece6051ac50ad32e8773e88612ee897858341cbce87`)
and
`/users/ZhenyuLi/static-rerun/results/HBASE-19/campaign-no-snappy-v1/HBASE-19/state.json`
(39-trial snapshot SHA-256
`590e05a3bc64339fd58d94e18b63465cb46b73032d77b73f9de59a78c0d0aef2`).
