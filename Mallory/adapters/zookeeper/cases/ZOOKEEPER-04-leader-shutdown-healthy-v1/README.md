# ZOOKEEPER-04: alternate five-peer healthy probe

The selected guard in `ZooKeeperServer.processConnectRequest` compares the
reconnecting client's `lastZxidSeen` against the peer's applied zxid. The
previous `WatchEventWhenAutoResetTest#testNodeDataChanged` uses client 1 for
the reconnect and client 2 for the write while peer 1 is down. Consequently,
that write cannot raise client 1's `lastZxidSeen`. Its exact `readBool`
IOException pilot retained the guard but did not change either operand.

This package selects the existing five-peer
`QuorumTest#testLeaderShutdown`. The same `zk` client creates two znodes and
issues two batches of `setData`; between batches the test shuts down input on
the leader's forwarding-follower sockets. This is a source-backed opportunity
for a client carrying an updated zxid to reconnect while follower state
changes. The test does **not** prove that such a reconnect occurs. The single
healthy run determines that, using the exact named target and the frozen
agent/site catalog already used for ZOOKEEPER-04.

`healthy.json` is calibration-only, with no automatic promotion to a fault
campaign. Its source/test class, target class, site catalog, and agent hashes
are pinned in `stage-manifest.json`. Run `python3 verify_stage.py` before
dispatching it. The selected JUnit method executes 10,000 asynchronous
writes; its healthy timeout is a ceiling, not an expected duration.

Admit a directed fault pilot only if the healthy trace shows the selected
target on a named peer after a successful write by the **same** reconnecting
client, plus a source-backed state-changing I/O point before that target.
The existing `readBool` door by itself is insufficient. Admit a full campaign
only after a bounded fault at such a point is applied exactly and the affected
actor still reaches the same selected guard. Preserve the healthy trace if
any condition fails.

## Healthy gate result

The node1 run completed in 19.733 s. The original five-peer JUnit passed and
the named target was reached once on `zk5` without throwing. However, the
target event is at timestamp `869982404423549`, after just 140 recorded events:
only 74 doors precede it, all from startup/quorum traffic or the connect path.
The test's two `create` calls and both `setData` batches run after that first
connect. There is no later `TARGET_CHECK` event in the 5,728-event trace.
Consequently this test does not exhibit the required same-client write followed
by reconnect and target check. No fault campaign is admitted from this seed.
The preserved result and events are under
`data/mallory/zk04_leader_shutdown_healthy_node1/ZOOKEEPER-04/`.
