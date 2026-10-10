# HDFS-37: normal DataNode rollback healthy seed on node2

`DataStorage.doRollback` reads `previous/VERSION` and rejects a previous
layout version or creation time that is newer than the namespace. The original
`TestDFSRollback#testRollback` MiniDFSCluster test runs a valid DataNode
rollback and checks the resulting storage directories, then deliberately tests
invalid versions. The latter phase reaches the selected exception by design.

The SHA-pinned v2 test-local patch returns just after the valid DataNode
rollback assertion, shutdown, and storage cleanup. It preserves the complete
valid rollback prefix. The target is the `DataStorage.doRollback` condition at
lines 940–941 and its `InconsistentFSStateException` throw at line 947. The
candidate pretarget doors are `BPServiceActor.retrieveNamespaceInfo`
`versionRequest` and `StorageInfo.readPropertiesFile` `Properties.load`; their
actual event-time path and fault-retaining behavior must be established by
the healthy trace. An expected invalid-layout exception is not a bug.

`package-manifest.json` pins the pristine Hadoop commit and complete source
digest, the complete source digest after applying only the test patch, the
patch and site catalog, the Mallory agent and HDFS adapter, and the compiled
`DataStorage` and original `TestDFSRollback` classes from the node2 HDFS seed.
The adapted test class is not yet built. The blocked config is a healthy-only
template; it cannot be run as a full campaign.

Run `python3 -B preflight.py` on node0 or node2 for a read-only static check.
After dispatch grants exclusive node2 HDFS lane access, run
`MALLORY_HDFS37_V3_NODE2_BUILD_GRANT=healthy-only python3 -B prepare_node2.py
--apply` on node2. It copies pristine source and the pinned compiled target
into a dedicated tree, applies the test patch, compiles the adapted JUnit test,
and emits a SHA-bound compiled receipt and runtime config. The source/build
step takes the same node2 lane lock as the campaign runner.

Dispatch may then run one healthy-only seed with
`MALLORY_HDFS37_V3_NODE2_RUN_GRANT=healthy-only ./run_healthy.sh` on node2.
The runner refuses an existing output directory and checks the runtime source,
class, config, and release pins before launching Java. The healthy gate
requires JUnit 1/0/0, the normal-phase marker, exact selected checks on the
named DataNode, zero selected throws, a unique target class/loader hash, and a
named pretarget I/O door with an observed target path. No fault campaign is
admitted by this package. Archive and audit the healthy trace before deciding
whether the target has a suitable fault-retaining frontier.
