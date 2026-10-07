# HDFS-28 original HA JUnit: pending RPC successor

`target_rpc_v3.py` is an offline-prepared successor for the existing
`TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization` campaign.
It may hand off only after the V2 controller naturally writes a complete
320-attempt `attempt_cap_inconclusive` checkpoint, has no reserved/started
trial, exits, and its independent raw audit passes. It does not touch the
running V2 controller. The HDFS-29/30 terminal claims remain the first 203
shared attempts and their first 80 effective trials each.

The new singleton selectors are discovered only in prior exact, same-owner
HDFS-28-effective original JUnit traces. Each candidate has an observed
`RECOVERY_BEGIN`, a physical `dnN` source, block/recovery root, and a later
HDFS-28 guard on the same root. Full selector IDs are compared against the
old `seen` ledger. The dry-run at 252 completed attempts found 12 unseen
`HDFS_RPC:INIT_REPLICA_RECOVERY` IDs and 12 unseen `HADOOP_IPC:REQUEST` IDs,
with two ordinals on each of the `dn0`/`dn2` second recovery roots. It copied
the state in memory, appended those 24 IDs, and verified old completed,
active, queue, seen, coverage and I/O prefixes without writing a checkpoint.

After a successful natural handoff, the priority order within the existing
4 RPC : 1 FILE lane is new HDFS RPC singletons, then new HADOOP IPC
singletons, then V2's original selection. Existing file plans keep their
one-in-five exploration opportunity. Because HDFS-28 remains below its 80
effective target and the new plans are raw-observed but untested, this
successor raises only the attempt cap from 320 to 512. It leaves the
80-effective goal, fault-depth limit, actor identity, JUnit and existing
per-case counters intact. If no new plan hits, the campaign may still end
inconclusive at 512; that outcome must be reported as such.

The actual handoff will write an intent and receipt with old/new checkpoint
SHA, selector IDs and raw-audit SHA. A candidate target exception still
requires source review and replay; it is not automatically a new bug.
