# zk-adhoc-b6: An ObserverMaster created after a follower's sync drops COMMITs for proposals the follower received during the sync. Observers attached in that window get a gapped txn stream, apply later txns without the committed one, and their CommitProcessor dies.

Severity (reviewer): **outage**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/ZKDatabase.java:341`, `ZKDatabase.addCommittedProposal(Request)`, throws `java.lang.IllegalStateException` when `!committedLog.isEmpty() && request.zxid > maxCommittedLog && !allowDiscontinuousProposals && request.zxid != maxCommittedLog + 1 && ZxidUtils.getEpochFromZxid(request.zxid) <= ZxidUtils.getEpochFromZxid(maxCommittedLog)`
- Starting test: `org.apache.zookeeper.server.quorum.TestAdhocWorkloadB6#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** 3 participants with observerMasterPort, and 1 observer that syncs through follower F's ObserverMaster. The observer and F are stopped. Create /held is proposed, and the leader's processing of its ACKs is delayed (a slow quorum). F restarts and receives the /held PROPOSAL during sync. The observer restarts and syncs through F's new ObserverMaster. Then /held commits, and a further create /after follows.

**Why (root cause in the source):** Follower.followLeader creates a fresh ObserverMaster only after syncWithLeader returns (Follower.java:107-116). Proposals that F received during the sync are therefore never recorded in om.proposedPkts. When their COMMIT arrives, ObserverMaster.proposalCommitted -> removeProposedPacket finds no packet, returns null and silently drops it (ObserverMaster.java:359-363, 407-411). The observer synced against F's committedLog up to /warm and got an empty DIFF. Because committedPkts was empty, startForwarding's 'too far behind' guard was skipped (ObserverMaster.java:293-330). The next INFORM (/after) reaches the observer with a hole. ZooKeeperServer.processTxn applies it to the DataTree and then calls addCommittedProposal (ZooKeeperServer.java:1888), which throws at ZKDatabase.java:341. The observer's CommitProcessor (a critical thread) dies, the server is set to ERROR, and the observer's replica now has /after without the committed /held. The triggers are restarts and an ACK delay, which force an interleaving that happens under normal write load. The fault is in the Follower/ObserverMaster coordination, not in any input.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The observer was sent a committed-transaction stream with a hole: transaction 0x100000003 (/held) was committed by the quorum and applied by F but never forwarded by F's ObserverMaster. The cause is in the ad hoc coordination between Follower and ObserverMaster: the ObserverMaster is created only after the follower's sync, and it forwards a COMMIT only if it saw the matching PROPOSAL. Proposals that arrive during the sync but commit after it (any write in flight while a follower rejoins) are therefore silently dropped for every observer that attaches in that window. Nothing invalid comes from the user. This is a plain restart of a follower and an observer under write load with a slightly slow quorum, which happens in real deployments. Without the check, the observer would have skipped /held and served reads that permanently diverge from the quorum (the node is missing, and later txns apply on top of the wrong state). With the check, the observer's CommitProcessor dies with an unrecoverable error and the observer stops serving clients until it is restarted and resynced.

**Execution (agent):** Cluster: 3 participants (each with observerMasterPort) + 1 observer O whose learner master is follower F's ObserverMaster (same setup as TestAdhocWorkloadB6). (1) Client creates /warm (zxid 0x100000002); all servers including O apply it. (2) O and F crash (shutdown). (3) Client creates /held (zxid 0x100000003); the leader L and the other follower log it but their ACKs are delayed (held by the test's Leader.processAck override, i.e. a slow quorum), so it stays uncommitted. (4) F restarts and syncs with L; L's LearnerHandler sends F the outstanding /held PROPOSAL as part of the sync (Learner.syncWithLeader), F logs and ACKs it. Only after syncWithLeader returns does Follower.followLeader create a fresh ObserverMaster, so /held is never added to om.proposedPkts. (5) O restarts and syncs through F's new ObserverMaster: F's last committed zxid is /warm, so O gets an empty DIFF, startForwarding finds committedPkts empty and adds O to activeObservers; O is up to date at 0x100000002. (6) The ACKs are delivered; /held commits; L sends COMMIT(0x100000003) to F. F applies it, but ObserverMaster.proposalCommitted -> removeProposedPacket finds no proposal ("ignore missing proposal packet", debug log) and forwards nothing to O. (7) Client creates /after (0x100000004); F receives PROPOSAL (now recorded by om) and COMMIT, and its ObserverMaster sends INFORM(0x100000004) to O. (8) O's CommitProcessor -> FinalRequestProcessor -> ZooKeeperServer.processTxn -> ZKDatabase.addCommittedProposal sees 0x100000004 after maxCommittedLog 0x100000002 in the same epoch and throws IllegalStateException('Committed proposal cached out of order: 0x100000004 is not the next proposal of 0x100000002') at ZKDatabase.java:341; the CommitProcessor (a critical thread) dies and O stops serving. Reproduced 3/3 runs.

**Stack frame (agent):** at org.apache.zookeeper.server.ZKDatabase.addCommittedProposal(ZKDatabase.java:341)

## Reproduction

- Test: `org.apache.zookeeper.server.quorum.TestAdhocWorkloadB6Repro#observerMissesCommitOfProposalReceivedDuringFollowerSync`
- Command: `source /bulk/codingagent/cases/zk-adhoc-b6/agent/env.sh && mvn -B -o test -pl zookeeper-server -Dtest='org.apache.zookeeper.server.quorum.TestAdhocWorkloadB6Repro#observerMissesCommitOfProposalReceivedDuringFollowerSync' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false -DtrimStackTrace=false`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/TestAdhocWorkloadB6Repro.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.lang.IllegalStateException: Committed proposal cached out of order: 0x100000004 is not the next proposal of 0x100000002`, frame `at org.apache.zookeeper.server.ZKDatabase.addCommittedProposal(ZKDatabase.java:341)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h04m | 1 | 764,901 | 36 | 15,871 | 50,804 | 698,190 | $0.86 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
