# zk-adhoc-b1: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.zookeeper.test.CausynthQuotaRetryTest#raisesARetriedHardQuota`, in the fork tree `/bulk/wt/zookeeper-checks`, `zookeeper-server/src/test/java/org/apache/zookeeper/test/CausynthQuotaRetryTest.java` (case `zk-bugs-quota-init`).
- **Port**: `org.apache.zookeeper.test.TestAdhocWorkloadB1#run`, in `tree/zookeeper-server/src/test/java/org/apache/zookeeper/test/TestAdhocWorkloadB1.java`. `run-case.sh` copies `tree/` into the case's tree, where it is an untracked file.

## Kept (same scenario)

- Topology: one standalone server, `ClientBase` (unchanged upstream test base).
- The test's own configuration: `zookeeper.enforceQuota=true` set before the server starts, cleared after tear-down.
- The operations in the same order: create the path; `SetQuotaCommand.createQuota` with a hard count limit of 2, then of 3, each call made again (up to 3 attempts) when it throws `ConnectionLossException`; create two children; a third child is refused with `QuotaExceededException` (`assertThrows`, as in the original).
- No waits other than `ClientBase`'s own (connect, server up).

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| `ClientBase` of the fork (opens GraphChecker's recording window in `createClient`, registers the server as a node, `CausynthNodes.endTest()` in tear-down, unbounded `waitForServerUp` in a workload) | upstream `ClientBase` | recording-window and replay hooks; inactive in a native run |
| class/method names, path `/causynth-quota`, javadoc describing the quota's two requests and the update branch | `TestAdhocWorkloadB1#run`, `/adhoc-workload-b1`, a javadoc that lists the operations only | neutral names (B3); no comment states the failure or the mechanism |

Nothing else changed: the original contains no Causynth call of its own.

The workload injects no fault.
