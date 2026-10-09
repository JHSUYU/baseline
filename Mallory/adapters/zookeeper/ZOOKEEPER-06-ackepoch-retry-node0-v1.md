# ZOOKEEPER-06 ACKEPOCH retry admission

The existing three-peer `QuorumRestartTest#testRollingRestart` starts each
member and restarts it in turn. The selected check is
`Leader.waitForEpochAck(long, StateSummary)` at the compiled
`@1475:branch:3` guard; the selected `IOException` is `@1479:throw:1`.
`LearnerHandler.run` reads a physical `ACKEPOCH` packet, constructs the
`StateSummary`, and calls that method. The prior healthy trace paired the
follower SEND and leader RECV of this packet with the guard. Its six-trial
pilot applied six archive I/O faults but reached no guard on the affected
packet path. Those observations remain negative evidence.

This source-only version combines that ACKEPOCH packet-object correlation
with the `QuorumPeer.run` FOLLOWING retry hook already demonstrated for
ZOOKEEPER-07. On a follower-side `ACKEPOCH` I/O failure,
`Follower.followLeader` catches the error and returns after closing the
socket. The enclosing FOLLOWING `finally` shuts down the follower and, if
the peer is still running, submits a unique task token. Only the next
FOLLOWING attempt on the identical `QuorumPeer` object, Java thread, and
lifecycle epoch may claim it. The next physical `ACKEPOCH` SEND/RECV must
then lead into the selected leader guard. A target check on a different
handshake without that observed chain is not retention.

The isolated node0 source is
`/users/ZhenyuLi/.mallory-worktrees/zookeeper-ackepoch-retry-node0`.
`data/mallory/admissions/ZOOKEEPER-06-ackepoch-retry-node0-source-v1.json`
pins its source hashes. It has not been compiled or run. After a disk and
lane admission, `finalize_ackepoch_retry_node0.py` will pin compiled class
hashes and make a fresh healthy-only config using the unchanged JUnit.
The healthy trace must pass JUnit, load the pinned `Leader.class`, name both
peers, and show an observed pretarget ACKEPOCH packet path. A bounded pilot
must apply a fault on the *follower* side and prove this ordered chain:

1. Exact fault in the old scoped FOLLOWING attempt.
2. Retry TASK_SUBMIT and unique TASK_CLAIM on the same peer/thread/epoch.
3. New ACKEPOCH SEND, paired RECV, exact ACKEPOCH scope and target check.

The source rule does not show that the fault changes either `StateSummary`
operand. No full campaign or bug claim follows from a healthy trace alone.
