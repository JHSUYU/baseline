# zk-adhoc-b5: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test.

- **GraphChecker original**: `org.apache.zookeeper.server.quorum.CausynthTruncSyncTest#aTruncSyncedFollowerRestarts`, in the fork tree `/bulk/wt/zookeeper-checks`, `zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/CausynthTruncSyncTest.java` (case `zk-bugs-trunc-sync`), with its helper `CausynthQuorumHarness.java` in the same package.
- **Port**: `org.apache.zookeeper.server.quorum.TestAdhocWorkloadB5#run`, in `tree/zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/TestAdhocWorkloadB5.java`. The helper is a static nested class `TestAdhocWorkloadB5.Holds`. Untracked file of the case tree.

## Kept (same scenario)

- Topology: three participants, `QuorumPeerTestBase.MainThread` (upstream), each with `snapCount=100000` and `admin.enableServer=false`; `QuorumPeerTestBase`'s tear-down.
- The helper's mechanics, which the scenario performs, re-implemented line for line with upstream test hooks only (`MainThread#getTestQPMain` -> `TestQPMain#getQuorumPeer` -> `QuorumPeer#makeLeader` -> a `Leader` subclass overriding `propose`, `processAck`, `tryToCommit`, `startForwarding`): track the next create of a path and its zxid; hold that create's ACKs at the leader until the test releases them (then in server id order, each processed before the next); note when a learner's ACK of the create or of UPTODATE arrives; pause the leader's next `startForwarding` for one follower until the test releases it. Every override waits before it calls the protocol's own (synchronized) method; no proposal, commit, packet or zxid is changed.
- The operations in the same order: start the three participants; wait for each to serve (`ClientBase.waitForServerUp`, 30 s); find the leader and a follower F; client on the leader creates `/warm`; hold the ACKs of the next create and create the held node asynchronously; wait until all three participants logged it; restart F with the leader's `startForwarding` for F paused; wait until paused; release the ACKs; wait for the commit; release the pause; wait for the create's reply (rc OK); wait for F's sync; two follow-up creates, each acknowledged by F and asserted to be the next zxid; restart F again; wait for its sync; assert F has all three nodes; shut F down and join it.
- The same waits and bounds: `@Timeout(120)`, helper waits of 300 s, 20 ms polls for the roles.
- The original's assertions (all made natively).

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| `CausynthQuorumHarness` (separate test class) | nested `Holds` class with the same code | neutral name; one file per case |
| fork `QuorumPeerTestBase` (`CausynthNodes.endTest()`, `ensembleStarting()`, `ensembleUp()`) | upstream `QuorumPeerTestBase` | recording-window hooks |
| harness javadoc on GraphChecker replays being slower than recordings; test javadoc naming the JIRA, TRUNC/NEWLEADER, and where the restart throws | javadoc listing the operations only | no comment names the bug, mechanism or expected failure |
| comment "the replay of F's next life applies both, so the second runs the out-of-order guard"; the final shutdown's comment about "a recorded window" | "Two follow-up creates, each the next transaction"; "F's last start ends inside the test" | same |
| node `/ahead`, assertion message "the restarted follower lost a create" | `/held`, "the restarted follower does not have every create" | neutral names |
| class/method names | `TestAdhocWorkloadB5#run` | neutral names |

Nothing in the original is a fault: the holds only order the normal protocol, and F's restarts are clean `MainThread#shutdown`/`start` calls the scenario makes. No helper writes the guard's operands (`committedLog`, `maxCommittedLog`, `allowDiscontinuousProposals`).

The workload injects no fault.
