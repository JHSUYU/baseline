# HDFS-14 early DataNode identity and exact key read-from calibration

This is a **healthy-only** revision of the existing two-instance
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite*`
MiniDFSCluster workload. The HDFS-14 target is
`BlockTokenSecretManager.checkAccess` at lines 411–412. The candidate typed
door is the `BPServiceActor.register` call to `registerDatanode` at line 829.
No fault campaign is admitted by staging this revision.

In Hadoop 3.4.3, `MiniDFSCluster.startDataNodes` calls
`DataNode.instantiateDataNode` at line 1808, then calls
`runDatanodeDaemon` at line 1842. Inside construction,
`DataNode.startDataNode` calls `BlockPoolManager.refreshNamenodes` at line
1955; that call starts the `BPServiceActor` threads. The old line-1842 hook
therefore named DataNodes after their registration RPCs. The v3 transformer
holds the concrete MiniDFSCluster receiver in a balanced thread-local scope
over the factory call and binds the concrete DataNode just before the
line-1955 refresh. The later line-1842 hook is idempotent. The scope closes
on return or `Throwable` and supports nested `startDataNodes` calls.

The immutable HDFS-12 key hook already observes actual `BlockKey` object
identity and per-key version while `addKeys` and `retrievePassword` hold the
same `BlockTokenSecretManager` monitor. This revision emits an additional
`STATE_WRITE`/`STATE_READ` pair with `version_confidence=exact` only when
the observed stored and returned non-null values match. A replacement,
removal, missing value, or unknown identity cannot make an exact edge. The
generic sampled map probes remain candidate evidence.

The v2 healthy trace contained four independently validated
`HDFS12_KEY_STATE` write-to-read pairs on named DataNodes. This is evidence
that the exact key relation is exercised by the chosen JUnit; it does not
establish a door-to-target path because the v2 registration doors were
unnamed. The v3 healthy gate requires 2/0/0 JUnit, named registration doors
and exact targets, and an observed event-time path from one registration door
through exact key state to the same target. Dispatch must review the trace
before admitting any fault run. Registration IOException may only delay
startup, so target retention under a fault remains a separate gate.

`preflight.py --static` checks local pins without launching Hadoop.
`VerifyHdfs14Overlay` transforms the real compiled Hadoop classfiles
offline. The isolated Maven build ran 25 agent tests and 3 adapter tests.
Only dispatch may run `run_healthy.sh` on node2 after admission; it uses the
existing HDFS lane lock. No Docker or canonical checklist changes.
