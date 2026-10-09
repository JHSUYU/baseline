# ZOOKEEPER-06 precise ACKEPOCH retry door

The v1 source overlay only inherited the generic quorum archive door, which
also fires on unrelated packets. The v2 isolated overlay adds
`zookeeper.quorum.ackepoch.write` at `Learner.registerWithLeader` directly
before `writePacket(ackNewEpoch, true)`. The hook requires an `ACKEPOCH`
packet and the identical `QuorumPeer` Java thread. It runs inside that
peer's bounded FOLLOWING region.

Source order is relevant: after receiving `LEADERINFO`, the follower may
execute `self.setAcceptedEpoch(newEpoch)` before constructing and sending
`ackNewEpoch`. An `IOException` at the new door prevents that ACKEPOCH send,
yet the accepted epoch can already be persisted. `Follower.followLeader`
catches the error, closes the socket and returns; `QuorumPeer.run` then
leaves the old FOLLOWING region and can retry. This creates a plausible
state change for a subsequent handshake without asserting that the selected
`Leader.waitForEpochAck` comparison will change.

The source-only node0 v2 overlay is
`/users/ZhenyuLi/.mallory-worktrees/zookeeper-ackepoch-retry-door-node0`.
Its receipt is
`data/mallory/admissions/ZOOKEEPER-06-ackepoch-retry-door-node0-source-v2.json`.
Because node0 is close to its disk reserve, the same 15 patched files were
transferred by SHA to the isolated node1 overlay
`/users/ZhenyuLi/.mallory-worktrees/zookeeper-ackepoch-retry-door-node1`.
Node1 Maven `test-compile` completed without executing JUnit; the compiled
overlay receipt is `zookeeper-3.8.7-ackepoch-retry-door-node1-overlay.json`.
The next admitted step is one healthy run of the unchanged three-peer
`QuorumRestartTest#testRollingRestart`, with the exact compiled
`Leader.waitForEpochAck` guard/throw and loaded class hash pinned. A bounded
pilot must select this new door and verify the
fault → same-peer retry token submit/claim → new physical ACKEPOCH SEND/RECV
→ target path. Target checks on unrelated leader handlers do not qualify.
