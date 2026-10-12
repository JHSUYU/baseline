# ZooKeeper workload review

## ZOOKEEPER-02 and ZOOKEEPER-03

The checklist maps both checks to
`org.apache.zookeeper.test.QuorumTest#testSessionMoved`. That test deliberately
reuses one session on a different peer and then sends a request through the
old connection. It expects `ConnectionLossException` on the old client. A
server-side `SessionMovedException` at `SessionTrackerImpl.checkSession` is
therefore an expected path of the healthy workload. A target throw from this
test is not evidence of a fault-induced bug for ZOOKEEPER-02.

The ZOOKEEPER-03 target is `SessionTrackerImpl.setOwner`, where a missing or
closing session throws `SessionExpiredException`. The same test may invoke
this path as part of deliberately replacing an owner. Its suitability has not
yet been established by an exact healthy target/throw catalog.

`QuorumTest#testMultiToFollower` is a candidate replacement for ZOOKEEPER-02:
its `@BeforeEach` starts the five-peer `QuorumBase` fixture, then the test
creates a separate three-peer `QuorumUtil(1)` ensemble, submits a
multi-operation through a follower, reads the three created nodes, and closes
the client without deliberately moving the session. The two ensembles reuse
peer IDs 1–3, so a runtime node identity also needs the peer lifecycle epoch.
`SessionUpgradeQuorumTest#testCloseSessionWhileUpgradeOnLeader`
has already reached line 323 in an instrumented healthy three-peer run without
a target exception, but it did not reach the line 325 owner-mismatch comparison.

No ZOOKEEPER-02 or ZOOKEEPER-03 campaign may count as a completed check until
its own healthy run and exact target-site catalog are validated.

The alternate `QuorumTest#testMultiToFollower` has now passed with the
five-peer fixture and separate three-peer test ensemble. Its exact catalog and raw events are archived under
`data/mallory/calibration/ZOOKEEPER-02-03-alternate/healthy`. The owner
comparison at `checkSession` line 325 was observed three times, and both
branches of the `setOwner` line 333 guard were observed once. Each target
event had logical node `zk2`; neither target throw occurred. A second
healthy run on the port-isolated lane2 confirmed these observations with
the ordinal-capable agent and archived the exact JVM properties, port log,
source/class bytes, and raw events separately for ZOOKEEPER-02 and -03.
The first full ZOOKEEPER-02 campaign remains provenance-limited: its target
region used the tracker receiver's default epoch 0, while task handoff and
the target check used the second ensemble's actual epoch 1. A separate
versioned overlay registers the tracker receiver with its peer epoch and
scopes parsed client requests before queuing them, so a new healthy run must
show an actual client-I/O-to-target path before another full campaign.

The corrected ZOOKEEPER-02 request-path overlay has since proved a unique
client-request door, two task handoffs, a physical `REQUEST` quorum-packet
send/receive, and the leader task path into the exact check on `zk2` epoch 1.
Its 80-fault campaign completed in 1909.914 seconds: all 80 faults were
strictly applied, 74 runs retained the check, and none reached the selected
throw. The independent 81-trial archive audit passed. Immutable result,
archive, source/class bytes, and audit are under
`data/mallory/cases/ZOOKEEPER-02`.

ZOOKEEPER-03's first request-path healthy run reached both `setOwner` guard
branches during *session creation*, before an ordinary client-operation
request door existed. A separate connect-path overlay now scopes the decoded
`ConnectRequest` to `createSession` and records
`zookeeper.client.connect.read`. Its healthy test passed in 21.831 seconds,
reached both branches on `zk2` epoch 1 with no throw, and proved an observed
connect door → task → exact `REQUEST` packet RPC → leader task → target path.
The 8-fault pilot applied every fault, retained the target in every trial,
and passed the independent 9-trial causal audit. The separate pinned full
campaign completed 80 faults in 2371.507 seconds: 75 strict injections, 69
target-retained strict trials, and zero selected throws. Its independent
81-trial audit passed with 29 healthy observed edges and 21 named pretarget
doors on observed paths. The complete raw archive and unchanged result are
under `data/mallory/cases/ZOOKEEPER-03`.

## ZOOKEEPER-04

The unmodified three-peer `ConnectionMetricsTest#testRevalidateCount`
passed in 38.153 seconds. The patched compiled `ZooKeeperServer` places the
selected `processConnectRequest` check at line 1434 and its throw at line
1444. The check ran once for the initial session on `zk1` and once for the
same client's reconnect on `zk2`; neither threw. Each exact occurrence had
one earlier `zookeeper.client.connect.read` door with the same decoded
connect correlation. The reconnect occurrence on `zk2` is the relevant one
for this test's session revalidation. Its door and target share a region, so
the current graph reports no nonempty observed path. The calibration is
archived at `data/mallory/calibration/ZOOKEEPER-04/reconnect-healthy-v1`
with manifest SHA-256
`f9d92b9651c55867e2b847a39345f867afb5b8ee79b575a2b03ae94c251464fc`.
It has not been promoted to a fault campaign.

The fresh opt-in core healthy seed is at
`data/mallory/calibration_core5a/ZOOKEEPER-04`. Its independent offline audit
passed with one `observed_local_timeline` proof: the decoded connect-read
door at event 635 precedes the exact check at event 641 in the same `zk2`,
epoch-0, `processConnectRequest` occurrence. Source line 1434 compares the
`ConnectRequest`'s `lastZxidSeen` with the server data tree's last zxid;
the read door is on that decoded request path. This establishes temporal
eligibility within a named occurrence, not an observed graph edge or an
independent value-flow proof. The fresh run also verified the exact loaded
class SHA and passing JUnit result.

The bounded opt-in pilot at `data/mallory/pilot_core5a/ZOOKEEPER-04`
completed six fault trials in 268.021 seconds. All six faults had exact named
match/application receipts, and the selected check appeared later in each
run. No selected target throw occurred. The subsequent strict actor audit
found that none of those later checks was in the injected fault's exact
node, epoch, and occurrence or connected by an observed causal path. The
versioned receipt at `data/mallory/admissions/ZOOKEEPER-04-5a-actor-retention-v1.json`
supersedes the earlier full-admission recommendation. This pilot does not
qualify for a full campaign; its raw traces remain preserved.

An isolated v2 healthy run at
`data/mallory/calibration_fa5f_lane2/ZOOKEEPER-04-readbool-v2` recorded the
exact `BinaryInputArchive.readBool("readOnly")` IOException door at patched
line 1420 immediately before the selected guard in the same named `zk2`
epoch-0 thread and connect occurrence (events 195→196). The original
three-peer JUnit passed in 29.414 seconds; loaded class SHA-256 was
`76cc1c01d29c85231d204c6ac302beaab64512b60576494484f78e542ebf0e0b`.
The fa5f audit passed with `observed_local_timeline` evidence, and the
independent exact-door attestation receipt SHA-256 is
`228567b08e1623fa1fef0514ddf3371b9012b1fd6e21e0ecf9619f6e8fa0726e`.

The directed v2 pilot at
`data/mallory/pilot_fa5f_lane2/ZOOKEEPER-04-readbool-v2` exhausted its two
eligible single-fault plans in 89.353 seconds. Both faults were precisely
applied and their JUnit runs passed. The `readBool` trial had
`FAULT_APPLIED` event 205 followed by the exact guard event 206 in the same
`zk2`, epoch-0, thread-142, connect occurrence; it did not throw the selected
exception. The separate `connect.read` trial lost its affected occurrence.
The independent postfault audit proves one of two exact affected-actor
continuations. Result/audit/postfault receipt SHA-256 values are respectively
`7f432e287a7530939917cd2c464e59b3e9aefaaab15123ad8a2cebd05042d49b`,
`a0c02c3a3e2fe11cdd2a2d6ec93f4b9a3a8104457ed1eb3dcc25ed23123562ff`,
and `bfd3efc77517988b02d1ca238c86d10f28ef326555462125c17499f30deb7e47`.

The source locally catches this `IOException` and leaves `readOnly=false`;
the selected guard compares the independent `connReq.lastZxidSeen` with
`zkDb.dataTree.lastProcessedZxid`. The chosen test creates a session,
disconnects one follower and reconnects to another without any client write
before the guard (`ConnectionMetricsTest.java:53-85`). This exact fault
exercises the check but does not change either compared zxid in this test.
More repetitions of these two plans would not support a new bug claim.

A source search found the existing three-peer
`WatchEventWhenAutoResetTest#testNodeDataChanged` as a stronger healthy
workload. It creates a znode through client 1, shuts peer 1 down, updates
that znode through client 2, restarts peer 1, and waits for client 1 to
reconnect (`WatchEventWhenAutoResetTest.java:101-106,128-137`). The pinned
healthy run at
`data/mallory/calibration_fa5f_lane2/ZOOKEEPER-04-write-reconnect-v1`
passed JUnit 1/1 in 19.935 seconds. The exact nonthrowing guard ran on
`zk1` before restart (epoch 0, event 73) and after restart (epoch 1,
event 290); the latter had the exact `readBool` door at event 289 in the
same thread and connect occurrence. The fa5f audit passed with four
`observed_local_timeline` doors and zero observed graph-path doors. The
loaded target class SHA matched the pinned compiled class. The independent
healthy receipt at
`data/mallory/admissions/ZOOKEEPER-04-fa5f-write-reconnect-v1-healthy.json`
has SHA-256
`99baa53c4815521471c9caba444bdd9c0d58bba7a0ab8b550308abcb935657b7`.
This verifies a write-before-reconnect workload and exact named target
reach. The write during downtime is performed by client 2, whereas the
reconnecting client 1 sends the zxid from its own earlier create response
(`ClientCnxn.java:964,1019`). Thus, dropping only client 2's update would
not make the restarted peer's zxid lower than client 1's last-seen zxid.
`Learner.syncWithLeader` can start serving before applying some queued
commits (`Learner.java:791,812-820`), a plausible state-changing I/O
surface, but this existing test has no demonstrated target-preserving
exception door that crosses the selected comparison. The bounded
source-gap receipt is
`data/mallory/admissions/ZOOKEEPER-04-fa5f-write-reconnect-v1-fault-model-gap.json`.
No fault campaign or new bug is claimed from this seed.

## ZOOKEEPER-05, ZOOKEEPER-06, and ZOOKEEPER-07

The existing three-peer `QuorumRestartTest#testRollingRestart` passed in
three independent healthy runs (27.049, 28.123, and 29.750 seconds). The
exact nonthrowing guards ran 6, 4, and 2 times respectively on named peers;
none of the selected throws occurred. Separate raw traces, JUnit reports,
class/source/test/agent copies, and SHA manifests are under
`data/mallory/calibration/ZOOKEEPER-{05,06,07}/rolling-healthy-v1`.

ZOOKEEPER-05 and ZOOKEEPER-07 each have observed quorum-packet RPC edges
from a named pretarget I/O door into a target occurrence. For example, in
ZOOKEEPER-07 the leader's `zookeeper.quorum.archive.writeRecord` door at
event 306 precedes a `LEADERINFO` send at 307, uniquely paired with the
learner receive at 309, followed by the selected guard at 314 on `zk1`
epoch 1. ZOOKEEPER-05 has a corresponding `LEADERINFO` receive into its
follower guard. The standalone audits report 78 and 72 pretarget doors in
the respective observed graph closures.

ZOOKEEPER-05 subsequently passed its fresh frozen-core healthy seed in
26.248 seconds: exact named target and class hash, passing JUnit, 86 doors
with observed paths, and 48 observed edges. Its six-fault bounded pilot
finished in 189.647 seconds with six exact applications and no selected
throw. The original controller counted six later target checks; the strict
fault-to-target audit found zero checks in the fault's exact occurrence and
zero causally connected paths. Two apparent RPC paths began at an unscoped
node root, which can contain unrelated work and is rejected as a fault
origin. The versioned result is
`data/mallory/admissions/ZOOKEEPER-05-5820-actor-retention-v2.json`;
the earlier v1 path interpretation remains preserved as superseded
evidence. ZOOKEEPER-05 is held from a full campaign.

A fresh source review of the same existing JUnit did not justify another
healthy or pilot replay. `Follower.followLeader` compares the proposed
epoch immediately after `registerWithLeader`; an injected packet I/O
exception aborts the same attempt before that guard. The one narrow
startup recovery exception is a missing `acceptedEpoch` file, but its
fallback uses the last processed transaction's epoch
(`QuorumPeer.java:1180-1191`), which cannot raise the accepted-epoch
operand needed by this selected throw in a valid persisted state. The
SHA-bound bounded gap is at
`data/mallory/admissions/ZOOKEEPER-05-5820-fault-model-gap-v2.json`.
Its six trial entries bind the exact applied-fault event to each raw trace;
the source-only v1 review is retained separately.
It keeps the previous six-fault negative evidence and leaves the check
incomplete for this fault model.

ZOOKEEPER-07 also passed a fresh frozen-core healthy seed in 24.218
seconds, with the exact nonthrowing guard on named `zk1` and `zk2`, matching
loaded class hash, and a passing JUnit. Its offline audit verified 75
pretarget doors on observed paths and 48 observed edges. A separate bounded
fault pilot then finished in 190.215 seconds with six exact applications and
no selected throw. All six later checks counted by the original controller
belonged to other target occurrences. Every injected fault originated in an
unscoped node root; the strict actor/path audit found no qualified postfault
target path. Its receipt is
`data/mallory/admissions/ZOOKEEPER-07-5820-actor-retention-v1.json`.
ZOOKEEPER-07 is held from a full campaign pending a bounded retry-handoff
hook and a fresh healthy/fault audit.

ZOOKEEPER-06 reached `Leader.waitForEpochAck` without a graph path: the
`ACKEPOCH` packet is read in `LearnerHandler`, then passed as a `StateSummary`
to `Leader.waitForEpochAck`, but the initial adapter retained receive context
only for `REQUEST` packets. Its closure was singleton. A separate versioned
overlay now compiles an exact packet-object `ACKEPOCH` context handoff, with
source and class hashes in the ackepoch overlay receipt. Source compilation
alone did not establish a fault result; a separate healthy run was required
to prove the paired packet and target path.

A fresh strict-core healthy run now supplies that proof at
`data/mallory/calibration_fa5f_lane2/ZOOKEEPER-06-ackepoch-v2`. The existing
three-peer rolling-restart JUnit passed in 22.186 seconds, and the loaded
`Leader.class` SHA-256 matched
`2997636daa456c16bbe1168a22da699bef636e27ab6bbd0a224ea0c6718f2256`.
The offline audit passed with six event-time observed-path doors and coarse
roots rejected. An independent packet attestor verified one exact follower
`ACKEPOCH` write door/SEND (events 25/26), leader RECV (27),
`zookeeper.leader.ackepoch` region (28), and selected nonthrowing guard (32),
using the same physical packet correlation and named `zk2` to `zk3` actors.
The result, audit, and attestation receipt SHA-256 values are respectively
`66258249c2eb35bf39113e884bb4d836b42e123d382f9115880d28686be58bf2`,
`e77e674be63513f7b393da85146398be732981bb049b0859bd8e121b751b5807`,
and `36ea3f5fce09bbbf3bf8abac606159693e4efcbf0cdc194eb302d5e1ec518542`.
This proves healthy packet causality only; a bounded fault pilot must still
prove that an applied fault leads to a later target check on the affected
path.

The subsequent six-fault pilot at
`data/mallory/pilot_fa5f_lane2/ZOOKEEPER-06-ackepoch-v2` completed in
168.8 seconds. All six faults matched and were applied, and the controller
observed a later target check in each trial; none threw the selected
exception. The independent fa5f audit passed raw integrity and healthy
guidance, but the strict postfault event-time audit found **zero** same
occurrence or observed-path continuations from the applied fault to a later
target check. Later checks belonged to other ACKEPOCH paths or peer roles.
The pilot therefore is not admitted to a full campaign. The result, offline
audit, and postfault audit SHA-256 values are respectively
`5c48db1494633f9b660fe8f5ac88b26a3b4fc61f03f9927fb7964028325579f2`,
`bba1df8f371801a1c5983c74341f303c6452d39e6963935c751da28b19797d24`,
and `6ff6647643ea2bf25878c1a49f8f63407d5b15e7f6eb3dff7bb728856e4e5192`.

## ZOOKEEPER-10

The existing three-peer `ObserverMasterTest#testObserver` parameterized test
is a shorter healthy workload than `testInOrderCommits` (which sends 10,001
asynchronous writes from each of two clients). A pinned node0 run of both
unmodified parameter values passed 2/2 JUnit cases in 38.693 seconds. The
exact `ObserverMaster.removeProposedPacket(long)` guard was reached seven
times on named `zk1`, across epochs 0 and 1, with no selected throw. Its
loaded class SHA matched the compiled overlay. The strict offline audit
verified 13 pretarget I/O doors with observed packet/region paths, including
quorum sender event 94, follower receive 95, `Follower.processPacket` 96,
`ObserverMaster.proposalCommitted` 97, `removeProposedPacket` 98, and selected
check 99. The raw campaign is at
`data/mallory/calibration_fa5f_node0/ZOOKEEPER-10-observer-v1`; the
SHA-bound healthy receipt is
`data/mallory/admissions/ZOOKEEPER-10-fa5f-observer-v1-healthy.json`.

All 13 doors in the selected closure are quorum archive `readRecord` or
`writeRecord` IOException sites. A read failure exits `Follower.followLeader`
through its outer catch, closes the socket, and stops that ObserverMaster.
A write failure closes the `LearnerHandler` socket and breaks its sender loop.
The target queue is updated in `proposalReceived` and inspected immediately
by `proposalCommitted`; this I/O fault model has no demonstrated way to skip
one queue update while retaining the same target occurrence. The bounded
source gap is recorded at
`data/mallory/admissions/ZOOKEEPER-10-fa5f-observer-v1-fault-model-gap.json`.
No fault pilot or full campaign was admitted, and no bug is claimed.

## ZOOKEEPER-11 and ZOOKEEPER-12

The unmodified three-peer
`CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile`
passed in two separate, pinned healthy runs on the port-isolated ZooKeeper
lane. ZOOKEEPER-11 took 39.066 seconds and observed the exact
`QuorumPeer.loadDataBase` line 1169 guard once on `zk0` epoch 2, with no line
1175 throw. ZOOKEEPER-12 took 37.142 seconds and observed the exact line 1193
guard nine times across `zk0`, `zk1`, and `zk2`, with no line 1197 throw.
Both compiled-class hashes match the archived overlay receipt. Separate raw
events, catalogs, JUnit reports, class/source/test/agent copies, and SHA
manifests are under
`data/mallory/calibration/ZOOKEEPER-11/epoch-file-healthy-v1`
and `data/mallory/calibration/ZOOKEEPER-12/epoch-file-healthy-v1`.

Auto I/O instrumentation observed file reads before the checks within the
same named `loadDataBase` region. For ZOOKEEPER-11, the `currentEpoch` read at
event 4618 preceded the selected check at event 4630 in the same `zk0`
epoch-2 occurrence. For ZOOKEEPER-12, later peer epochs similarly read
`currentEpoch` and `acceptedEpoch` before the comparison. The current
occurrence graph has no nonempty observed edge from those same-region doors
to the target occurrence, so both offline attestations report zero
observed-path doors and a singleton closure. These are valid target-reach
calibrations but not yet closure-qualified fault campaigns. No fault trials
had been launched for either check at that stage.

Fresh opt-in core healthy seeds now reside at
`data/mallory/calibration_core5a/ZOOKEEPER-11` and
`data/mallory/calibration_core5a/ZOOKEEPER-12`. Both passed the independent
offline causal audit with `observed_local_timeline` evidence and no observed
graph-path door. ZOOKEEPER-11's `readLongFromFile` door at event 4455 precedes
its line-1169 check at event 4460 in the same `zk0`, epoch-2 occurrence.
ZOOKEEPER-12 has five such doors on `zk0` epochs 1 and 2; an epoch-1 pair is
events 2407/2413 before the line-1193 check at event 2418. In
`QuorumPeer.loadDataBase`, `readLongFromFile(CURRENT_EPOCH_FILENAME)` assigns
`currentEpoch` before the first guard, and
`readLongFromFile(ACCEPTED_EPOCH_FILENAME)` assigns `acceptedEpoch` before
the second guard. The existing cluster test rewrites `currentEpoch` and
`currentEpoch.tmp` before restart. These are source-relevant file reads;
the generic audit claims only exact same-occurrence temporal order. Both
fresh runs verified the loaded class SHA, named target and passing JUnit.

The bounded ZOOKEEPER-11 pilot at
`data/mallory/pilot_core5a/ZOOKEEPER-11` completed six fault trials in
350.831 seconds: five exact named injections, three followed by a selected
check somewhere in the run, and no selected throw. The directly selected
local-timeline file-read fault prevented the guard from running. A subsequent
strict actor audit found no postfault selected check in the injected fault's
exact node, epoch, and occurrence or connected by an observed causal path.
The versioned receipt at `data/mallory/admissions/ZOOKEEPER-11-5a-actor-retention-v1.json`
supersedes the earlier full-admission recommendation. This pilot does not
qualify for a full campaign; its raw traces remain preserved.

The bounded ZOOKEEPER-12 pilot at
`data/mallory/pilot_core5a/ZOOKEEPER-12` completed six fault trials in
590.566 seconds. All six faults had exact named application receipts; the
selected check appeared later in one trial, and no selected throw occurred.
The independent seven-trial offline audit passed its original gate, but the
strict actor audit found zero later checks in the fault's exact node, epoch,
and occurrence and zero observed fault-to-check paths. Its versioned receipt
at `data/mallory/admissions/ZOOKEEPER-12-5a-actor-retention-v1.json` records
the raw result and audit hashes. The pilot does not qualify for a full
campaign; its raw traces remain preserved.

## ZOOKEEPER-13

The selected `ReadOnlyModeTest#testGlobalSessionInRO` deliberately creates a
global session, removes the quorum, and expects reconnection in read-only mode
to fail. `ReadOnlyZooKeeperServer.validateSession` rejects exactly that global
session with `CloseRequestException`, so a healthy target throw from this test
would be expected behavior.

`ReadOnlyModeTest#testConnectionEvents` is the first alternate three-peer
candidate for a direct runtime check. Source review makes target reach
unlikely: after quorum loss it constructs a *new* `ZooKeeper` client, so the
connect request normally has session ID zero. `ZooKeeperServer.processConnectRequest`
calls `validateSession` only for a nonzero session ID; a new session instead
calls `createSession`. `testReadOnlyClient` also constructs a new client after
closing the old one, and `testSessionEstablishment` constructs its client
after quorum loss. None is a validated ZOOKEEPER-13 seed until an exact target
catalog, named node, and nonthrowing healthy outcome are observed in a real
run. If all miss the target, this check has no suitable existing cluster test.

The actual three-selector review corrected that source-only prediction in one
respect: `testConnectionEvents` can sometimes reconnect its still-live *old*
client after quorum loss. Its first healthy run reached the nonthrowing guard
on `zk1` through a uniquely correlated `zookeeper.client.connect.read` door
and observed `region_parent` edge. The original test reached the selected
throw 11 times, all expected by its refusal scenario; `testReadOnlyClient`
missed the guard. The first 8-fault pilot had a valid healthy closure and seven
effective injections, but no fault retained the target. An independently
launched full campaign stopped at its healthy seed because the same unmodified
`testConnectionEvents` JUnit passed without reaching the guard. Three more
independent starts yielded one visit and two misses: three visits in six starts
overall. The exact source/class/agent hashes and raw JUnit traces are preserved
under `data/mallory/calibration/ZOOKEEPER-13/`; the versioned
`stability-assessment.json` records each result. Under the existing cluster-test
restriction, ZOOKEEPER-13 has no **stable, demonstrated** nonthrowing workload.
No fault-campaign completion or new bug is claimed for this check.
