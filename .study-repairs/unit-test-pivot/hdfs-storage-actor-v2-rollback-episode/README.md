# HDFS-26/37 rollback episode scheduler handoff

This is an isolated controller/image for continuing the **original**
`TestDFSRollback#testRollback` embedded-cluster JUnit after the old controller
finished plan 84. The prior V2 overlay and its actor matching remain frozen at
SHA-256 `a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`.
The old raw runs and checkpoint stay at
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/rollback-constructor`.
This image reads that same checkpoint, but has its own code and build overlay.

Migration boundary: 84 distinct plans, HDFS-26 42 effective, HDFS-37 41
effective, `in_flight=null`; checkpoint SHA-256
`0a69ac8adc458cbc2efe66b1926ba46be274add9d32d49f4bca9309de7c15fcb`.
The final original trial `4e3aa6ba9223fbfbd279` was JUnit exit 0 and strict;
its manifest SHA-256 is
`7e12c053d8e10a75516a7ed438fca318337c37f3f79e426606c6417d6977222e`.
The old controller PID 3413908 was stopped only after its child JUnit had
finished and its checkpoint passed the independent raw audit, then terminated.
No legacy plan is repeated or counted again.

`campaign.pick` keeps the old one-in-ten bound-RPC exploration slot. Within
that slot it chooses a pending case/startup episode with the fewest previously
effective strict, same-actor postfault trials, then uses case deficit, score,
and queue age. Other picks preserve the old priority. This should sample the
calibrated HDFS-26 episode 15 and HDFS-37 episodes 3/13/21, which the deep
queue had largely starved. The queue, actor identity, fault cap, coverage
feedback, and effective denominators are unchanged.

`run_one_locked.py` holds the node-local `jvm-start.lock` across the Java/disk
gate and one original JUnit. `guarded_locked_campaign.py` accepts the exact
legacy checkpoint SHA once, requires the complete boundary, and publishes a
new locked receipt for each later plan. It can stop after two new completed
plans for a strict identity/target pilot; subsequent resumption from that
checkpoint uses the same launcher without the legacy SHA flag. Launch only
when Java before start is at most four and free disk is at least 10 GiB.

Offline `smoke_episode.py` verifies selection of an untested episode in the
periodic slot and unchanged ordinary score order. It does not run a cluster.
