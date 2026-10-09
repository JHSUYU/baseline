# HDFS-30 source feasibility after the HDFS-29 healthy seed

**Disposition:** HDFS-30 has a more direct control-plane state path than
HDFS-29, but the current exception frontier does not establish it. This is
read-only source analysis; no HDFS-30 JUnit or fault trial was launched.

The selected check is the second guard in
`BlockRecoveryWorker.getActiveNamenodeForBP`:
`if (activeNN == null)` at line 582, with `IOException` at line 583. After
HDFS-29's non-null block-pool lookup, `BPOfferService.getActiveNN()` returns
the NameNode proxy from `bpServiceToActive`, or null if that actor reference
is null (`BPOfferService.java:519–533`). The v16 HDFS-29 trace contains a
normal `BRANCH` event at line 582 on named dn0 in the same target occurrence,
but it is not an HDFS-30 `TARGET_CHECK` marker and cannot itself admit
HDFS-30.

There is a concrete state writer: `updateActorStatesFromHeartbeat` installs
a newer active actor or clears the old actor when a standby heartbeat arrives
(`BPOfferService.java:567–603`). `BPServiceActor.offerService` calls
`sendHeartbeat`, then applies the returned HA status to the BPOS *before*
enqueuing commands from that response (`BPServiceActor.java:563–575,
719–737`). It catches `IOException` and retries (`BPServiceActor.java:786–788`).
Therefore a failed heartbeat skips that response's state update and its
commands; the exception alone does **not** clear `bpServiceToActive`.

The recovery command is processed on a separate command thread.
`BPOfferService.processCommandFromActor` first checks whether the command's
actor equals the current `bpServiceToActive` (`BPOfferService.java:662–695`);
only an active actor's `DNA_RECOVERBLOCK` launches the recovery worker
(`BPOfferService.java:774–778`). A possible null-at-check schedule would
need a recovery worker already launched, a later standby heartbeat clearing
the active actor, and a delayed or failed new-active update before that worker
reaches line 582. The 3-DataNode HA lease-recovery JUnit changes the active
NameNode, so this schedule is relevant, but neither source nor the HDFS-29
trace proves that it occurs in the selected test.

The two HDFS-29 observed doors are generic inbound `Server$RpcCall.run`
calls on secondary dn1/dn2 for replica recovery. They can alter the replica
responses to dn0; they do not change dn0's `bpServiceToActive`. The current
v11 adapter records recovery-task handoffs but lacks a typed heartbeat
response/status hook that binds NameNode identity, DataNode epoch, block
pool, HA state/txid, and the resulting actor update to the worker occurrence.
For HDFS-30, a future fault frontier should target the **dn0 heartbeat
response/update path** and observe the command queue and recovery-worker
handoff. A fresh HDFS-30 healthy run must first attest the exact line-582
target on a named DataNode and a strict observed door→target path. No fault
pilot follows from the present v16 HDFS-29 seed.

This complements the earlier offline review in
`Mallory/adapters/hdfs/cases/hdfs30-heartbeat-control-admission-v1/README.md`.
