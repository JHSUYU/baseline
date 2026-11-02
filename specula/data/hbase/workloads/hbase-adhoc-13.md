# hbase-adhoc-13: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.hadoop.hbase.master.assignment.TestMergeTableRegionsProcedure#testMergeTheMergedRegionAfterItsParentsAreCollected`, in the fork tree `/bulk/wt/hbase-checks` (JHSUYU/hbase `graphchecker/hbase-checks`, on top of upstream `1790942bb2`), `hbase-server/src/test/java/org/apache/hadoop/hbase/master/assignment/TestMergeTableRegionsProcedure.java` (fork commits `6fddb3317a`, `618e0dfe19`). The class is upstream, but this method was **added by the fork**: it does not exist at `1790942bb2`. The inventory listed it as `upstream`; it is now `ported` (inventory row and `targets/hbase-adhoc-13.yaml` updated to the port, `gc_workload` keeps the original).
- **Port**: `org.apache.hadoop.hbase.master.assignment.TestAdhocWorkload13#run`, in `tree/hbase-server/src/test/java/org/apache/hadoop/hbase/master/assignment/TestAdhocWorkload13.java`. A new class, because a method cannot be added to the tracked `TestMergeTableRegionsProcedure.java` as an untracked file.

## Kept (same scenario)

- Topology: one master, one region server, `HBaseTestingUtil.startMiniCluster(1)`.
- `TestMergeTableRegionsProcedure`'s configuration, line for line: `hbase.assignment.maximum.attempts=3`, `hbase.master.maximum.ping.server.attempts=3`, `hbase.master.ping.server.retry.sleep.interval=1`, one master procedure thread, region coprocessor `RegionServerHostingReplicaSlowOpenCoprocessor` (upstream, same package).
- Its per-test set-up and tear-down: reset the executor's kill flag, nonce group and nonce, balancer off, catalog janitor chore disabled; after the test, delete every table.
- The operations in the same order: create a table named after the test method with family `info` and split keys `b`..`e` (five regions); merge the first two regions with a `MergeTableRegionsProcedure` (forcible) and wait for it, asserting it did not fail; disable and enable the table; run `CatalogJanitor#scan()` on the test thread; sleep 3000 ms; merge the merged region with the third region and wait, asserting it did not fail; assert the table has `regions - 2` regions.
- JUnit 5, `@Tag(MasterTests.TAG)` and `@Tag(LargeTests.TAG)`, as `TestMergeTableRegionsProcedure`.

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| a method inside upstream `TestMergeTableRegionsProcedure` | the method, the class's configuration, `@BeforeAll`/`@AfterAll`, `@BeforeEach`/`@AfterEach` and `getMasterProcedureExecutor()` copied into `TestAdhocWorkload13` | the method does not exist upstream; an untracked new class is how a case tree gets it |
| the class's other tests, its procedure-metrics fields and their reads in `@BeforeEach` | dropped | other tests; the metrics reads only fill fields this test never uses |
| method name `testMergeTheMergedRegionAfterItsParentsAreCollected` (also the table name, via `TestInfo`) | `run` (table `run`) | neutral names (B3) |
| javadoc naming GraphChecker and the check, and stating that only time orders the janitor's removal before the second merge's check | class javadoc listing the operations and the 3 s wait | no comment states the mechanism |

The fork's production change for this case (`RegionStateStore` keeping a map of merge-qualifier rows in automatic mode, `6fddb3317a`) is GraphChecker tracking and is not ported; the port runs on upstream `RegionStateStore`.

The workload injects no fault.
