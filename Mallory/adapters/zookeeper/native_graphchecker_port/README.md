# ZooKeeper protocol receipts for source-built GraphChecker

This isolated post-pass instruments ZooKeeper 3.8.7's existing class files after
the original GraphChecker REGION_STATE or concolic weave. It calls the original
`edu.uva.liftlab.graphchecker.runtime.MessageDoors` and `RowRuntime`; it does
not depend on Mallory's earlier custom graph runtime.

The seven Java sources in `src/main/java` are the required protocol weave,
trace bridges, JUnit runner, and session verifier. `source-provenance.json`
pins their bytes and records a Java 8 build check: all 11 resulting class
files matched the pinned protocol class tree byte for byte. The reference
class tree is a build output and is deliberately excluded from this source
directory.

`NativeZooKeeperProtocolWeaveMain <woven-class-tree> <dependency-classpath>
[client|quorum|all]` copies only the selected protocol classes through Soot and
replaces those classes in the supplied woven tree. The `quorum` mode selects
`Learner`, `LearnerHandler`, `Follower`, and `ObserverMaster`; `client` selects
`ClientCnxnSocketNIO` and `NIOServerCnxn`. The mode selects a transport family,
never an individual fault site. Each expected source anchor is checked exactly;
missing anchors abort the post-pass.

The two statically declared ZooKeeper handshake ports are FOLLOWERINFO or
OBSERVERINFO zxid
(`Learner.registerWithLeader` to `LearnerHandler.run`) and LEADERINFO zxid
(`LearnerHandler.run` to `Learner.registerWithLeader`). `writePacketNow` publishes
FOLLOWERINFO/OBSERVERINFO only on its normal return after a requested flush. The leader
publishes LEADERINFO only after the `bufferedOutput.flush()` following its
`writeRecord` succeeds. The receiver pairs an exact packet type and zxid with
the same directional socket and FIFO slot. The outbound carries the scope
captured at write preparation, so a separate synthetic flush root does not
replace the producer's causal context. A missing socket, owner, packet match,
or original actor registration produces a blocking gap; it never guesses a
cross-process edge. ACKEPOCH has no declared port in the current static map and
is not claimed as an instrumented wire edge.

The bridge accepts the protocol's `OBSERVERINFO` packet type at the same
learner-info anchors. An unchanged `ObserverLETest#testLEWithObserver` passed
under the combined engine. A diagnostic-only logging build observed two type-16
packets prepared and flushed by observer peers 4 and 5 and read by
`LearnerHandler`; its original session had eight typed SEND/RECV pairs and no
gaps. Another run observed six pairs because startup timing differed. These
are protocol observations, not an observer target-closure or campaign gate.

The original `QuorumRestartTest#testRollingRestart` passed unchanged after the
quorum post-pass with source-built original engine SHA-256
`0059dfd3a3f9bd5de1439929a8411bc7d666b3fab5b9fa945a2502dc8aad30aa`.
The source-built original session recorded 12 handshake SENDs and 12 matching
RECVs, including the restarted peer's epoch, with zero gaps. The full
`SessionReader` verdict is
`/dev/shm/mallory-native-zk07-engine0059-protocol-v1/session-reader-receipt-strict.json`.
The verifier also reads every schedule line strictly, since the original
`SessionReader.readSchedule` can return a prefix after an unreadable line.
This is protocol evidence only. The mapped concolic u51 target weave
currently fails closed at `ClientCnxnSocketNetty$1.operationComplete#u48`
because the planner's observed store does not match the concolic Soot body.
Consequently no target-closure claim or accepted campaign gate is published
from this pilot.
