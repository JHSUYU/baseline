# zk-adhoc-04: After a leader election with no new write, the leader advertises zxid newEpoch<<32 while DIFF-synced followers keep the old last zxid, so clients that talked to the new leader are refused by every in-sync follower (CLIENT_ZXID_AHEAD) until the next write.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java:1516`, `ZooKeeperServer.processConnectRequest(ServerCnxn, ConnectRequest)`, throws `org.apache.zookeeper.server.ServerCnxn.CloseRequestException` when `request.getLastZxidSeen() > zkDb.dataTree.lastProcessedZxid   (DisconnectReason.CLIENT_ZXID_AHEAD)`
- Starting test: `org.apache.zookeeper.test.ReadOnlyModeTest#testSeekForRwServer`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** 3-node ensemble. The leader crashes, the other two elect a new leader in epoch 2, and the old leader restarts and rejoins through an empty DIFF. With no write in the new epoch, a client reads from the new leader and then moves to the followers (updateServerList; any loss of the client->leader connection has the same effect).

**Why (root cause in the source):** Leader.startZkServer sets dataTree.lastProcessedZxid to zk.getZxid() = newEpoch<<32 (Leader.java:1609), and that value reaches clients in reply headers. Followers synced by DIFF never adopt it: Learner.syncWithLeader sets lastProcessedZxid only for SNAP/TRUNC (Learner.java:614, 628). Fully in-sync followers therefore refuse the client at ZooKeeperServer.java:1504-1516 (CLIENT_ZXID_AHEAD) for a zxid that is not the zxid of any transaction. The client is refused again and again until some write happens. In a read-mostly ensemble, a client that cannot reach the leader cannot reconnect at all and may lose its session even though a healthy quorum is up.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The check is meant to stop a client from going back in time by connecting to a server that has not yet applied a transaction the client already saw. Here there is no such transaction. 0x200000000 is not the zxid of any txn. The new leader writes the epoch's base zxid into dataTree.lastProcessedZxid when it starts, and that value leaks to clients through reply headers. The followers have exactly the same committed state (the same last txn 0x100000001) but never adopt the new epoch's base zxid. So the two kinds of server report inconsistent 'last zxid' values for identical state, and the ad hoc client/server coordination of lastZxidSeen breaks. After every leader election, until the next write, every in-sync follower refuses every client that has talked to the new leader. In a read-mostly or idle ensemble the client cannot reconnect at all if the leader is unreachable from it, is overloaded, or hits its connection limit, or if the client's server list is rebalanced away from the leader. Its session can then expire while a healthy quorum is available. Clients see connection loss, and possibly session expiry, for no real reason.

**Execution (agent):** 3-server ensemble (servers 0,1,2, localSessionsEnabled=true as in ReadOnlyModeTest). (1) A client creates /a in epoch 1 (zxid 0x100000001), so all servers have it. (2) The leader crashes (node crash). The two survivors elect a new leader in epoch 2. The old leader restarts and rejoins as a follower via DIFF. No transaction happens in epoch 2. At the end of Leader.startZkServer (Leader.java:1609) the new leader runs zkDb.setlastProcessedZxid(zk.getZxid()) = 0x200000000. Both followers keep dataTree.lastProcessedZxid = 0x100000001: an empty DIFF does not touch it, and only SNAP/TRUNC set it. The test logs these values. The followers are fully in sync: fresh clients read /a from each of them. (3) A client connected to the new leader does getData(/a). FinalRequestProcessor puts the leader's lastProcessedZxid 0x200000000 in the reply header, so ClientCnxn stores lastZxid = 0x200000000. (4) The client's connection moves to the followers. In the test this is ZooKeeper.updateServerList(followers), the client rebalancing API. In a deployment it is any loss of the client->leader connection: network glitch, leader unreachable from the client, client-side rebalancing. (5) Each follower's processConnectRequest sees lastZxidSeen 0x200000000 > lastProcessedZxid 0x100000001 and throws CloseRequestException(CLIENT_ZXID_AHEAD) at ZooKeeperServer.java:1516 ('Refusing session ... as it has seen zxid 0x200000000 our last zxid is 0x100000001 client must try another server'). The client cycles between the followers and is refused about 11 times in 20 s, staying CONNECTING. The test wraps Leader/FollowerZooKeeperServer.processConnectRequest only to log and rethrow the exception, so its stack trace appears in the output and in the test failure.

**Stack frame (agent):** at org.apache.zookeeper.server.ZooKeeperServer.processConnectRequest(ZooKeeperServer.java:1516)

## Reproduction

- Test: `org.apache.zookeeper.server.quorum.ZxidAheadAfterElectionTest#testClientRefusedByInSyncFollowersAfterElection`
- Command: `mvn -B -o test -pl zookeeper-server -Dtest='org.apache.zookeeper.server.quorum.ZxidAheadAfterElectionTest#testClientRefusedByInSyncFollowersAfterElection' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/ZxidAheadAfterElectionTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.zookeeper.server.ServerCnxn$CloseRequestException: Refusing session(0x10045fc59f50000) request for client /127.0.0.1:37442 as it has seen zxid 0x200000000 our last zxid is 0x100000001 client must try another server`, frame `at org.apache.zookeeper.server.ZooKeeperServer.processConnectRequest(ZooKeeperServer.java:1516)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h14m | 1 | 3,016,388 | 84 | 45,712 | 106,800 | 2,863,792 | $2.34 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
