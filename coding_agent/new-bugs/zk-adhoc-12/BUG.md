# zk-adhoc-12: A transient failure persisting acceptedEpoch in a LearnerHandler is swallowed: the leader still establishes the epoch and writes currentEpoch > acceptedEpoch, so the server can never restart ("accepted epoch is less than the current epoch").

Severity (reviewer): **outage**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java:1256`, `QuorumPeer.loadDataBase()`, throws `java.io.IOException` when `acceptedEpoch < currentEpoch`
- Starting test: `org.apache.zookeeper.server.quorum.QuorumPeerMainTest#testQuorum`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** A transient disk write failure (an IOException from writeLongToFile at the I/O boundary) for the acceptedEpoch file, in the LearnerHandler thread that completes the leader's epoch quorum. Later the leader server is restarted.

**Why (root cause in the source):** Leader.getEpochToPropose sets waitingForNewEpoch=false before persisting with self.setAcceptedEpoch(epoch), and calls notifyAll only afterwards (Leader.java:1481-1484). When the write throws in a LearnerHandler, only that handler dies. The leader thread's wait times out, but because waitingForNewEpoch is false it does not throw and returns the epoch (Leader.java:1492-1500). Leadership goes on and setCurrentEpoch(1) succeeds, so the disk holds acceptedEpoch=0 and currentEpoch=1. On the next start QuorumPeer.loadDataBase throws at QuorumPeer.java:1256-1259, and the server cannot start without an operator editing the epoch files. A single recoverable I/O fault thus leaves the server's durable state inconsistent and permanently unable to start.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Zab needs acceptedEpoch >= currentEpoch on every server, and the leader is supposed to establish an epoch only after it has durably accepted it. Leader.getEpochToPropose() breaks this: it publishes the decision (waitingForNewEpoch=false) before persisting acceptedEpoch, and does not undo the decision or notify the waiting leader thread when the persist fails in a LearnerHandler thread. The leader thread then treats a failed write as success and records currentEpoch=1 while acceptedEpoch stays 0. ZOOKEEPER-2307 fixed the same write failure on the follower side (Learner.registerWithLeader aborts, see EpochWriteFailureTest), but on the leader side the failure is swallowed by whichever LearnerHandler thread happens to complete the quorum. In a real deployment a single transient disk error (EIO, a briefly full disk, an fsync failure) during leader election leaves the leader with inconsistent epoch files. Nothing goes wrong while it keeps running, but the next restart of that server fails permanently with 'Unable to run quorum server'. An operator then has to edit or delete the acceptedEpoch file by hand, and until then the ensemble runs with one server fewer (with 3 servers, one more failure makes it unavailable). The state the check rejects was produced by ZooKeeper's own epoch protocol from a single recoverable fault, not by invalid user input.

**Execution (agent):** 1) Ensemble of 3 participants (sid 1,2,3), fresh data dirs, tickTime=1000, initLimit=10. Server 3 (highest sid) wins FLE and enters Leader.lead(); its leader thread calls getEpochToPropose(3, 0), adds itself to connectingFollowers and waits (no quorum yet). 2) A follower connects; its LearnerHandler thread calls getEpochToPropose(sid, 0), which completes the quorum: it sets waitingForNewEpoch=false and then calls self.setAcceptedEpoch(1). On server 3 this disk write fails with a transient IOException (fault injected by overriding QuorumPeer.writeLongToFile in a test subclass of QuorumPeer, failing exactly one acceptedEpoch write, the one made in a LearnerHandler thread; this models EIO/ENOSPC/fsync failure that clears again). The exception kills only that LearnerHandler (socket closed, 'Unexpected exception in LearnerHandler'); acceptedEpoch on disk and in memory stays 0, and notifyAll() is never called. 3) The leader thread's wait in getEpochToPropose times out after initLimit*tickTime, but because waitingForNewEpoch is already false it does not throw; it returns epoch=1 as if the epoch had been accepted. 4) The other follower's handler (and the first follower once it re-joins) gets epoch 1 immediately, sends LEADERINFO, receives ACKEPOCH; waitForEpochAck reaches a quorum and the leader thread runs self.setCurrentEpoch(1), which now succeeds. The leader finishes sync (followers 'Set the current epoch to 1') and the ensemble serves clients. On server 3's disk: acceptedEpoch=0, currentEpoch=1. 5) Server 3 is restarted (crash, rolling restart, or a later leader change followed by a restart). QuorumPeer.start() -> loadDataBase() reads currentEpoch=1, acceptedEpoch=0 and throws java.io.IOException 'The accepted epoch, 0 is less than the current epoch, 1' at QuorumPeer.java:1256, wrapped in RuntimeException 'Unable to run quorum server'. Server 3 cannot start again.

**Stack frame (agent):** at org.apache.zookeeper.server.quorum.QuorumPeer.loadDataBase(QuorumPeer.java:1259)  -- this is the `throw new IOException("The accepted epoch, " ...)` statement that starts at line 1256 (guarded by `if (acceptedEpoch < currentEpoch)`); javac attributes the IOException constructor call to the last line of its multi-line argument expression (1259). Message: java.io.IOException: The accepted epoch, 0 is less than the current epoch, 1

## Reproduction

- Test: `org.apache.zookeeper.server.quorum.LeaderAcceptedEpochWriteFailureTest#testLeaderRestartFailsAfterTransientAcceptedEpochWriteFailure`
- Command: `source /bulk/codingagent/cases/zk-adhoc-12/agent/env.sh && mvn -B -o test -pl zookeeper-server -Dtest='org.apache.zookeeper.server.quorum.LeaderAcceptedEpochWriteFailureTest#testLeaderRestartFailsAfterTransientAcceptedEpochWriteFailure' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false -DredirectTestOutputToFile=false`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/LeaderAcceptedEpochWriteFailureTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.io.IOException: The accepted epoch, 0 is less than the current epoch, 1`, frame `at org.apache.zookeeper.server.quorum.QuorumPeer.loadDataBase(QuorumPeer.java:1259)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h07m | 1 | 1,036,133 | 40 | 21,980 | 70,541 | 943,572 | $1.19 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
