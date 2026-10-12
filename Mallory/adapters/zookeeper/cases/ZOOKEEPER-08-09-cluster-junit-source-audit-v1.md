# ZOOKEEPER-08/09: existing cluster JUnit source audit

Scope: original-102 selected sites in ZooKeeper 3.8.7, considering **any
existing cluster-based JUnit**, regardless of its harness class. This is a
source-only, no-JVM audit. It does not establish that the sites are unreachable
in all tests. No healthy exact-site trace, selected throw, or pretarget I/O
door has been observed for either case.

Source root: `/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7`, commit
`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`. The original inventory is
`Mallory/cases/inventory.json`, SHA-256
`fcc824e5142cede4effadee9f46e64c3132be177f353e4cc543d46cb5c1b5b47`.
The currently mapped compiled `LearnerSessionTracker.class` SHA-256 is
`b36b481b6dd38608369706eb1ffcf27c1a99b6374f27e1e6eb07749ea37af965`.
The target source SHA-256 is
`98f3708f1679964736af5c7ed840d8dd000b320471e04958303deea16a3a8731`.

## Exact guards

| Case | Compiled check / throw | Necessary nonthrowing B2 state |
| --- | --- | --- |
| 08 | `LearnerSessionTracker#checkSession(JLjava/lang/Object;)V@173:branch:2` / `@174:throw:1` | `localSessionTracker.checkSession` throws `UnknownSessionException`, then `isGlobalSession(sessionId)` is true. A valid local session returns at line 167 before B2. An unknown nonglobal ID takes the selected throw. |
| 09 | `LearnerSessionTracker#setOwner(JLjava/lang/Object;)V@190:branch:2` / `@191:throw:1` | `localSessionTracker.setOwner` throws `SessionExpiredException`, then `isGlobalSession(sessionId)` is true. A fresh local session returns at line 184 before B2. An absent or closing nonglobal ID takes the selected throw. |

`SessionTrackerImpl.java:308-333` supplies the local failure conditions: an
unknown ID makes `checkSession` throw `UnknownSessionException`, while absent
or closing state makes `setOwner` throw `SessionExpiredException`. The global
lookup is `LearnerSessionTracker.java:96-97`, backed by
`globalSessionsWithTimeouts`. The source does admit a nonthrowing B2 for a
known global session absent from the local tracker. The missing evidence is a
cluster JUnit that drives an actual learner request through that fallback.

## Existing cluster tests inspected

* `ReadOnlyModeTest#testMultiTransaction` (lines 68-109) and
  `#testReadOnlyClient` (115-159) create a real quorum, enable local sessions,
  enter read-only mode, and issue reads. `ReadOnlyZooKeeperServer.java:65-70`
  installs `ReadOnlyRequestProcessor -> PrepRequestProcessor ->
  FinalRequestProcessor`; `PrepRequestProcessor.java:928` calls `checkSession`
  on reads. Their new local clients normally pass the local tracker and return
  before ZK08 B2. `ZooKeeperServer.java:1010-1023` creates a session before
  submitting `createSession`; `PrepRequestProcessor.java:586` then calls
  `setOwner`. The newly created local session normally returns before ZK09 B2.
  These are method mappings, not exact-guard healthy witnesses.
* `ReadOnlyModeTest#testGlobalSessionInRO` (247-280) starts with a global
  session and removes quorum. `ReadOnlyZooKeeperServer.java:121-127` rejects
  its global renewal in `validateSession`, before read or createSession request
  processing. Its later new local session is not a global fallback.
* `SessionUpgradeTest#testUpgradeWithEphemeralOnFollower` is a real five-peer
  test that upgrades a local session and reconnects it on another follower.
  Ordinary `FollowerZooKeeperServer.java:70-77` and
  `ObserverZooKeeperServer.java:88-96` install follower/observer processors,
  not `PrepRequestProcessor`, so this does not source-map a client read or
  createSession to either selected learner B2. The other-peer rejection in
  `#testLocalSessionsWithoutEphemeralOnFollower` is a revalidation case, not
  proof of either target occurrence.
* `SessionTrackerCheckTest#testLearnerSessionTracker` directly constructs a
  tracker and evaluates ZK08 B2 with an unknown and a known global ID, but
  starts no cluster. It does not exercise a physical pretarget I/O door.
  Repository test-source search found no direct cluster-test call to
  `LearnerSessionTracker.setOwner`.

The `ReadOnlyModeTest.java` source SHA-256 is
`14eac3d1debfb52d4e79d890c74265c50a12c860914e79bb2462d4e04ddfe57e`;
`SessionUpgradeTest.java` is
`c1f72023862fd850dc0e4848e77a926e399ac5b62559535ebdbe269410bf7b75`;
`SessionTrackerCheckTest.java` is
`6c1f6175a967cc2003873e5de49f562b6efd82cf923161d4abaab533074b2f1c`.

## Dispatch decision

Keep both cases at **source gap / no exact-site healthy admission**. Do not
promote a passing method-only `ReadOnlyModeTest` run, or a direct tracker unit
test, to a fault campaign. Reopen either case when an existing cluster JUnit
has a named learner `TARGET_CHECK` at the exact B2 with no selected throw and
an observed, time-ordered pretarget physical I/O door in that occurrence's
closure. A source path to the method alone does not satisfy this gate.
