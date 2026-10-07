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
`stable_actor_io_gain`, because `campaign_v1.py` initializes
`stable_actor_io_families` from the two healthy traces only (lines 198–205).
Independent application of its `stable_io` function finds neither family in
the healthy **target-path** sets. However, the earlier fault pilot `pilot-01`
already observed the same `dn1`, same recovery root, same two stable families
at seq 35/36, followed by the same HDFS-28 guard at seq 46. Thus trial 179
repeats a target-path I/O behavior already present in the seed evidence. The
pilot is correctly excluded from the effective trial denominator, but it
must be included when deciding whether behavior is genuinely new across all
prior evidence. Trial 179 alone does **not** justify the conditional
128-effective extension. Its target-related method/branch coverage gain is
also zero.

Evidence SHA-256:

- Trial 179 raw trace: `7bd484e1d28c4b8c073a881d8f5e8ba83bfc57f9339ea7dd45547758c2e8e784`
- Pilot 01 raw trace: `cf90e0c3b6bea58cae4ec6aa5c89d5d6169466ddea346f31daa4af71bcc3b5a7`
- `campaign_v1.py`: `eb086e62aa536a4a778f59382c6f1f56a5f776a6d5dda435aadbde795dff945d`
- Hadoop 3.4.3 `BlockRecoveryWorker.java`: `928a3e6d159a47a2f8c88e1720211ddf7af62129a5ed2d5a9f133f7ada60499b`
