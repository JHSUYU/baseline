# HDFS-29 diagnostic source and JUnit admission

The existing `TestPipelinesFailover#testLeaseRecoveryAfterFailover` method
starts a three-DataNode HA `MiniDFSCluster`, fails over to NameNode 1, and
recovers a lease. It avoids the delayed Mockito commit callback that timed
out in the prior instrumented HDFS-29 selector. Whether this alternate
reaches the exact HDFS-29 check on a named DataNode remains unobserved.

`HDFS-29.sites.json` selects one typed pretarget door:
`BlockRecoveryWorker.callInitReplicaRecovery` line 561 invokes
`InterDatanodeProtocol.initReplicaRecovery`, which declares `IOException`.
`RecoveryTaskContiguous.recover` catches a per-replica `IOException` at lines
162–166, continues the loop, and calls `syncBlock` at line 183 if not all
replicas failed. `syncBlock` calls `getActiveNamenodeForBP`, whose selected
check is `@577:branch:1` and selected throw is `@578:throw:1`. The offline
classfile check confirms that call, catch coverage, continuation, and guard.

This door has a **fault-model gap** for the selected exception. The recovery
loop calls `getDatanodeID(bpid)` and obtains a non-null `BPOfferService`
before `initReplicaRecovery`. Catching an error from that replica RPC does
not remove the block-pool mapping. A later same-task check can still run,
but this one-shot error alone does not make its `bpos == null` operand true.
An independent concurrent state change would be needed to explain that
throw. Neither source nor an observed trace establishes such a change.

The config is one-trial, fault-free, and diagnostic only. It bundles scoped
copies of the frozen agent (SHA-256
`38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9`)
and v11 recovery adapter (SHA-256
`d210764e9b7f812a52a56235794677047318648b35c659fe9fb0bf014c4670e7`).
`source-receipt.json` pins the config, selector, Hadoop source and classes,
and both JARs. Run `python3 check_offline.py` to verify all pins and source
conditions without a Hadoop JVM.

An optional healthy probe, only after dispatch grants a separate idle HDFS
lane, can resolve whether this alternate JUnit passes and reaches the exact
nonthrowing check on a named DataNode with a strict root-free event-time path
from the explicit door. Such a probe would not resolve the fault-model gap.
Do not promote a fault or full campaign from this door on the current
evidence. No live JVM or fault trial was started for this handoff.
