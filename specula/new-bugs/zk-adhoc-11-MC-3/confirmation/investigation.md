# MC-3 investigation record

Target: QuorumPeer.loadDataBase, throw at QuorumPeer.java:1236, guard `epochOfZxid > currentEpoch && !currentTmp.exists()`.
Source pinned at eab16599. Tree used for the verdict: `git archive HEAD` export (no Specula instrumentation), plus the instrumented worktree for traces.
Line numbers below are the instrumented worktree's for Learner.java and the shared ones for QuorumPeer.java:1236.

## Step 1: code audit
- Stop: `QuorumPeer.shutdown` sets `running = false` first (QuorumPeer.java:1682), then x509Util.close, then follower.shutdown -> Learner.shutdown -> closeSocket (Learner.java:919).
- Callers of QuorumPeer.shutdown in production code: only QuorumPeerMain.close (QuorumPeerMain.java:256, javadoc "not a public API"), reached from ZooKeeperServerEmbeddedImpl.close. No other caller in the quorum package. Tests reach it through QuorumBase.shutdown.
- Loop: `while (self.isRunning())` (Learner.java:651). False condition ends the loop normally, with no check after it.
- Post-loop: writePacket(ack) (:827), zk.startup, updateElectionVote, fzk.logRequest for every packetsNotLogged entry (:841).
- setCurrentEpoch runs only under NEWLEADER (:812) or UPTODATE with isPreZAB1_0, so neither runs on this path.
- Durability: SyncRequestProcessor appends and flushes; its shutdown joins and flushes.
- Replay: FileTxnSnapLog.restore fast-forwards from the log over snapshot.0, so lastProcessedZxid takes the logged epoch.
- Guard: QuorumPeer.java:1233-1238; currentEpoch 0, epochOfZxid 1, no tmp -> throw.
- Why a proposal precedes NEWLEADER: LearnerHandler calls syncFollower (startForwarding) before serializing the snapshot and queues NEWLEADER after (LearnerHandler.java:556-604), so proposals made during the transfer queue ahead of NEWLEADER.
- Safeguards considered: socket close racing the ACK (writePacket throws if the socket closed first, then nothing is logged; observed as the benign outcome in some trials); zk.shutdown no-op before startup; currentEpoch.tmp fallback (no tmp exists on this path because no epoch write ever started).

## Step 2: developer knowledge (searched only after the reproduction verdict, per Shared Rule 2)
Comments at Learner.java:810-811 cite ZOOKEEPER-4643/4785 and order the epoch write after txn persistence, inside the NEWLEADER branch only. Nothing near the loop or post-loop code discusses a stop before NEWLEADER. QuorumPeer.java:1229 comment and CurrentEpochWriteFailureTest (ZOOKEEPER-4269) treat the tmp-rename failure as the case to tolerate. No test covers this order.

## Step 3: known status; queries run, all after the verdict settled
Web search:
- `ZooKeeper "The current epoch" "is older than the last zxid" follower shutdown during sync before NEWLEADER`
- `ZOOKEEPER Learner syncWithLeader while self.isRunning loop exit shutdown logs proposals without setCurrentEpoch JIRA` (issues.apache.org, github.com, lists.apache.org)
- `apache zookeeper pull request 2026 Learner syncWithLeader shutdown running false current epoch older than last zxid fix` (extended)
JIRA REST, project=ZOOKEEPER:
- text ~ "older than the last zxid" (8 hits)
- text ~ syncWithLeader AND shutdown AND currentEpoch (6 hits)
- text ~ currentEpoch AND updated >= -365d (3 hits)
- text ~ syncWithLeader AND updated >= -365d (3 hits)
- text ~ isRunning AND NEWLEADER (6 hits)
GitHub search API, repo:apache/zookeeper (issues and PRs, including closed):
- "older than the last zxid" (2); syncWithLeader shutdown (5); currentEpoch shutdown sync is:pr (2); syncWithLeader is:pr (20, top 12 read)
Git history at the pinned tree: `git log -i --grep` on older than / currentEpoch / current epoch; last 6 commits on Learner.java; `git log -S` on the loop guard.
`gh` is not installed; the REST APIs were used instead. No revision other than base_commit was checked out.

Read and compared:
- ZOOKEEPER-1653 (Closed/Fixed) and ZOOKEEPER-2354: same exception; restart between takeSnapshot and setCurrentEpoch inside NEWLEADER. Different mechanism; the fix is the tmp fallback.
- ZOOKEEPER-4269 (Fixed): tmp rename failure. Different.
- ZOOKEEPER-2653 (Open, 0 comments): same exception after "shutting zk down", embedded caller, no root cause stated. Same symptom, no mechanism reported, so not a report of this defect; it cannot be excluded that it shares this cause.
- ZOOKEEPER-1549 (Open): dirty snapshot and DIFF. Different.
- ZOOKEEPER-4712 (Closed/Fixed): syncProcessor shutdown path. Different.
- ZOOKEEPER-5094 / PR #2459 (Open): interrupted TRUNC leaves memory ahead of the log, IllegalStateException on replay. Same area, different mechanism, exception and site.
- PR #2382 (Open): ZXID width change, surfaced by search only because it touches these files.
Result: nothing reports a stop ending the sync loop before NEWLEADER followed by post-loop logging. Novelty NEW.

## Not done
`specula findings lookup` was not run: this worker's instructions forbid reading other findings.
