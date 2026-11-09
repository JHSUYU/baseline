# MC-2 investigation record

Target: `ZooKeeperServer.processConnectRequest`, `ZooKeeperServer.java:1516`, `CloseRequestException` (`CLIENT_ZXID_AHEAD`), guard `request.getLastZxidSeen() > zkDb.dataTree.lastProcessedZxid`. Tree pinned at eab16599.

## Step 1: code audit

### Mechanism and call chain
1. A quorum-losing leader leaves its main loop. `Leader.java:832-840` checks `syncedAckSet.hasAllQuorums()` only on every second half-tick (`tickSkip`, line 770), so it keeps accepting writes after its last follower has gone, for up to one tick.
2. `Leader.shutdown` (`Leader.java:861`) calls `zk.shutdown()`, which is `shutdown(false)` (`ZooKeeperServer.java:915`, `922`).
3. `shutdown(false)` calls `zkDb.fastForwardDataBase()` (`ZooKeeperServer.java:936`). The comment reads "This will fast-forward the database to the last recorded transaction".
4. `ZKDatabase.fastForwardDataBase` calls `FileTxnSnapLog.fastForwardFromEdits` (`FileTxnSnapLog.java:330`), which applies every txn from `txnLog.read(dt.lastProcessedZxid + 1)`. There is no commit check. Restart replay reaches the same tree contents.
5. `QuorumPeer.java:1536` creates `ReadOnlyZooKeeperServer(logFactory, this, this.zkDb)` over that same database. It starts after a grace of `max(2000, tickTime)` ms if the peer is still LOOKING (`QuorumPeer.java:1544-1548`).
6. A read reply carries `getDataTreeLastProcessedZxid()` (`FinalRequestProcessor.java:166`, `615`). The client stores it at `ClientCnxn.java:958` and sends it in `ConnectRequest` at `ClientCnxn.java:1013`.
7. A server behind that zxid throws at `ZooKeeperServer.java:1516`.
8. A next-epoch follower synced by DIFF does not move `lastProcessedZxid` to the epoch; only SNAP and TRUNC set it (`Learner.java:614`, `628`). The new leader does set it to `epoch<<32` (`Leader.java:1609`), so the leader accepts the same client.

### Reachability
Reachable with `readonlymode.enabled=true` and `canBeReadOnly=true` clients. No caller filters logged-only txns from the read-only tree.

### Safeguards and masks recorded
- The 1516 guard itself works as designed: it stops the client going back in time. It is the symptom here, not the defect.
- TRUNC removes the txn when the old leader rejoins. That repairs the servers, not what a client has already read.
- Any new-epoch write moves followers past the client's zxid, ending the refusal.
- The new-epoch leader accepts the client, so a client whose list reaches it reconnects.

### Trigger scenario
See the Reproduction section below. Both counterexample orders were realized.

### Mapping to the counterexamples
`hunt_S2_uncommitted_ro_bfs.out` to `testHuntCounterexampleSuspendedReadOnlyPeerRefuses`:

| Trace step | Real execution |
|---|---|
| 5: sid 1 read-only | workload prefix: `qu.shutdown(2)`, client connects read-only |
| 6-12: quorum {2,3} forms, sid 1 stays out | `setSuspended(true)` on sid 1, `qu.start(2)`, `qu.start(3)`; sid 1 is FOLLOWING with `isro=ro`, as `targetInfo.role=FOLLOWING, srv=RO` |
| 13-14: write, follower stops before logging | async creates at the leader while its follower stops |
| 15: leader abandons, fast-forwards | `Not sufficient followers synced`, `N txns loaded` |
| 16, 18-20: read-only server, client reads | `isro=ro`, `RO READ` lines |
| 17, 21: old leader elected, read-only server stops | `qu.start(follower)`, client connection closes |
| 22: client connects to sid 1, target fires | `seen zxid 0x20000005d our last zxid is 0x0`, matching `sz=0` in `targetInfo` |

The real run has leader sid 2 where the trace has sid 3; the roles are the same.

`route_S2_next_epoch.out` to `testDirtyReadThenNextEpochFollowerRefuses`: same outcome (read of the uncommitted txn at the old leader's read-only server, refusal by a next-epoch FOLLOWING server with `role=FOLLOWING, srv=RW`). Differences from the trace:
- The client moves because the old leader stops, not through an `isro` seek.
- The trace has the read-only server at the old leader start while the next-epoch quorum is alive (steps 18-19). From reading `FastLeaderElection`, a LOOKING old leader that can reach that quorum learns its votes and follows it before the 2 s grace ends, so the read-only server would not start. This was not run. That order would need the old leader cut off from election traffic, and the trace's `part` count is 0. The test therefore stops the old leader instead.
- The test uses more stops than the trace's bound of 1: both followers and the old leader. The fault type is the same.

The hit at 1516 does not depend on these differences: the exception, branch, role, and the zxid relation are the same.

## Step 2: developer knowledge (evidence only)
Searches ran after the verdict was settled, per adhoc Shared Rule 2.

- Comment at `ZooKeeperServer.java:936`: "This will fast-forward the database to the last recorded transaction". "Recorded", not committed.
- Javadoc at `ZKDatabase.java:300`: "Fast-forward the database adding transactions from the committed log into memory." The raw txn log is what is replayed (CR-3 in the dedup note).
- `zookeeperAdmin.md:1915` (experimental feature): "ROM clients can still read values from the ZK service, but will be unable to write values and see changes from other clients". `ZooKeeper.java:591-596`: read requests are allowed while write requests are not. Neither mentions data that was never committed.
- Tests: `ReadOnlyModeTest` reads only values that were committed before read-only mode. No test asserts that logged-only txns are visible.
- History: fast-forward on shutdown came with `bbfd0169` ZOOKEEPER-2678 (retain the database across election to shorten sync).

## Step 3: known status
Novelty: **NEW**. Queries, all run after the verdict:

Web search:
- `ZooKeeper read-only mode server serves uncommitted transaction fastForwardDataBase dirty read ZOOKEEPER JIRA`
- `"ReadOnlyZooKeeperServer" uncommitted data visible after leader loses quorum issue apache zookeeper`
- `ZooKeeper "as it has seen zxid" "our last zxid is" client must try another server read-only uncommitted txn truncated JIRA`

JIRA REST (project=ZOOKEEPER):
- `text ~ "read-only uncommitted" OR text ~ "readonly uncommitted" OR text ~ "fastForwardDataBase" OR text ~ "CLIENT_ZXID_AHEAD"`
- `(text ~ "read-only" OR text ~ "readonly" OR summary ~ "r/o") AND (text ~ "uncommitted" OR text ~ "not committed" OR text ~ "dirty")`
- `text ~ "ReadOnlyZooKeeperServer"`
- `text ~ "fastForward"`

GitHub search API, apache/zookeeper PRs (`gh` is not installed, so via curl):
- `read-only uncommitted` (one hit, #2141, unrelated)
- `fastForward` (0)
- merged since 2026-08-01 with `read-only` (4 hits, all unrelated) and with `fastForward` (0)
- `CLIENT_ZXID_AHEAD` (#1525, #1518: disconnect-reason text only)
- `readonly fastForward` was rate-limited and not retried under that exact query; the `fastForward` retry covers it.

Local history: `git log -i --grep` for read-only, readonly, fastForward, fast-forward, uncommitted, dirty read, lastProcessedZxid, CLIENT_ZXID_AHEAD, client must try another server.

Nearest reports, none the same mechanism at the same site:
- ZOOKEEPER-4681 (open): uncommitted requests executed on 3.5.8 under dropped messages and restarts; its description does not mention read-only mode.
- ZOOKEEPER-2845 (fixed): retained database causes replica inconsistency after election, not client reads through read-only mode.
- ZOOKEEPER-1462 (fixed): same refusal text, caused by an uninitialized read-only database (`our last zxid is 0x0`).
- ZOOKEEPER-3713 (open): read-only server exposes an uninitialized database during snapshot load.
- ZOOKEEPER-3870, ZOOKEEPER-3178 (open): read-only txn creation and response order.
- ZOOKEEPER-3911 (closed): DIFF sync of an uncommitted log; leader path, not read-only.

Pre-filter: not applicable (MC-sourced with a real counterexample).

## Phase 2 reproduction
Test: `repro/test_bugMC-2_ReadOnlyDirtyReadMC2Test.java`, driver `repro/test_bugMC-2_dirty_read.sh`, per-run logs `repro/MC-2-logs/`, summary `repro/MC-2.log`.

Ladder: Level 0 triggered `testDirtyReadThenNextEpochFollowerRefuses` and `testRestartReplayServesLoggedTxn` (client API and QuorumUtil start/stop only). Level 1 for `testHuntCounterexampleSuspendedReadOnlyPeerRefuses`, which adds the workload's own `setSuspended`. Levels 2 and 3 were not needed: no state injection, no production source change.

| Test | Factory | Result |
|---|---|---|
| next-epoch follower | Netty | 3/3 after the port fix (the last run's logs are kept); 1 earlier run failed with `Address already in use` from other workers' JVMs |
| next-epoch follower | NIO (default) | 3/3 |
| hunt counterexample | Netty | 1 of 4 reached sid 1 (one run before the test's timeout was shortened, logs replaced) |
| hunt counterexample | NIO | 1 of 3 reached sid 1 |
| restart replay | NIO | 1/1 (no refusal is expected in this test) |
| unmodified workload (control) | NIO | passes, 0 refusals |

Why hunt runs miss: `ClientCnxn.pingRwServer` calls `hostProvider.next(0)` (`ClientCnxn.java:1351`), so the seek rotates the client's list. With two hosts, the next host after the read-only server stops is either sid 1 or the old leader. Each non-triggering run reached the old leader, which accepted it. The dirty read itself happened in every run.

Stack frames come from Netty runs because `NettyServerCnxn.java:561-562` logs the exception. `NIOServerCnxn.java:380` swallows it silently, so NIO runs show the `ZooKeeperServer@1515` log line and the JVM exception log (type and message) instead.
