# ZOOKEEPER-02 actor V2 adapter

This case uses original ZooKeeper 3.8.7
`org.apache.zookeeper.test.QuorumTest#testSessionMoved`, source commit
`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`. The old actor-free
80-trial evidence and checkpoint remain separate.

The test starts five actual `QuorumBase` peers (SIDs 1–5), creates an
ephemeral node on `handle:0`, then makes ten successive client handles using
the **same raw session ID**. Each `handle:i` has a distinct client object and
a fixed destination peer `(i % 5) + 1`. The adapter binds the original
`qb.s1..s5`, `portClient1..5`, `hostPort` order, snapshot directories and
`ZooKeeper.cnxn` objects. The I/O hook reads the real socket channel and
remote port. A wrong destination, unknown handle, missing session or unknown
channel is excluded before matching a fault.

`SessionTrackerImpl#checkSession` line 322 compares the *actual object*
stored in `SessionImpl.owner` with the request owner; line 323 throws
`SessionMovedException`. A bound target guard requires the moved raw session
on the actual current leader's `ZooKeeperServer` and owner objects that map
either to the local `ServerCnxn.me` singleton or to a `LearnerHandler` whose
actual `sid` and `learnerMaster.zk` match that leader. Its `OWNER_BIND`
receipt records both logical owner keys **and** whether the two Java object
references are identical. A follower, unknown owner type, stale leader,
unregistered SID or unrelated session cannot count as target retention.

`python3 build_adapter.py` builds the agent outside the repository and runs
offline ASM stack analysis plus a same-callsite smoke with two handles on one
raw session. The wrong peer and unknown handle are excluded. No cluster JVM
is started by this build. `python3 calibrate_healthy.py` only prepares two
fresh original-JUnit commands. After a port slot and cluster resources are
reserved, `python3 calibrate_healthy.py --run --worker-id 1 --worker-count 1`
runs them into `/users/ZhenyuLi/zk02-actor-v2-runs/healthy-{a,b}` without
overwriting existing results. `python3 audit_calibration.py` checks the five
peer joins, all eleven handle roles, one shared raw session, owner object
identity, selected guard, production coverage, and stable selector families.
It remains `pending` until those fresh healthy runs execute.

The independent V2 campaign budget in `v2-budget.json` is 80 effective
actor-bound, target-retained trials with up to 8 faults per sequence;
evidence of novel target-related coverage, a new bound I/O family or a
candidate target throw can extend this case to 128 effective trials and 10
faults. A missing fault match or lost target does not consume the effective
denominator. The old 80 actor-free trials are not counted toward V2.
