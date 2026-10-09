# HDFS-28 alternate JUnit trial 179 feedback review

This review concerns the original Hadoop 3.4.3
`TestPipelinesFailover#testLeaseRecoveryAfterFailover` campaign. It does not
alter the running fault scheduler, completed-trial ledger, or effective
denominator.

Trial 179 injected one exact `IOException` at the `dn1` Hadoop IPC
`initReplicaRecovery` request at trace seq 22. The physical owner is
`dn1/block:1073741826/attempt:1`; its HDFS-28 `getDatanodeID` guard ran at
seq 24 and again at seq 30, both after the fault. The same recovery worker
thread observed a second `initReplicaRecovery` HDFS RPC and Hadoop IPC request
at seq 26 and 27, between those two guards. The selected guard outcome stayed
false and the original JUnit passed.

In `BlockRecoveryWorker.RecoveryTaskContiguous.recover` at lines 130–164, the
per-replica loop calls `getDatanodeID(bpid)` before
`callInitReplicaRecovery`; its `IOException` catch allows the next loop
iteration. The seq 26/27 requests are therefore on the control path to the
**later** seq 30 guard in this recovery attempt. They do not establish that
the RPC response changed the guard's `bpos` value; `getDatanodeID` reads the
local `datanode.getBPOfferService(bpid)` at lines 536–542.

The live feedback marked the two request families as
`stable_actor_io_gain`. `campaign_v1.py` initializes
`stable_actor_io_families` from the two healthy traces (lines 198–205), and
the independent `audit_campaign.py` additionally includes only the pilot's
I/O **after its own applied fault, on that fault's physical actor and root**.
The healthy target-path sets contain neither family. The earlier `pilot-01`
did observe the same `dn1` I/O families at seq 35/36 followed by a `dn1`
guard at seq 46, but its applied fault at seq 12 was on **dn2**. Those `dn1`
requests are therefore outside the pilot's same-fault-actor successor set.
Independent application of `stable_io(pilot_events, pilot_last_fault)` finds
no overlap with trial 179's two gained families. Trial 179 is the first
observed **dn1 fault → dn1 I/O → later dn1 guard** path for these families.

This is fault-conditioned, actor-bound I/O novelty on the target guard's
control path under the predefined feedback rule. The request APIs themselves
were already observed elsewhere, so it must not be described as a globally
new I/O operation or as proof that the guard value changed. The trial's
target-related method/branch coverage gain is zero. If this effective trial
falls in the applicable last-eight window, its actor-bound postfault I/O
feedback can justify the conditional 128-effective budget, subject to the
separate ledgers and independent final audit.

Evidence SHA-256:

- Trial 179 raw trace: `7bd484e1d28c4b8c073a881d8f5e8ba83bfc57f9339ea7dd45547758c2e8e784`
- Pilot 01 raw trace: `cf90e0c3b6bea58cae4ec6aa5c89d5d6169466ddea346f31daa4af71bcc3b5a7`
- `campaign_v1.py`: `eb086e62aa536a4a778f59382c6f1f56a5f776a6d5dda435aadbde795dff945d`
- Hadoop 3.4.3 `BlockRecoveryWorker.java`: `928a3e6d159a47a2f8c88e1720211ddf7af62129a5ed2d5a9f133f7ada60499b`
