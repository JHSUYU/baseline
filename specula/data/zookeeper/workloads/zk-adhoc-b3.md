# zk-adhoc-b3: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.zookeeper.server.CausynthContainerReuseTest#keepsTheReplacementOfACleanedContainer`, in the fork tree `/bulk/wt/zookeeper-checks`, `zookeeper-server/src/test/java/org/apache/zookeeper/server/CausynthContainerReuseTest.java` (case `zk-bugs-container-reuse`), with the adapter `org.apache.zookeeper.test.CausynthZkCluster`.
- **Port**: `org.apache.zookeeper.server.TestAdhocWorkloadB3#run`, in `tree/zookeeper-server/src/test/java/org/apache/zookeeper/server/TestAdhocWorkloadB3.java`. Untracked file of the case tree.

## Kept (same scenario)

- Topology: one standalone server, `ClientBase`.
- The test's own container manager, as in the original (and as upstream `CreateContainerTest`): a `ContainerManager` subclass on the server's database and first processor, check interval 100 ms, no pacing between deletions (`maxPerMinute = Integer.MAX_VALUE`); it checks once (it stops itself after its first `checkContainers`) and waits 3000 ms after the scan before it posts each deletion (`postDeleteRequest` override, then `super.postDeleteRequest`).
- The operations in the same order: create a container, create and delete its child; start the manager; sleep 1000 ms; delete the container (tolerating `NoNodeException`); create a persistent node at the same path; `getData` it; wait (up to 30 s) for the manager's check to end; `exists("/")`; stop the manager.
- The same waits: 100 ms, 1000 ms, 3000 ms, 30 s.

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| `CausynthZkCluster.serverWork(server, () -> new OneCheck(...).start())` | `new OneCheck(server)` and `start()` directly | the adapter only attributes the manager's threads to the server node during a recording; natively it just calls the supplier |
| the manager's one-worker `ThreadPoolExecutor` on a `SynchronousQueue`: `postDeleteRequest` hands the deletion to the worker and waits; the worker sleeps 3000 ms and posts | `postDeleteRequest` sleeps 3000 ms on the manager's own thread and posts | the hand-off exists only so GraphChecker can hold the submission where it runs (its javadoc says so); natively it is the same synchronous 3000 ms delay before the post, on another thread |
| fork `ClientBase` recording hooks | upstream `ClientBase` | recording-window and replay hooks |
| class/method names, path `/causynth-container`, javadoc on the cleanup deleting whatever node holds the path and on "the bug's world" | `TestAdhocWorkloadB3#run`, `/adhoc-workload-b3`, javadoc listing the operations and the manager's timing only | neutral names; no comment states the failure or the mechanism |

**Operator note.** The 3000 ms post delay is GraphChecker's own workload choice (case.sh: "the workload widens the cleanup's scan-to-post window so the race ... happens natively"). It is kept because it is part of the original test's own code and timing (same operations, order and waits), and because without it the client's `delete` would always find the container already removed. It does not make the check fail: in a native run the `getData` comes about 2 s before the manager's deletion. It is in the test's own `ContainerManager` subclass, not in server code, and it writes no operand of the guard.

The workload injects no fault.
