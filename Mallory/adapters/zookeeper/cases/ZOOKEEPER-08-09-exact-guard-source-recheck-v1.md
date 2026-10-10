# ZOOKEEPER-08/09: existing cluster-test mapping recheck

This is a source-only review of pinned ZooKeeper 3.8.7. No JUnit was run and no healthy exact-site witness is claimed. Both cases remain unrun under the existing-cluster-test rule.

## Pinned source

| File relative to ZooKeeper source root | SHA-256 |
| --- | --- |
| `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/LearnerSessionTracker.java` | `98f3708f1679964736af5c7ed840d8dd000b320471e04958303deea16a3a8731` |
| `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/FollowerZooKeeperServer.java` | `140d0720c0f5f6dbd01b3ec6904ce3d97c77bad941c4e9509b79d56978a41a43` |
| `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ObserverZooKeeperServer.java` | `60b184e0c3b496161a44abbb8f432b535df9937ae8e510049b21c8c690aff985` |
| `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java` | `4df96bf0d3e99ad184933e4483c555f8955e7205070d6604e4861e94e581fd7d` |
| `zookeeper-server/src/main/java/org/apache/zookeeper/server/PrepRequestProcessor.java` | `b3ba5e779f99cc972d5fcde6090c43814d1695405a1da9f108257baae24ddd5d` |
| `zookeeper-server/src/test/java/org/apache/zookeeper/test/ReadOnlyModeTest.java` | `14eac3d1debfb52d4e79d890c74265c50a12c860914e79bb2462d4e04ddfe57e` |
| `zookeeper-server/src/test/java/org/apache/zookeeper/test/SessionUpgradeTest.java` | `c1f72023862fd850dc0e4848e77a926e399ac5b62559535ebdbe269410bf7b75` |
| `zookeeper-server/src/test/java/org/apache/zookeeper/test/SessionTrackerCheckTest.java` | `6c1f6175a967cc2003873e5de49f562b6efd82cf923161d4abaab533074b2f1c` |

## Exact guards

ZOOKEEPER-08 selects `LearnerSessionTracker.checkSession(long,Object)` inner `isGlobalSession` guard (source lines 166–177; compiled `@173:branch:2`, throw `@174:throw:1`). A successful `localSessionTracker.checkSession` returns before that guard. The guard is evaluated only after `UnknownSessionException`. An unknown nonglobal session then takes the selected `SessionExpiredException` path; a known global session would be the nonthrowing inner-guard case.

ZOOKEEPER-09 selects `LearnerSessionTracker.setOwner(long,Object)` inner `isGlobalSession` guard (source lines 180–194; compiled `@190:branch:2`, throw `@191:throw:1`). A successful local `setOwner` returns first. The inner guard requires a caught local `SessionExpiredException`; it rethrows for a nonglobal ID.

## Existing test candidates

`ReadOnlyModeTest#testMultiTransaction` (lines 68–109) and `#testReadOnlyClient` (lines 115–159) are real quorum tests. They enable local sessions, then create a new read-only client after quorum loss. The read-only pipeline is `ReadOnlyRequestProcessor → PrepRequestProcessor → FinalRequestProcessor` (`ReadOnlyZooKeeperServer.java:65–70`). The preparer calls `sessionTracker.checkSession` for read operations (`PrepRequestProcessor.java:915–930`) and `zks.setOwner` for `createSession` (line 586). These are **method-level** routes, but the tests' newly created local sessions take the successful local-tracker return before either selected inner guard. The tests do not establish an unknown-yet-global session at that read-only peer.

`SessionUpgradeTest#testUpgradeWithEphemeralOnFollower` (lines 147–200) does upgrade a local session to global and reconnect to another follower. Its ordinary follower pipeline is `FollowerRequestProcessor → CommitProcessor → FinalRequestProcessor` (`FollowerZooKeeperServer.java:70–76`), not `PrepRequestProcessor`. The observer pipeline similarly lacks `PrepRequestProcessor` (`ObserverZooKeeperServer.java:88–95`). Thus its `exists` calls do not establish a source route through the selected `LearnerSessionTracker` inner guards. Its later reconnect of a closed session expects `SessionExpiredException` at client/session validation, not an exact selected-guard healthy execution.

`SessionTrackerCheckTest#testLearnerSessionTracker` directly constructs the tracker and exercises these exception paths; it does not start an ensemble, so it is outside the requested cluster-test workload class.

## Decision

There is no **mapped existing cluster JUnit with a source-supported, nonthrowing exact inner-guard hit** for either case in the reviewed candidates. Retain `no_mapped_cluster_test` / unrun for ZOOKEEPER-08 and -09; do not promote a method-level route or an expected exception as a healthy seed. This is a bounded source review, not a proof that no test anywhere in the suite could ever reach the guard. A future candidate must identify a cluster path carrying an unknown-to-local but known-global session ID into `PrepRequestProcessor`, then demonstrate the exact loaded-class check, named learner identity and injectable pretarget I/O door in a fresh healthy run.
