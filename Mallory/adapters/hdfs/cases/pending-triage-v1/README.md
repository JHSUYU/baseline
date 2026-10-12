# Pending HDFS healthy-seed triage (source only)

`preflight.json` records SHA-256 hashes of the exact Hadoop 3.4.3 source,
selected JUnit source, prior healthy-trial evidence, pinned agent, and eight
healthy-only configs. `prepare.py` deterministically regenerates the configs
and receipt. It does not launch a JVM or inject a fault. Each config is limited
to one fault-free calibration trial, uses the frozen thread-ID/SafeWriter agent
and event-time causal gate, and disables automatic campaign promotion.

| Check | Candidate cluster JUnit | Current decision |
| --- | --- | --- |
| HDFS-24 | `TestDFSUpgradeFromImage#testUpgradeFromRel22Image` | Staged existing old-image alternate; original test raised selected guard. Needs admitted lane and about 1 GiB transient disk. |
| HDFS-26 | `TestDFSRollback#testRollback` | Retain original. It already reached exact check without throw; requires concrete DN identity and VERSION-read path. |
| HDFS-29 | `TestPipelinesFailover#testLeaseRecoveryAfterFailover` | Staged existing shorter three-DN HA alternate after prior instrumented original JUnit timeout. Alternate target reach is unverified. |
| HDFS-30 | `TestPipelinesFailover#testLeaseRecoveryAfterFailover` | Stage same shorter HA alternate for the second guard in `getActiveNamenodeForBP`. Alternate target reach is unverified. |
| HDFS-33 | `TestDataNodeHotSwapVolumes#testAddOneNewVolume` | Retain original. It reached exact nonthrowing assertion but lacked owner binding for `VolumeBuilder`. |
| HDFS-34 | `TestDFSUpgradeFromImage#testUpgradeFromRel22Image` | Staged existing old-image alternate; original version-matrix test deliberately raised selected exception. Shares fixture with HDFS-24. |
| HDFS-37 | `TestFileTruncate#testUpgradeAndRestart` | Staged existing valid rollback alternate; original rollback test deliberately raised selected exception. |
| HDFS-48 | `TestRenameWithSnapshots#testRenameUndo_1` | Existing NN-only v14 healthy seed already passed; do not rerun for count. Ten effective RpcCall faults prevented postfault target, so full campaign remains held. |

Dispatch must allocate an idle isolated source/build lane and verify at least
5 GiB free on node0 before admitting old-image probes. A JUnit pass alone is
insufficient: require the exact named target check without its selected throw,
a root-free event-time path from an observed I/O door, and an offline audit.
HDFS-48 needs a new source-backed fault door that leaves the rename operation
able to reach `INodeDirectory.replaceChild` after injection.
