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
all rewritten methods' ASM stack frames, and loads the rewritten classes in
a separate JVM with `-Xverify:all`. The isolated smoke calls the same bridge
entrypoints with two clients at one static site: only the selected actor
matches; an unknown actor is excluded.

`python3 calibrate_healthy.py` prepares two healthy original-JUnit
commands without running them. With an assigned port slot, run e.g.
`python3 calibrate_healthy.py --run --worker-id 15 --worker-count 16`;
the two outputs go only to
`/users/ZhenyuLi/zk01-actor-v2-runs/healthy-{a,b}` and existing outputs are
never overwritten. Before each JVM the script requires a free PortAssignment
slot and at least 2 GiB disk headroom. `python3 audit_calibration.py` requires both original
JUnit executions to pass, three peer/port joins, separate client and raw
session tags, bound I/O to the selected leader, the selected guard on the
leader's `creatorCloser` session, nonempty coverage, and stable actor/resource
families across the fresh runs. The two repaired original-JUnit calibrations
passed in 4.978 and 4.227 seconds; the first attempted calibration failed
bytecode verification and is retained separately under `failed-seeds/`.

`campaign.py` resumes an independent 80-effective/max8 campaign in worker
slots 15 and 16. Only complete ordered fault matches with a bound relation
to the selected leader and a later target guard count toward the 80. Trial
scratch is removed after each original cluster JUnit; raw events, coverage,
logs and receipts remain under the V2 run root. A late coverage or I/O gain
in the last eight effective trials extends the budget to 128/max10. The
checkpoint can be resumed after interruption, and disk below 2 GiB pauses
new trials. A selected target throw is marked for source review, never
automatically labeled a new bug. The old actor-free receipts do not become
V2 evidence by relabeling their selectors.
