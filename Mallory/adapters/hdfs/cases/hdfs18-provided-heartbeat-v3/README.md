# HDFS-18: real PROVIDED heartbeat, healthy-only node2 package

The original `TestSecureAliasMap#testSecureConnectionToAliasMap` MiniDFSCluster
test passed but missed the selected `DatanodeDescriptor.injectStorage` assertion.
This package uses the test-local adaptation from v2 to request a second real
DataNode heartbeat after the first PROVIDED storage report. It does not call
`injectStorage` directly or fabricate a storage identity. A case-local HDFS
adapter scopes `ProvidedStorageMap.updateStorage` to its registered NameNode.

The adapter was built from pinned adapter sources at commit `597689a8` plus
the v2 `nn-owner-adapter.patch` in a private build tree; its two existing tests
passed. The Hadoop test source was rendered by the v2 anchored patch helper
in a clean `9d50c688` worktree; `mvn -o -pl hadoop-hdfs-project/hadoop-hdfs
-DskipTests test-compile` succeeded. The compiled target archive was copied
to node2 at `/tmp/mallory-hdfs18-target-compiled.tar.zst` and SHA verified.
`package-manifest.json` pins those artifacts and the complete patched source
snapshot. The old v2 raw patch file is a visual sketch whose line-zero hunks
are not directly applicable; `prepare_node2.py` uses the SHA checked anchored
renderer.

On node2, after its current HDFS lane completes, run `prepare_node2.py` once.
It verifies the complete original source snapshot before copying, applies the
anchored test patch, extracts the compiled target archive, and performs the
no-JVM runtime preflight. Dispatch may then run `run_healthy.sh` once with
`MALLORY_HDFS18_V3_NODE2_GRANT=healthy-only`. The runner takes the existing
HDFS node2 lane lock and refuses an existing output directory. No full fault
campaign is admitted until healthy evidence shows one passing JUnit, the
second-heartbeat marker, a named exact target check on `nn0`, and a relevant
typed I/O door that can retain the target after injection.
