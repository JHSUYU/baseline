# ZOOKEEPER-01 actor V2 adapter

This directory is independent of the old ZOOKEEPER-01 evidence, checkpoint,
and 80-trial budget. It instruments the original ZooKeeper 3.8.7 compiled
JUnit `SessionUpgradeQuorumTest#testCloseSessionWhileUpgradeOnLeader`, source
commit `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`.

## Exact binding contract

`makeSureEphemeralIsGone(int)` receives the leader slot selected by the
original test. Its actual `qpMain[]` peers supply quorum SID and snapshot
directory; `clientPorts[]` supplies the destination port for each peer. The
selected physical SID receives the cross-run `peer-role:leader` alias. The
first and second `ZooKeeper` constructor results become respectively
`creatorCloser` and `verifier`; their actual `ClientCnxn` objects carry the
logical session tags through asynchronous socket callbacks.

At `ClientCnxnSocketNIO#doIO`, the adapter reads the actual `sockKey` channel,
its remote port, and the socket's raw session ID. A client I/O selector is
bound only if the `ClientCnxn`, channel, and destination port join the
registered test actors. On `NIOServerCnxn` I/O it reads the actual
`zkServer`, connection, and session ID; I/O before session registration is
excluded. On peer epoch-file operations it checks the actual peer receiver
against the file's snapshot-directory owner. The selected target is
`SessionTrackerImpl#checkSession` line 316, with the throw on line 317. Its
`expirer` is the actual `ZooKeeperServer`; that server's quorum SID must equal
the selected leader and the raw session must join the first (`creatorCloser`)
client. Checks on the later verifier session cannot count as the target.
Unknown actor, server, session, destination, or file owner emits an `UNBOUND`
event and cannot match an injection plan.

## Current evidence

`python3 build_adapter.py` compiles an agent outside the repository, analyzes
all rewritten methods' ASM stack frames offline, and checks the actual
test/production class rewrites. The isolated smoke calls the same bridge
entrypoints with two clients at one static site: only the selected actor
matches; an unknown actor is excluded. This does not run JUnit or a cluster.

`python3 calibrate_healthy.py` prepares two fresh healthy original-JUnit
commands without running them. Once a ZooKeeper port slot and JVM resources
are reserved, run e.g. `python3 calibrate_healthy.py --run --worker-id 1
--worker-count 1`; the two outputs go only to
`/users/ZhenyuLi/zk01-actor-v2-runs/healthy-{a,b}` and existing outputs are
never overwritten. Before each JVM the script requires a free PortAssignment
slot and at least 2 GiB disk headroom. `python3 audit_calibration.py` then requires both original
JUnit executions to pass, three peer/port joins, separate client and raw
session tags, bound I/O to the selected leader, the selected guard on the
leader's `creatorCloser` session, nonempty coverage, and stable actor/resource
families across the fresh runs. It currently reports `pending` because no
cluster JUnit was run during this preparation.

Fault trials and a `quality_complete` determination require those two
calibrations and their binding audit. The old actor-free receipts do not
become V2 evidence by relabeling their selectors.
