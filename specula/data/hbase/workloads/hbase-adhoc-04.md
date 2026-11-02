# hbase-adhoc-04: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.hadoop.hbase.quotas.TestCausynthQuotaEnableAfterAdvance#enableAfterTheSnapshotAdvanced`, in the fork tree `/bulk/wt/hbase-checks` (JHSUYU/hbase `graphchecker/hbase-checks`, on top of upstream `1790942bb2`), `hbase-server/src/test/java/org/apache/hadoop/hbase/quotas/TestCausynthQuotaEnableAfterAdvance.java`.
- **Port**: `org.apache.hadoop.hbase.quotas.TestAdhocWorkload04#run`, in `tree/hbase-server/src/test/java/org/apache/hadoop/hbase/quotas/TestAdhocWorkload04.java`. `run-case.sh` copies `tree/` into the case's tree, where it is an untracked file.

## Kept (same scenario)

- Topology: one master, one region server, `HBaseTestingUtil.startMiniCluster(1)` (upstream; the fork's `HBaseTestingUtil` hooks are active only in GraphChecker's automatic mode).
- The test's own configuration: quotas on (`hbase.quota.enabled`); the master's quota observer chore delay and period 3 600 000 ms (its own runs come after the test); the observer's client `hbase.client.retries.number=0`.
- The operations in the same order: wait (up to 30 s) for the master's quota manager; create a one-family table; disable it; build a `QuotaObserverChore` on its own connection with a `TableSpaceQuotaSnapshotNotifier`, the master's quota manager and the master as stopper; `initializeSnapshotStores(emptyMap)`; set the table's snapshot to DISABLE violation (2048/1024); run `updateTableQuota` twice to a not-in-violation snapshot (2048/4096), logging and continuing on `IOException`; flush the table.
- JUnit 5, `@Tag(MediumTests.TAG)`, as the original and as the neighbouring upstream quota tests.

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| class/method names, table `causynth_quota_disable` | `TestAdhocWorkload04#run`, table `adhoc_workload_04` | neutral names (B3) |
| javadoc naming GraphChecker, the JIRA, the check line and the failure it would lead to | javadoc listing the set-up and the operations only | no comment states the failure or the mechanism |

Nothing else changed: the original has no GraphChecker or Causynth call and compiles against upstream unchanged. The test sets the observer's own in-memory snapshot (`setTableQuotaSnapshot`), as the original does; it writes no operand of the check's guard (the table's state in `TableStateManager`), which only `disableTable` and the observer's enable change.

The workload injects no fault.
