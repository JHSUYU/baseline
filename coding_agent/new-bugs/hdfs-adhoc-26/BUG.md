# hdfs-adhoc-26: A DataNode that missed a rollback silently discards its unfinalized previous snapshot on the next upgrade and keeps the rolled-back state, so a later rollback fails and its block pool cannot start.

Severity (reviewer): **outage**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java:621`, `BlockPoolSliceStorage.doRollback(StorageDirectory, NamespaceInfo)`, throws `org.apache.hadoop.hdfs.server.common.InconsistentFSStateException` when `!(prevInfo.getLayoutVersion() >= DataNodeLayoutVersion.getCurrentLayoutVersion() && prevInfo.getCTime() <= nsInfo.getCTime())`
- Starting test: `org.apache.hadoop.hdfs.TestDFSRollback#testRollback`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Two upgrade/rollback cycles in a mini cluster. DN1 is down during the first rollback and rejoins (regular start) during the second upgrade. The second upgrade is then rolled back with all DNs started with -rollback.

**Why (root cause in the source):** DN1 still holds previous=C0, current=C1 (an upgrade the NN rolled back). Started against the rolled-back NN (C0) it would be refused by the 'newer than the namespace state' branch (BlockPoolSliceStorage.java:419-424). But NN upgrade #2 assigns cTime C2 > C1, so doTransition calls doUpgrade (L414-417). doUpgrade silently deletes the existing unfinalized <bp>/previous (L477-480), the only copy of the C0 state, and preserves the rolled-back C1 state as previous. The NN itself refuses to upgrade while an unfinalized previous exists; the DN does not. At the next rollback, doRollback (L621-626) finds previous cTime C1 > NN cTime C0 and throws InconsistentFSStateException on every volume, so DN1's block pool cannot start. The check is right to reject C1. The bug is the upstream upgrade step that produced that state after an ordinary node outage. Consequence: the DN is unusable for that block pool until an operator wipes its storage, and its pre-upgrade-#1 snapshot is already gone.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The upgrade/rollback coordination between the NN and the DNs is supposed to keep a DN's <bp>/previous snapshot in step with the NN's previous checkpoint, so that a later rollback always finds DN previous cTime <= NN cTime. Here a single DN crash during a rollback (a normal operational event) breaks that invariant. When the DN rejoins during the next upgrade, BlockPoolSliceStorage.doUpgrade deletes an unfinalized previous snapshot without checking it against the NN, and preserves a state (cTime C1) that the NN already rolled back. The NN never accepts that state again, so it can never be a valid rollback target. Neither the NN nor the DN detects the mismatch at upgrade time (the DN should have refused to upgrade, or rolled back first). The problem only surfaces at the next rollback. Consequences in a real deployment: (a) the DN cannot start its block pool after the rollback, so its replicas are unavailable and the admin has to intervene manually (format or delete the DN's block pool storage, losing its replicas). (b) Worse, the pre-upgrade-#1 snapshot (C0) on that DN, which matches the namespace being rolled back to, has already been deleted, so this DN's data from the state the cluster rolled back to is permanently lost. Blocks that were only on such DNs may be lost or under-replicated.

**Execution (agent):** MiniDFSCluster with 1 NameNode and 2 DataNodes (DN0, DN1), replication 2. (0) Format and write a file; the NN cTime is C0. (1) Upgrade #1: restart the NN with -upgrade (new cTime C1 = now()) and both DNs normally. Each DN's BlockPoolSliceStorage.doUpgrade turns <bp>/current (C0) into <bp>/previous and writes a new current with cTime C1. Write more data. Shut down. (2) The admin rolls the cluster back (NameNode -rollback restores NN cTime C0), but DN1 is down/crashed at that point, so only DN0 is started with -rollback. DN1 keeps previous=C0, current=C1 (an unfinalized upgrade that was rolled back elsewhere). (3) Later the admin starts upgrade #2: NN -upgrade (cTime C2 = now() > C1), and both DNs start normally (DN1 is back). In DN1, doTransition sees current cTime C1 < C2 and calls doUpgrade, which silently deletes the existing unfinalized <bp>/previous (C0, the only copy of the pre-upgrade-#1 state), renames current (C1) to previous and writes current with C2. (4) The admin rolls back upgrade #2: NN -rollback (cTime back to C0), and both DNs are started with -rollback. DN0 rolls back fine (its previous has cTime C0). In DN1, BlockPoolSliceStorage.doRollback reads previous VERSION cTime C1 > NN cTime C0 and throws InconsistentFSStateException 'Cannot rollback to a newer state. Datanode previous state: LV = -57 CTime = C1 is newer than the namespace state: LV = -57 CTime = C0' on both of DN1's volumes. Then 'All specified directories have failed to load' and DN1's block pool service exits.

**Stack frame (agent):** at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.doRollback(BlockPoolSliceStorage.java:626)  (this is the multi-line 'throw new InconsistentFSStateException(...)' of the check whose 'if' is at line 621; javac attributes the constructor call to the last line, 626, of the statement)

## Reproduction

- Test: `org.apache.hadoop.hdfs.TestDFSRollbackAfterMissedRollback#testRollbackAfterDataNodeMissedPreviousRollback`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.TestDFSRollbackAfterMissedRollback#testRollbackAfterDataNodeMissedPreviousRollback' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestDFSRollbackAfterMissedRollback.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.hdfs.server.common.InconsistentFSStateException: Directory /bulk/codingagent/cases/hdfs-adhoc-26/validate/hadoop/hadoop-hdfs-project/hadoop-hdfs/target/test/data/dfs/data/data3/current/BP-517259671-172.18.0.3-1794074481631 is in an inconsistent state: Cannot rollback to a newer state.`, frame `at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.doRollback(BlockPoolSliceStorage.java:626)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h07m | 1 | 599,662 | 28 | 16,604 | 50,086 | 532,944 | $0.84 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
