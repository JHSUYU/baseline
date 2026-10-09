# HDFS-19/20 heartbeat bridge release

`mallory-hdfs-adapter.jar` has SHA-256
`d7960a24a4ce21633d870d30d796daf5cc9d9170fe9bfc2e0e9fac16986cbc58`.
The two release-local healthy configs pin this JAR and the runtime artifacts.
`mallory-agent-38658059.jar` is a scoped copy of the pinned instrumentation
JAR with SHA-256
`38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9`.
They retain one fault-free calibration run, no automatic promotion, and the
existing `TestDFSFinalize#testFinalize` and
`TestStandbyIsHot#testStandbyIsHot` workloads.

The isolated clean build passed four focused JUnit tests with no failure,
error, or skip. `HdfsHeartbeatReleaseSelectorTest` transformed the pinned
Hadoop 3.4.3 class images and checked the reply decoder, target consumer, and
command queue selectors. `release-receipt.json` pins the build inputs,
Hadoop images, configs, test reports, and embedded JAR classes. Run
`heartbeat-v1/verify_immutable_release.py` with this directory as its sole
argument for an offline digest and gate check.

No cluster JVM has used this release. Dispatch must run a separate named
healthy JUnit for each case on an idle lane, observe a passing target on a
named DataNode, and attest a root-free event-time path from an explicit
`IOException` door through the completed IPC reply to the selected target.
HDFS-19 additionally needs the matched command queue submit and claim. No
fault or full campaign is admitted before that case's healthy and strict path
gate passes.

The historical `heartbeat-v1/check_preflight.py` expects an older active
adapter transformer hash. That mutable active file has changed during HDFS24
work; this release's verifier checks the isolated bridge source and packaged
bytecode directly.
