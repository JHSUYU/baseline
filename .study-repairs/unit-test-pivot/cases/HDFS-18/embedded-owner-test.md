# HDFS-18 original cluster test review

The selected assertion is `DatanodeDescriptor.injectStorage` at
`DatanodeDescriptor.java:537`: `assert storage == s`. It requires the existing
storage-ID branch. Source revision `9d50c688466` was reviewed from the
unchanged Hadoop 3.4.3 source tree.

The closest original MiniDFSCluster test is
`TestSecureAliasMap#testSecureConnectionToAliasMap`. It starts one DataNode
with DISK and PROVIDED volumes. The original Maven JUnit passed (1 test,
0 failures, 0 errors; 8.304 seconds). Three instrumented runs of that same
test also passed (9.746, 10.142, and 9.140 seconds). Each observed only the
first-storage-insertion branch; the selected existing-entry identity check
ran zero times. The run summaries and hashes of the original traces are in
[verdict.json](verdict.json).

`TestProvidedStorageMap#testProvidedStorageMap` and
`TestBlockManager#testSafeModeWithProvidedStorageBR` exercise nearby code,
but use direct or mocked components rather than an embedded cluster. No
unchanged cluster JUnit was found that drives a second report through this
selected assertion. HDFS-18 is therefore `no_cluster_test` under the
original-test-only rule: no fault trial was run, and this is a workload
reachability gap rather than a negative bug result.
