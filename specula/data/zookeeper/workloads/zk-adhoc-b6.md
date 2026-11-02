# zk-adhoc-b6: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.zookeeper.server.quorum.CausynthObserverMasterSyncTest#aProposalPendingAtTheObserverMastersStart`, in the fork tree `/bulk/wt/zookeeper-checks`, `zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/CausynthObserverMasterSyncTest.java` (case `zk-bugs-observer-master`), with its helper `CausynthQuorumHarness.java`.
- **Port**: `org.apache.zookeeper.server.quorum.TestAdhocWorkloadB6#run`, in `tree/zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/TestAdhocWorkloadB6.java`. The helper is a static nested class `TestAdhocWorkloadB6.Holds` (the same code as b5's). Untracked file of the case tree.

## Kept (same scenario)

- Topology: three participants (helper `MainThread`s, each with its own `observerMasterPort`, `snapCount=100000`, `admin.enableServer=false`) and one observer (plain upstream `MainThread`) whose `observerMasterPort` is follower F's, so it syncs through F's ObserverMaster.
- The helper's mechanics, re-implemented line for line with upstream test hooks (see zk-adhoc-b5.md): hold one create's ACKs at the leader and release them in server id order; note ACKs of a create and of UPTODATE. (The `startForwarding` pause is in the shared helper but this test does not use it, as in the original.)
- The operations in the same order: start the participants; wait for each to serve; find the leader and a follower with an ObserverMaster; start the observer and wait for it to serve; client on the leader creates `/warm`; wait for the observer to apply it; stop the observer, then F; hold the ACKs of the next create and create it asynchronously; wait for the ACKs of the leader and of the other follower; assert it is the next zxid; start F; wait for F's sync and for F's ACK of the create; release the ACKs; wait for the reply (rc OK); start the observer; wait until it is connected to F's ObserverMaster port and serving; create `/after` and assert the next zxid; wait until the observer has both nodes and its `maxCommittedLog` is `/after`'s zxid; assert it still serves; shut the observer down, join it and the learner handlers that served it; assert those handlers ended.
- The same waits and bounds: `@Timeout(120)`, helper waits of 300 s, 20 ms polls.
- The original's assertions (all made natively).

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| `CausynthQuorumHarness` | nested `Holds` class with the same code | neutral name; one file per case |
| fork `QuorumPeerTestBase` (`CausynthNodes` recording hooks) | upstream `QuorumPeerTestBase` | recording-window hooks |
| test javadoc naming the JIRA/PR, describing the ObserverMaster never queueing the proposal, the empty DIFF, the missing INFORM, and where the observer throws | javadoc listing the operations only | no comment names the bug, mechanism or expected failure |
| the `finally` block's comment about "a recorded window" | "The observer and the handler serving it at F end inside the test" | same |
| node `/pending`, method `awaitObserverAfterPending`, variable `pending` | `/held`, `awaitObserverApplies`, `heldZxid` | neutral names |
| class/method names | `TestAdhocWorkloadB6#run` | neutral names |

No helper writes the guard's operands, and the observer's and F's restarts are the scenario's clean `shutdown`/`start` calls.

The workload injects no fault.
