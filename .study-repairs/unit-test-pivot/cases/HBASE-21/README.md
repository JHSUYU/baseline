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

The queue favors new stable I/O sites, new production coverage, and I/O events
nearer the target in the healthy run, including the selected test namespace.
It reduces the score of repeatedly tried or target-losing first sites and skips
fault patterns that have repeatedly removed the target.
The healthy event order is runtime feedback, not a reconstructed causal graph.

The default search budget is 80 **strict, target-retaining** trials with at most
eight ordered faults. Unmatched plans and trials that lose the target are kept
in the ledger but do not consume that effective budget. The loop has a 180
attempt cap and a 9,000-second wall-clock cap measured from the healthy run's
completion. Plans with repeated target loss under the same prefix are skipped.
For multi-fault plans, two observed losses at the same stable final I/O site
also skip further combinations at that site. Hit ordinal and exception kind
remain part of each exact injection selector. System namespace `default` and
`hbase` writes share a target-loss family after independent multi-fault losses.
If only such plans remain, the
campaign stops with an explicit queue reason. The result records
both total attempts and valid target-retaining trials, plus elapsed test time
and wall time. A checkpoint and each trial's log, JaCoCo execution file,
duration, match/application counts, target state, and JUnit outcome are stored
under `work/` on node1. At the 80-trial checkpoint, new production coverage or
a new stable I/O site in the last 16 effective trials can extend the same
campaign to 128 trials and ten faults. The `hbase21-campaign` tmux session runs
the campaign on node1; the `hbase21-result-pull` tmux session atomically copies
its result to node0 for the 102-site checklist.

Short partial JVM runs stopped deliberately while installing queue changes are
listed in `work/operator_preemptions.json`, separate from the completed trial
ledger. Their time is included in wall time; none is counted as a strict or
effective fault trial.

An exception with the healthy target signature is marked expected. A changed
signature or test failure is only a candidate until the HBase source and a
clean replay establish an invariant or interface violation.

`NamespaceStateManager.getNamespaceDescriptor` catches an `IOException` from
the cluster schema and returns `null`. A fault on that read can skip the quota
guard entirely; such a run is recorded as target lost and cannot count toward
this selected check's effective budget, even if the original JUnit later fails.
