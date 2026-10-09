# ZOOKEEPER-07 FOLLOWING continuation

The existing three-peer `QuorumRestartTest#testRollingRestart` reaches the
nonthrowing `Learner.registerWithLeader(int)` guard at source line 518. The
fault sites are quorum archive I/O calls executed while a peer is in the
`FOLLOWING` branch of `QuorumPeer.run`.

`followLeader()` can return through its own I/O handling after an injected
exception. The v2 hook submitted a task token only in `QuorumPeer`'s catch
block; six real fault trials emitted no such token, despite a later
`FOLLOWING` attempt and target check. Their raw traces remain separate.

The versioned v3 source overlay submits a token in the `FOLLOWING` finally
block, after follower shutdown and state update, if the peer remains running.
The next `FOLLOWING` attempt claims that token only when the exact
`QuorumPeer` object, Java thread object, server ID, and registered lifecycle
epoch still agree. The source hook enters a bounded `zookeeper.peer.following`
region on each attempt. It never joins actor-wide `unscoped` roots.

The strict sidecar accepts a postfault path only when a SHA-verified trial
trace contains, in order, an old scoped region entry, an applied fault in
that region, task submit, old exit, new scoped region entry, the unique
observed task claim, a target region entry whose parent is the new region,
and the exact target check. All events must share the named node, epoch, and
thread. The token contains the source peer identity and Java thread ID; the
source hook verifies object identity before observing it.

In the first v3 fault trial, the concrete event sequence is `267 → 327 →
341 → 342 → 343 → 344 → 368 → 389` for those eight steps on `zk1` epoch 1. This
shows an observed fault-to-target continuation, not a target exception. The
full pilot and any later full campaign require their own terminal audits.
