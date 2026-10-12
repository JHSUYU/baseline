# HDFS-18: adapted real PROVIDED heartbeat (unexecuted)

This is a test-only adaptation of Hadoop 3.4.3
`TestSecureAliasMap#testSecureConnectionToAliasMap`. It has **not** been
compiled or run. It does not change the production check, shared checklist,
or original source-review verdict. The original cluster calibration passed
but reached only the first `injectStorage` insertion
(`data/mallory/calibration/HDFS-18/trials/r0000`).

The selected check is `DatanodeDescriptor.injectStorage`'s object-identity
assertion for a duplicate storage ID (`DatanodeDescriptor.java:519-537`;
exact `@537:branch:5`, `@537:branch:6`, and `@537:throw:1`). After the
existing fixture starts its one-DN DISK+PROVIDED MiniDFSCluster, the overlay
observes the registered DN descriptor and confirms its first reserved
PROVIDED storage entry. It asks that same DN to send a second ordinary
heartbeat through `MiniDFSCluster.triggerHeartbeats()`, then waits until the
NN descriptor's heartbeat timestamp advances. No test code calls
`injectStorage` or creates a duplicate storage report. The adaptation is
enabled only by `-Dmallory.hdfs18.secondProvidedHeartbeat=true`.

The system path is `BPServiceActor.sendHeartBeat` (gets the live FsDataset
storage reports at :541, sends the heartbeat at :563) to
`DatanodeManager.handleHeartbeat` (:1833), `HeartbeatManager.updateHeartbeat`
(:263-273), `BlockManager.updateHeartbeat` (:2815-2823), and
`ProvidedStorageMap.updateStorage` (:192-202), which passes its one shared
`providedStorageInfo` object to `DatanodeDescriptor.injectStorage`.
`FsDatasetImpl.getStorageReports` includes the live volumes (:159-184).
That second delivery should take the duplicate branch and pass the identity
assertion. A second block report is not equivalent:
`ProvidedStorageMap.getStorage` avoids reinjection when the DN already has
that ID (:125-138).

`prepare_overlay.py` verifies the source and patch hashes offline. Its
`--apply` option writes only to the planned dedicated source checkout after
that checkout exists. No source checkout, compiled test class, or fresh
healthy seed is claimed here. `preflight.py` validates the staged templates,
released agent and adapter, target-class hash, and 80 trial / 3,600 second /
three fault full budget without Java. The full template remains blocked.

Admission requires a fresh adapted JUnit result of 1 test, 0 failures, and
0 errors; the completion marker; exact duplicate-branch coverage on the
registered NN descriptor; no selected throw; a single expected target class
loader/hash; and assertion-enabled execution. Only after those checks and
the core's named-actor and injectable-door attestation can a dispatcher
promote a separate full config. Record observed graph quality as an outcome;
the heartbeat RPC I/O door may prevent delivery rather than perturb storage
identity, so source inspection does not predict a three-fault assertion
failure. A returned JUnit failure or selected throw still requires causal
review against the fault plan and same DN/storage-ID/object identities.
