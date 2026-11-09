# zk-adhoc-11: A follower that crashes between persisting the synced new-epoch txns and writing currentEpoch can never restart ('current epoch is older than the last zxid') without manual repair.

Severity (reviewer): **outage**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java:1236`, `QuorumPeer.loadDataBase()`, throws `java.io.IOException` when `epochOfZxid > currentEpoch && !currentTmp.exists()`
- Starting test: `org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** In a 3-node mini cluster, a follower that missed a new epoch rejoins and gets a DIFF. It crashes after it has appended and fsynced the new-epoch transactions during NEWLEADER handling, but before it writes currentEpoch. A test-subclass writeLongToFile throws before any byte of currentEpoch(.tmp) is written, which leaves the same disk state as a kill -9 or power loss at that point. The node is then restarted normally.

**Why (root cause in the source):** Learner.syncWithLeader's NEWLEADER branch makes the new-epoch txns durable first (fzk.appendRequest + fzk.getZKDatabase().commit(), Learner.java:798-804) and only afterwards calls self.setCurrentEpoch(newEpoch) (Learner.java:813). These are two separate durable steps, and that order was chosen on purpose for ZOOKEEPER-4643/4785. A crash between them leaves committed epoch-N txns on disk, currentEpoch = N-1 and no currentEpoch.tmp. On restart, QuorumPeer.loadDataBase (QuorumPeer.java:1226-1238) only recovers through the .tmp file from ZOOKEEPER-4269. Otherwise it throws IOException('The current epoch, 1, is older than the last zxid ...'), and QuorumPeer.start fails on every restart. The state is consistent: the txns are ones the leader committed and the follower had not ACKed NEWLEADER. So the check rejects a state the protocol itself produces and permanently removes a voter until an operator edits currentEpoch by hand. The fault is a crash between two separate persistence steps, not inside one atomic step, so the trigger is realistic.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The follower persists its data and its epoch in two separate, non-atomic steps. Since ZOOKEEPER-4643/4785 the txns of the new epoch are made durable first and currentEpoch is written afterwards. A crash, power loss, kill -9 or I/O error between the two steps is normal in a real deployment. It leaves a fully valid on-disk state: committed txns of epoch N and currentEpoch N-1 with no tmp file. The ZOOKEEPER-4269 recovery only covers a crash during the rename of currentEpoch.tmp, not a crash before the tmp file is created. The check treats this reachable state as corruption, so the server refuses to start ('The current epoch, 1, is older than the last zxid ...') on every restart until an operator edits the currentEpoch file by hand or wipes the data dir. One crash at an unlucky moment permanently removes a voter from the ensemble, which lowers fault tolerance and can cost quorum if more nodes hit it. Since the follower had not yet ACKed NEWLEADER, its only state is txns the leader already committed, so it could safely recover by setting currentEpoch to the epoch of its last zxid.

**Execution (agent):** 1. Start a 3-node ensemble (servers 0,1,2). Elect a leader in epoch 1 and write /epoch1. Server 2 has currentEpoch=1. 2. Server 2 goes down. 3. Servers 0 and 1 restart and establish epoch 2 without server 2. Clients write /epoch2a and /epoch2b (zxids 0x2000000xx). 4. Server 2 restarts and rejoins as a follower. The leader syncs it with DIFF: PROPOSAL+COMMIT packets for the epoch-2 txns, then NEWLEADER. In Learner.syncWithLeader's NEWLEADER branch the follower appends the committed epoch-2 txns to its txn log and fsyncs them (fzk.getZKDatabase().commit()). Only after that does it call self.setCurrentEpoch(newEpoch). Server 2 crashes right before that write (simulated: a QuorumPeer subclass's writeLongToFile throws for currentEpoch=2 before anything is written, then the node is shut down). So the currentEpoch file still says 1 and no currentEpoch.tmp exists. 5. Server 2 restarts normally with no fault injection. zkDb.loadDataBase() replays the txn log, so lastProcessedZxid=0x200000006 (epoch 2) while currentEpoch=1 and currentEpoch.tmp is missing. QuorumPeer.loadDataBase throws java.io.IOException at QuorumPeer.java:1236-1237, wrapped as RuntimeException('Unable to run quorum server'), and the server cannot start. The same window exists in SNAP sync: takeSnapshot(syncSnapshot) on NEWLEADER writes a snapshot with an epoch-2 zxid before setCurrentEpoch.

**Stack frame (agent):** at org.apache.zookeeper.server.quorum.QuorumPeer.loadDataBase(QuorumPeer.java:1237)  (java.io.IOException: The current epoch, 1, is older than the last zxid, 8589934598 -- the 'throw new IOException(' statement starting at line 1236; javac attributes the constructor call to the argument line 1237)

## Reproduction

- Test: `org.apache.zookeeper.server.quorum.CurrentEpochCrashAfterSyncTest#testFollowerCrashBetweenSyncPersistAndCurrentEpochWrite`
- Command: `mvn -B -o test -pl zookeeper-server -Dtest='org.apache.zookeeper.server.quorum.CurrentEpochCrashAfterSyncTest#testFollowerCrashBetweenSyncPersistAndCurrentEpochWrite' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/CurrentEpochCrashAfterSyncTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: java.io.IOException: The current epoch, 1, is older than the last zxid, 8589934598`, frame `at org.apache.zookeeper.server.quorum.QuorumPeer.loadDataBase(QuorumPeer.java:1237)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h03m | 1 | 411,218 | 22 | 12,767 | 40,570 | 357,859 | $0.65 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
