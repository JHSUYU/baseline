# zk-adhoc-b5: A TRUNC-mode sync interrupted before NEWLEADER leaves a committed txn applied only in memory. The follower rejoins with it, so its on-disk log has a permanent hole and the server fails to load its database on the next restart.

Severity (reviewer): **data-loss**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/ZKDatabase.java:341`, `ZKDatabase.addCommittedProposal(Request)`, throws `java.lang.IllegalStateException` when `!committedLog.isEmpty() && request.zxid > maxCommittedLog && !allowDiscontinuousProposals && request.zxid != maxCommittedLog + 1 && ZxidUtils.getEpochFromZxid(request.zxid) <= ZxidUtils.getEpochFromZxid(maxCommittedLog)`
- Starting test: `org.apache.zookeeper.server.quorum.TestAdhocWorkloadB5#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** 3-node mini cluster. The leader's processing of the ACKs for create H is delayed. Follower F restarts and gets TRUNC(H-1). The leader's startForwarding for F is delayed while H commits, so F's sync stream is TRUNC, PROPOSAL(H), COMMIT(H), NEWLEADER. F's connection to the leader is lost at the NEWLEADER read (injected SocketException at the Learner.readPacket I/O boundary). F rejoins in the same JVM, logs H+1 and H+2, and later restarts.

**Why (root cause in the source):** In TRUNC/SNAP sync, snapshotNeeded = true, so writeToTxnLog is false. COMMITs that arrive before NEWLEADER are only applied in memory (zk.processTxn, Learner.java:683-692), and the NEWLEADER snapshot (Learner.java:759-760) is what persists them. When the sync aborts before NEWLEADER is processed, Learner.shutdown calls zk.shutdown(syncMode == SNAP) (Learner.java:924). TRUNC is not SNAP, so the in-memory DB is kept (ZooKeeperServer.java:928-946; fastForwardDataBase cannot drop H). F then registers with lastZxid H taken from memory (QuorumPeer.getLastLoggedZxid, QuorumPeer.java:1390), gets an empty DIFF, and appends H+1 onward to a new log file. Its durable history now permanently lacks the committed txn H. On restart, replay goes from H-1 straight to H+1, and ZKDatabase.addCommittedProposal throws at ZKDatabase.java:341, so F cannot start. Every step is allowed: a restart, delays the real scheduler or network can produce (LearnerHandler startForwarding is called after the TRUNC is queued, LearnerHandler.java:864/925), and a lost connection during sync. The check is correctly catching corruption that the sync protocol produced.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Every input is legitimate: a follower restart, a leader-side handler that runs slowly, and a lost follower-leader connection during sync. The check fails because the follower's sync protocol is wrong, not because of an invalid request. In a TRUNC (or SNAP) sync, COMMITs received before NEWLEADER are applied only in memory. Their persistence depends entirely on the NEWLEADER snapshot. If the sync is interrupted before that snapshot, the follower keeps the committed txn H in its in-memory DataTree. It then re-registers with lastZxid=H taken from memory, the leader accepts this with an empty DIFF, and the follower's durable history now has a permanent hole at H while later txns H+1.. are appended after it. Consequences: the follower's on-disk state silently diverges from the committed history; it acked and served H, but H is lost from its disk. On the next restart it cannot load its database (IllegalStateException in addCommittedProposal), so the server is down until an operator wipes its data. If the check were absent or relaxed, it would come up without /held, a committed znode, and could serve or propagate an inconsistent state. If it became leader, a txnlog-based DIFF from it would also skip H.

**Execution (agent):** 3 participants (leader L, follower F=sid 1, follower G). 1) The client's session (0x100000001) and /warm (0x100000002) commit; then the client creates /held (H=0x100000003). L holds all ACKs of H until every participant has logged H, so H is proposed and logged everywhere but not committed. 2) F crashes and restarts (process restart): it loads its log (lastZxid H) and connects to L. L's LearnerHandler.syncFollower sees peerLastZxid H > maxCommittedLog H-1 and queues TRUNC(H-1), then calls startForwarding while holding the logLock read lock; startForwarding is delayed (test pause, i.e. the LearnerHandler thread is slow / not scheduled). 3) The held ACKs are processed, H commits on L (tryToCommit puts H into toBeApplied). 4) startForwarding proceeds and queues PROPOSAL(H), COMMIT(H) from toBeApplied, then the handler queues NEWLEADER. 5) F handles TRUNC: truncates its log to H-1 and reloads (sync mode TRUNC, snapshotNeeded=true, writeToTxnLog=false). PROPOSAL(H)+COMMIT(H) arrive before NEWLEADER, so F applies H directly to its in-memory DataTree via zk.processTxn and does NOT write H to its txn log; the snapshot at NEWLEADER is what is supposed to persist it. 6) F's connection to the leader is lost right when NEWLEADER is read (injected SocketException in Learner.readPacket = network failure / leader socket reset), so the NEWLEADER snapshot is never taken. Learner.shutdown does zk.shutdown(fullyShutDown=false) since the sync mode is TRUNC, not SNAP, so the in-memory DB, with lastProcessedZxid=H, is kept. 7) F goes back to LOOKING, rejoins the same leader in the same JVM and reports lastZxid H (from memory). L sees lastProcessedZxid == peerLastZxid and sends an empty DIFF, so F is considered in sync. On disk F has log.100000001 = [1, 2] (H truncated) and only snapshot.0. 8) Client creates /after (H+1) and /after2 (H+2). F logs them to a new file log.100000004. 9) F restarts again: restore loads snapshot.0, replays 0x100000001 and 0x100000002, then the next log file starts at 0x100000004. The commitProposalPlaybackListener calls addCommittedProposal(0x100000004) with maxCommittedLog 0x100000002, both in epoch 1, and ZKDatabase.java:341 throws IllegalStateException('Committed proposal cached out of order: 0x100000004 is not the next proposal of 0x100000002'). QuorumPeer.start fails and F cannot start.

**Stack frame (agent):** at org.apache.zookeeper.server.ZKDatabase.addCommittedProposal(ZKDatabase.java:341)

## Reproduction

- Test: `org.apache.zookeeper.server.quorum.TestAdhocB5TruncSyncCommitLost#run`
- Command: `mvn -B -o test -pl zookeeper-server -Dtest='org.apache.zookeeper.server.quorum.TestAdhocB5TruncSyncCommitLost#run' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/TestAdhocB5TruncSyncCommitLost.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.lang.IllegalStateException: Committed proposal cached out of order: 0x100000004 is not the next proposal of 0x100000002`, frame `at org.apache.zookeeper.server.ZKDatabase.addCommittedProposal(ZKDatabase.java:341)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h07m | 1 | 1,495,675 | 52 | 30,043 | 78,765 | 1,386,815 | $1.51 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
