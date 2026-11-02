# hbase-adhoc-07: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.hadoop.hbase.snapshot.TestCausynthRestoreSnapshot#restoreAFlushSnapshot`, in the fork tree `/bulk/wt/hbase-checks` (JHSUYU/hbase `graphchecker/hbase-checks`, on top of upstream `1790942bb2`), `hbase-server/src/test/java/org/apache/hadoop/hbase/snapshot/TestCausynthRestoreSnapshot.java` (fork commit `b5d5cc6a20`: the first restore of upstream `TestRestoreFlushSnapshotFromClient#testRestoreSnapshot` alone, under its configuration).
- **Port**: `org.apache.hadoop.hbase.snapshot.TestAdhocWorkload07#run`, in `tree/hbase-server/src/test/java/org/apache/hadoop/hbase/snapshot/TestAdhocWorkload07.java`. Untracked file of the case tree.

## Kept (same scenario)

- Topology: one master, one region server, `HBaseTestingUtil.startMiniCluster(1)`.
- The test's own configuration (that of `TestRestoreFlushSnapshotFromClient`): `hbase.regionserver.msginterval=100`, `hbase.client.pause=250`, 6 client retries, `hbase.master.enabletable.roundrobin=true`, snapshots on, region-server snapshot timeout twice the default.
- The operations in the same order: create a one-region table with family `cf`; put 10 rows; take a FLUSH snapshot; disable; `restoreSnapshot`; enable; `SnapshotTestingUtils.verifyRowCount(..., 10)`.
- JUnit 5, `@Tag(RegionServerTests.TAG)` and `@Tag(MediumTests.TAG)`, as the original.

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| class/method names, table `causynth_restore`, snapshot `causynth_restore_snapshot` | `TestAdhocWorkload07#run`, `adhoc_workload_07`, `adhoc_workload_07_snapshot` | neutral names (B3) |
| javadoc naming GraphChecker, the owner's scope decision and the check (`SnapshotManager#restoreSnapshot`'s table-state guard) | javadoc that names the upstream test it is cut from and lists the operations | no comment names the check or a mechanism |

Nothing else changed: the original has no GraphChecker or Causynth call and compiles against upstream unchanged. The table state the guard reads is changed only by the test's `disableTable`/`enableTable` admin calls.

The workload injects no fault.
