# SOLR-21: replica lookup during core reload

The selected Solr 8.11.4 check is `CoreContainer.reload(String, UUID)` at `CoreContainer.java:1765`: after obtaining the collection state, it looks up the reloaded core's `coreNodeName` and asserts `replica != null`. The bytecode at this source line contains the conditional jump and `AssertionError` throw. The oracle records that exact check and exact throw under the logical source `SOLR/RELOAD/c8n_1x1/shard1/core_node2`; a generic JUnit error or a nearby exception does not satisfy it.

The unchanged original embedded-cluster test is `org.apache.solr.cloud.api.collections.CollectionReloadTest#testReloadedLeaderStateAfterZkSessionLoss`. Its `@BeforeClass` fixture starts a one-node SolrCloud cluster. The method creates `c8n_1x1` with one shard and one replica, reloads the collection, waits for the core start time to increase, then expires the replica node's ZooKeeper session and waits for active registration. **The selected check executes during reload, before the explicit session expiry.** That limits what this test can say about the later recovery sequence.

The case uses a clean Solr worktree at source revision `e27f44e3d78dfcec230c97e0a1240e3751daeff9` on node2. The original JUnit ran and passed without an agent, then passed with a case-local ASM recorder in two repeated healthy seeds (`ran=1, ignored=0, failures=0` each). Both recorded one exact target guard and no target throw. The first instrumented setup attempt produced a JVM verifier error due to a fixed local-variable slot; it was excluded and the agent was corrected to derive the slot from the original method's bytecode data flow. It is not a test result.

The independent agent records exact SolrZkClient retry-callable operations and the original `CorePropertiesLocator.buildCoreDescriptor` → `Files.newInputStream(core.properties)` call. Both healthy traces have 95 identical exact I/O selectors before the target, including the same-core properties read. Selectors contain operation, bytecode caller site, logical collection/core source, ZooKeeper path or normalized core file, and hit ordinal. Jetty port and absolute temporary path remain physical evidence, not selector fields. The Java classpath excludes GraphChecker and static region skeletons. JaCoCo provides coverage feedback from original Solr/Lucene production classes; the three runtime-woven classes are excluded from that production count.

An independent calibration injected `IOException` at the exact same-core `core.properties` read. It applied once, and the original JUnit passed; the same thread reached the target guard afterward with a nonnull ACTIVE/NRT replica, and the target assertion did not throw. This calibration is counted once, separately from the resumable fault campaign. The campaign starts from two healthy seeds, mutates observed I/O fault sequences, and uses exact injection, post-fault target guard, target throw, production coverage, and semantic I/O family feedback. Its default budget is 80 trials and eight ordered faults. Progress and each trial's elapsed time are recorded under `independent/campaign/`, then mirrored into the shared 102-check table.

The target assertion is a candidate symptom, not automatic proof of a new bug. If it fires, the original collection state, core descriptor, node identity, JUnit postconditions, and repeated fault replay must be checked in source and traces. A negative result for this test covers its reload-before-session-expiry path and the observed I/O families only.

## Completed campaign and source review

The bounded campaign completed 80 fault trials in addition to the separate
calibration. All 81 injections matched their exact runtime selectors, all 81
reached the same reload target after the fault, and none executed the exact
`AssertionError` throw. Every faulted original JUnit passed. The 80 campaign
trials included 34 single-fault sequences and multi-fault sequences up to
five ordered faults, spread across 32 first-fault families. From the two
healthy seeds, the union of strict target-preserving trials added seven
original production methods and 35 branch outcomes; three runtime-woven
classes are excluded. The 46 semantic I/O families seen in the healthy runs
did not increase. The complete per-trial timing, coverage, and I/O audit are
in `independent/campaign/`.

The original production source first looks up the replica by the reloaded
core descriptor's `coreNodeName`, then asserts it is nonnull under
`docCollection != null`. The original JUnit invokes collection reload before
its explicit ZooKeeper session expiry; all observed target checks therefore
belong to that reload. This is a high quality, bounded negative result for
that path. It does not test a target check after the later session expiry.
