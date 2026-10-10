# HDFS-18 named NameNode healthy package

This is a blocked healthy-only package for the selected
`DatanodeDescriptor.injectStorage` duplicate-storage assertion at line 537.
The unchanged `TestSecureAliasMap#testSecureConnectionToAliasMap` MiniDFSCluster
run passed but missed that branch. `real-heartbeat.patch` makes the same test
send one more ordinary heartbeat after confirming its first PROVIDED storage
entry. It does not call the target or fabricate a storage report.

The archived first target entry was `node=unknown`. The case-local
`nn-owner-adapter.patch` scopes `ProvidedStorageMap.updateStorage` to its
private `bm` field. `MiniDFSCluster` registration already binds that exact
`BlockManager` instance to its physical NameNode; the nested `injectStorage`
call should therefore inherit `hdfs-cluster-1/nn0`. The offline source and
config preflight passes with `python3 -B preflight.py`. No adapter JAR or
patched test class has been built, and no new JUnit has run.

For runtime admission, use an isolated checkout of pinned Hadoop commit
`9d50c688`, apply the test patch there, and apply the adapter patch in an
isolated Mallory adapter source copy. Compile each without replacing any live
JAR. Repin the resulting test class, adapter JAR, source tree, and site catalog
SHAs in a new healthy config. Run exactly one JUnit under an exclusive source
lock. Admit a full campaign only if the JUnit reports 1 test, 0 failures and
errors; assertions are enabled; the completion marker and exact duplicate
branch appear on `hdfs-cluster-1/nn0`; the selected throw is absent; the
target loader/hash is unique; and a named injectable I/O door is observed.
The current `HDFS-18-healthy-BLOCKED-template.json` deliberately names an
unbuilt adapter path and is not runnable.
