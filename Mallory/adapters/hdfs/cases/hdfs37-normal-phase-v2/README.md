# HDFS-37 named DataNode healthy package

The unchanged `TestDFSRollback#testRollback` MiniDFSCluster test reaches
`DataStorage.doRollback` lines 940–941 during normal DataNode rollback, then
intentionally reaches its selected throw at line 947 in later invalid-version
phases. `normal-phase.patch` places a test-only return after the original
normal rollback assertion, shutdown, and cleanup. The valid rollback prefix
and its I/O remain in source order.

The pinned HDFS adapter registers `DataNode.storage` before daemon startup
and scopes `DataStorage.doTransition` by that registered receiver. Its nested
`doRollback` target should therefore be attributed to
`hdfs-cluster-1/dn0`. `python3 -B preflight.py` checks the pristine and
patched test source hashes, patch applicability, target class hash, pinned
adapter hooks, blocked config, and frozen static frontier without starting
Java. No adapted test class has been built or run.

For runtime admission, create a dedicated checkout of Hadoop commit
`9d50c688`, apply only this test patch, compile, and SHA-pin the patched
test class. Run one healthy JUnit under an exclusive source lock. Require
JUnit 1/0/0, the normal-phase marker, exact selected checks on the named
DataNode, zero selected throws, a unique target loader/hash, and a named
pretarget I/O door. The current healthy template is blocked until that
evidence exists; it is not a full campaign config.
