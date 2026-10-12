# ZOOKEEPER-04 pretarget I/O triage v2

The prior `ConnectionMetricsTest#testRevalidateCount` healthy run reached the
selected `ZooKeeperServer.processConnectRequest` zxid guard on named `zk2`.
The old fault door, `zookeeper.client.connect.read`, is before the guard. A
source hook throws from that door, so it aborts the **current** connect
attempt. The SHA-pinned first pilot trace shows `FAULT_APPLIED` at sequence
637 in `zk2` occurrence `root:1`; the next selected check is sequence 683 in
occurrence `root:2`. There is no selected check in the faulted occurrence.
`source-preflight.json` pins the prior traces, audit, source, test, overlay,
agent, and proposed config hashes. This is a
`fault_model_target_lost_for_exact_connect_attempt` conclusion for the old
door, not for the entire check.

There is a more precise source-backed candidate. In the same method,
`BinaryInputArchive.readBool("readOnly")` (ZooKeeper 3.8.7 line 1417, patched
line 1420) reads the decoded connect request and declares `IOException`.
`processConnectRequest` catches `IOException` immediately and continues to
the selected `lastZxidSeen > lastProcessedZxid` guard (original line 1431,
patched line 1434). The existing three-peer test connects to regular
followers, so the intervening `ReadOnlyZooKeeperServer` rejection branch does
not apply. This makes the readBool call a plausible **same-occurrence**
exception door; its fault does not itself change either zxid operand.

`ZOOKEEPER-04.readbool.sites.json` adds only that exact invocation as an
explicit `IOException` door. The source overlay is unchanged. The
`ZOOKEEPER-04.readbool.healthy-only.json` preflight pins an immutable agent
with numeric thread IDs and event-time causal gating, source overlay, compiled
target class, site file, and one existing cluster JUnit selector. It has one
fault-free trial and cannot auto-promote. `prepare.py` regenerates both and
checks the old trace sequence/occurrence claim before writing the receipt.
Read-only inspection on node2 confirmed that the isolated overlay has the
readBool call at line 1420, the guard at line 1434, source SHA-256
`6011ece2590691c458bfd4cc95758c732a31717586ad7d0952c6cab056efeb9e`,
and compiled `ZooKeeperServer.class` SHA-256
`76cc1c01d29c85231d204c6ac302beaab64512b60576494484f78e542ebf0e0b`.

No JUnit or fault trial was launched for this v2 preflight. Before a bounded
pilot, the healthy run must pass JUnit, load the pinned class, record the exact
named nonthrowing target, and catalogue the proposed
`processConnectRequest(...)@1420:door:1` with `IOException` on a root-free
same-thread path to that target. The pilot must inject at that **specific**
readBool door and independently verify `FAULT_APPLIED` followed by the exact
target in the same node, epoch, thread and occurrence. Generic connect-read
faults and unrelated later checks remain excluded. A selected target throw
would still need source review and replay before classification as a new bug.
`pilot-gate.json` records this proposed six-trial admission; it is not a
runnable campaign config until the fresh healthy evidence exists.

`ZooKeeperServerTest#testClientZxidAhead` directly constructs a mock server
and intentionally asserts the selected exception. It is neither a passing
healthy cluster workload nor a substitute for this calibration.
