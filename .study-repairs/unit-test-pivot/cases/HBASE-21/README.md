# HBASE-21: namespace quota during snapshot restore

The selected HBase 2.6.6 site is
`NamespaceStateManager.checkAndUpdateNamespaceRegionCount(TableName,int)` at
line 133. It compares `namespaceTotal - existingTableRegions + snapshotRegions`
with the namespace's configured maximum and throws `QuotaExceededException`
when the result is too large. `RestoreSnapshotProcedure.prepareRestore` opens
the snapshot manifest, counts its regions, and asks the master quota manager to
perform this check. The descriptor and namespace count are control-plane
state; the snapshot manifest comes from file-system state.

The unchanged original cluster JUnit is
`TestNamespaceAuditor.testRestoreSnapshotQuotaExceed`. Its `@BeforeAll` starts
a two-master MiniHBaseCluster. The test creates and snapshots a four-region
table, recreates that table with one region, then lowers the namespace maximum
to three and restores the four-region snapshot. It **expects**
`RestoreSnapshotException` caused by `QuotaExceededException` and checks that
the namespace still counts one region. The healthy target exception is part of
the test's intended behavior.

The no-fault JUnit passed in 49.76 seconds. The exact target call saw
`table1`, requested regions 4, namespace total 1, existing table regions 1,
and maximum 3. Its quota guard was evaluated, it threw the expected exception,
and 20 related namespace ZooKeeper I/O operations occurred before the guard.

The case-local ByteBuddy agent in `work/src/HBase21Agent.java` records target
calls and the quota comparison's input state, plus namespace ZooKeeper create,
write, children-read, and data-read operations. Selectors include operation
family, znode path, production call site, and hit ordinal. A fault is marked
applied only when the exact ordered selector matches, and the JUnit reruns in a
fresh mini-cluster. JaCoCo records production method and branch coverage for
six related classes. No GraphChecker prewoven JAR, skeleton, graph, or closure
is used. The source checkout is read only; the executed HBase JAR and test JAR
are original release artifacts.

The default search budget is 80 **strict, target-retaining** trials with at most
eight ordered faults. Unmatched plans and trials that lose the target are kept
in the ledger but do not consume that effective budget. The loop has a 180
attempt safety cap. A checkpoint and each trial's log, JaCoCo execution file,
duration, match/application counts, target state, and JUnit outcome are stored
under `work/` on node1. At the 80-trial checkpoint, new production coverage or
a new stable I/O site in the last 16 effective trials can extend the same
campaign to 128 trials and ten faults. The `hbase21-campaign` tmux session runs
the campaign on node1; the `hbase21-result-pull` tmux session atomically copies
its result to node0 for the 102-site checklist.

An exception with the healthy target signature is marked expected. A changed
signature or test failure is only a candidate until the HBase source and a
clean replay establish an invariant or interface violation.
