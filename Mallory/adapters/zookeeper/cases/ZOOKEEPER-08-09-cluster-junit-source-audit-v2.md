# ZOOKEEPER-08/09: cluster JUnit source audit receipt

Scope: original-102 sites in ZooKeeper 3.8.7 at source commit
`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`. This is a read-only
source inventory audit; no JVM run or healthy exact-site trace was obtained.

## Selected sites and required state

| Case | Exact selected check and throw | Nonthrowing branch condition |
| --- | --- | --- |
| ZOOKEEPER-08 | `org.apache.zookeeper.server.quorum.LearnerSessionTracker#checkSession(JLjava/lang/Object;)V@173:branch:2`; selected throw `@174:throw:1` | The local tracker throws `UnknownSessionException`, and `globalSessionsWithTimeouts` contains the same ID. |
| ZOOKEEPER-09 | `org.apache.zookeeper.server.quorum.LearnerSessionTracker#setOwner(JLjava/lang/Object;)V@190:branch:2`; selected throw `@191:throw:1` | The local tracker throws `SessionExpiredException`, and `globalSessionsWithTimeouts` contains the same ID. |

`LearnerSessionTracker.java:163-194` has the two catch and fallback guards;
`:96-97` defines the global lookup. `SessionTrackerImpl.java:308-333` shows
that an unknown ID misses `checkSession`, and an absent or closing ID fails
`setOwner`. A valid local session returns before either selected guard.

## Existing JUnit candidates

* `org.apache.zookeeper.test.SessionUpgradeTest#testUpgradeWithEphemeralOnFollower`
  creates a global session on a five-peer quorum and reconnects through a
  different follower (`SessionUpgradeTest.java:156-188`).
  `org.apache.zookeeper.test.DuplicateLocalSessionUpgradeTest#testLocalSessionUpgradeOnFollower`
  similarly upgrades a local session (`DuplicateLocalSessionUpgradeTest.java:75-109`).
  The follower request chain is `FollowerRequestProcessor -> CommitProcessor ->
  FinalRequestProcessor` (`FollowerZooKeeperServer.java:70-77`); the observer
  chain also omits `PrepRequestProcessor` (`ObserverZooKeeperServer.java:88-96`).
  Neither test source maps an ordinary client read or create-session request
  to the selected learner `checkSession` or `setOwner` guard.
* `org.apache.zookeeper.test.ReadOnlyModeTest#testReadOnlyClient` and
  `#testMultiTransaction` use local sessions and issue reads after quorum
  loss (`ReadOnlyModeTest.java:71-106,115-159`). Read-only servers do run
  `PrepRequestProcessor` (`ReadOnlyZooKeeperServer.java:65-70`), whose read
  path calls `sessionTracker.checkSession` (`PrepRequestProcessor.java:911-929`).
  Their new local clients return at `LearnerSessionTracker.java:166-167`,
  before the selected ZK08 fallback.
* `org.apache.zookeeper.test.ReadOnlyModeTest#testGlobalSessionInRO` creates
  a global session, loses quorum, and tries renewal (`ReadOnlyModeTest.java:247-280`).
  `ReadOnlyZooKeeperServer.java:121-127` rejects a global renewal during
  connection validation, before a read can reach ZK08.
* Read-only local `createSession` does **not** reach ZK09 through
  `PrepRequestProcessor`: `ReadOnlyZooKeeperServer.java:101-107` flags it
  local; `PrepRequestProcessor.java:903-909` skips `pRequest2Txn` for local
  sessions; the `setOwner` call is only in that skipped transaction path at
  `PrepRequestProcessor.java:579-586`. `ReadOnlyRequestProcessor.java:91-96`
  rejects nonlocal create-session requests. This corrects the earlier v1
  audit's method-level implication that ordinary read-only local session
  creation calls `setOwner`.
* `org.apache.zookeeper.test.SessionTrackerCheckTest#testLearnerSessionTracker`
  directly calls the tracker with unknown and global IDs
  (`SessionTrackerCheckTest.java:74-110`), so it can exercise ZK08's fallback
  in isolation. It starts no cluster and supplies no physical pretarget I/O
  door. Test-source search found no direct cluster JUnit call to
  `LearnerSessionTracker.setOwner`.

## Admission

No suitable **existing cluster-based JUnit selector** is source-backed for
either selected guard. The source admits a nonthrowing global fallback, but
the inspected cluster workloads do not naturally drive it through the learner
request path. Keep both as `no_cluster_test` / source gap pending a healthy
exact-site occurrence with a pretarget physical I/O door. A method-level
test mapping alone does not establish that occurrence.
