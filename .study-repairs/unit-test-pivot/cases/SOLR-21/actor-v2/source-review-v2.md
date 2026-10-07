# SOLR-21 source and original JUnit scope

The exact target is Solr 8.11.4 `CoreContainer.reload(String, UUID)` at `CoreContainer.java:1765`: after `registerCore`, the method reads the collection state and calls `docCollection.getReplica(cd.getCloudDescriptor().getCoreNodeName())`; the check is `assert replica != null`. The case-local ASM hook records this precise guard and `AssertionError` throw, with the runtime core and actor identity. The original source revision is `e27f44e3d78dfcec230c97e0a1240e3751daeff9`; the unchanged test and release JAR hashes are recorded in `junit-build.json`.

The mapped original embedded-cluster test is `CollectionReloadTest#testReloadedLeaderStateAfterZkSessionLoss`. Its `@BeforeClass` starts one Jetty in `MiniSolrCloudCluster`. The test creates a one-shard, one-replica collection, invokes `reloadCollection` at line 60, waits for the new core start time, then calls `cluster.expireZkSession(...)` at line 75 and waits for the replica to re-register ACTIVE. The healthy actor-V2 runs each observed the target guard once during the reload and no target assertion. The explicit session expiry happens **after** that reload. A source scan of the original `solr/core/src/test` tree found no other Java test file containing both `expireZkSession` and `reloadCollection` or `reloadCore` calls.

This order limits what a negative campaign can establish. Exact I/O faults during the original reload can test the descriptor/collection-state consistency at this check, including the observed `core.properties` file read and ZooKeeper calls. The original test does not directly test a session expiry before or concurrent with the reload that reaches this same guard. A result with no target assertion must retain this workload gap; it is not proof that all session-loss/reload interleavings preserve the replica mapping.

The actor-V2 campaign uses no static graph or precomputed region skeleton. It binds the actual `SolrZkClient` object to stable `JETTY/node1`, checks the raw physical Jetty and exact core properties path, and records an original JUnit/JaCoCo execution for each fault plan. Two new healthy seeds and every trial are preserved on node2; the main 102-case table counts only the new actor-V2 fault plans. The older 80 coarse actor plans remain historical evidence under `legacy_coarse_actor`.

The completed actor-V2 raw recount found 128/128 strict injections with the
same target guard after the final fault on the same actor and physical node,
and zero exact `AssertionError` outcomes. Original release-JAR coverage added
7 production methods and 31 branch outcomes. This supports completion for
the original test's reload-before-expiry window only; it does not resolve the
expiry-before/concurrent-reload workload gap described above.
