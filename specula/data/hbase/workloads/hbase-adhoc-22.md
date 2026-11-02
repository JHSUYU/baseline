# hbase-adhoc-22: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.hadoop.hbase.namespace.TestCausynthTruncatedTableQuota#createWhileATruncatedTableIsDeleted`, in the fork tree `/bulk/wt/hbase-checks` (JHSUYU/hbase `graphchecker/hbase-checks`, on top of upstream `1790942bb2`), `hbase-server/src/test/java/org/apache/hadoop/hbase/namespace/TestCausynthTruncatedTableQuota.java`.
- **Port**: `org.apache.hadoop.hbase.namespace.TestAdhocWorkload22#run`, in `tree/hbase-server/src/test/java/org/apache/hadoop/hbase/namespace/TestAdhocWorkload22.java`. Untracked file of the case tree.

## Kept (same scenario)

- Topology: one master, one region server, `HBaseTestingUtil.startMiniCluster(1)`.
- The test's own configuration: quotas on (`hbase.quota.enabled`); wait (up to 30 s) for the master's quota manager.
- The operations in the same order: create a namespace with `hbase.namespace.quota.maxregions=2`; create its first table with one split key (two regions); disable it; `truncateTable(..., preserveSplits=false)`; disable it again; `deleteTableAsync`; sleep 2000 ms; create a one-region table in the same namespace; wait for the deletion's future.
- The same waits: 30 s for quota initialization, the 2000 ms sleep.
- JUnit 5, `@Tag(MediumTests.TAG)`, as the original and upstream `TestNamespaceAuditor`.

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| class/method names, namespace `causynth_quota` | `TestAdhocWorkload22#run`, namespace `adhoc_workload_22` (tables `truncated` and `created` kept) | neutral names (B3) |
| javadoc naming GraphChecker and the JIRA, and describing the stale region count and the order that would refuse the creation | javadoc listing the operations and the waits | no comment states the failure or the mechanism |

Nothing else changed: the original has no GraphChecker or Causynth call and compiles against upstream unchanged. The namespace quota state is written only by the master's own procedures.

The workload injects no fault.
