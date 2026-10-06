# ZooKeeper 3.8.7: embedded JUnit inventory for checks 08 and 09

This map evaluates **unmodified source-tree tests** for the selected guards.
Neither selected site has an upstream cluster-test mapping in
`crashfuzz/examples/zookeeper_387/study_manifest.json` (`owner_status:
NO_CHECK`). Paths and line numbers below refer to
`/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7`.

| ID | Exact guard and state | Closest exact test | Best real embedded quorum tests | Does an unmodified real-quorum test reach selected **B2**? | Exception interpretation |
| --- | --- | --- | --- | --- | --- |
| ZOOKEEPER-08 | `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/LearnerSessionTracker.java:163-177`, `checkSession(long,Object)` B2/throw at `:174`: only after `localSessionTracker.checkSession` throws `UnknownSessionException`, throw if the same ID is also absent from learner `globalSessionsWithTimeouts` | `zookeeper-server/src/test/java/org/apache/zookeeper/test/SessionTrackerCheckTest.java:75-121`, `testLearnerSessionTracker`, constructs a tracker in isolation; its unknown ID intentionally triggers `SessionExpiredException` at `:82-87`, while a known global or local ID succeeds. **No quorum.** | `zookeeper-server/src/test/java/org/apache/zookeeper/test/ReadOnlyModeTest.java:114-155`, `testReadOnlyClient`: `QuorumUtil(1)` runs three peers, enables local sessions, loses quorum, connects a read-only client and reads a znode. `testMultiTransaction` at `:69-110` also reads in read-only mode. `SessionUpgradeTest.testLocalSessionsWithoutEphemeralOnFollower` at `zookeeper-server/src/test/java/org/apache/zookeeper/test/SessionUpgradeTest.java:67-143` runs five peers with local sessions and checks rejection of a local session on another peer. | **No source proof of B2 in these unmodified tests.** In read-only mode the real server has `LearnerSessionTracker` plus `ReadOnlyRequestProcessor -> PrepRequestProcessor -> FinalRequestProcessor` (`ReadOnlyZooKeeperServer.java:65-95`); a valid local-session read can call `checkSession` through `PrepRequestProcessor.java:915-929`, but the local lookup returns **before B2**. The session-upgrade test expects rejection on another peer but does not prove that that peer executes this exact learner B2; ordinary follower request processing does not use the read-only Prep chain. Runtime branch evidence would be required. | An unknown ID absent from both maps is supposed to get `SessionExpiredException`, as the exact unit test asserts. This alone is not a bug. |
| ZOOKEEPER-09 | Same file at `:180-194`, `setOwner(long,Object)` B2/rethrow at `:191`: only after the local tracker's `setOwner` throws `SessionExpiredException`, rethrow if ID is not known as global | No source-tree test found that directly calls `LearnerSessionTracker.setOwner`. `SessionTrackerCheckTest.testLearnerSessionTracker` tests only `checkSession`. | `ReadOnlyModeTest.testSessionEstablishment` at `:213-246` runs three peers, enables local sessions, creates a session on a read-only server, then restores quorum. `ReadOnlyModeTest.testReadOnlyClient` and `SessionUpgradeQuorumTest.testCloseSessionWhileUpgradeOnLearner` (`zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/SessionUpgradeQuorumTest.java:213-260`) are nearby lifecycle tests. | **No source proof of B2.** In the read-only server, a local `createSession` can pass the read-only processor (`ReadOnlyRequestProcessor.java:90-96`), and `PrepRequestProcessor.java:579-587` calls `trackSession` then `zks.setOwner`. With a live newly tracked session, local `setOwner` returns before learner B2. The tests do not assert a removal/closing race between these calls. | A missing/closing local session that is not global is supposed to retain `SessionExpiredException`. Fatal B2, if observed, needs lifecycle review; it is not automatically a coordination bug. |

## Disposition under the unit-test pivot

`no_cluster_test` is justified for **both 08 and 09** if that status means
"no unmodified, real embedded-quorum JUnit method demonstrated to execute the
selected B2 under the needed session state." It must **not** be read as
"unreachable in production." `ReadOnlyZooKeeperServer` has a plausible
server-side path to both methods, but the listed tests exercise normal local
session success and do not create the exact absent-local/absent-global state
at a request boundary. The clean next route would require a new or modified
JUnit test with a real read-only server, `localSessionsEnabled=true`, a
specific session ID, and server-side B2 trace, then coverage and I/O fault
evidence. Under the current unchanged-test rule, both checks stay excluded.

The old `LearnerSessionTrackerClient.java` campaign helper must not count as
cluster coverage: it constructed a new tracker in the **client JVM** and
called `commitSession` on its private map before the target. Its target hit
could not establish that a server fault influenced the checked state
(`.study-repairs/zk08_09-source-review.md`). No new embedded JUnit test or
fault trial has been run for either site in this pivot.
