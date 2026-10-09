# ZOOKEEPER-09: existing cluster-test calibration

Source revision: Apache ZooKeeper 3.8.7, `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`.
Selected check: `LearnerSessionTracker.setOwner(long,Object)`, source lines
190-191. It requires `localSessionTracker.setOwner` to throw
`SessionExpiredException` for a missing or closing local session and the
session ID to be absent from the learner's global map. A valid local session
returns at line 184.

Unmodified three-peer `ReadOnlyModeTest.testSessionEstablishment` was run
with a case-local ZooKeeper copy and JaCoCo's ASM instrumentation on
`LearnerSessionTracker`. JUnit passed (1 test, 0 failures, 0 errors), but
`setOwner` was not entered: lines 181, 183-185, and 190-191 had no covered
instructions; line 190 had 0/2 covered branches. The test observes a
read-only connection and then restores the quorum before a write, but does
not put an absent/closing local session through this method.

`SessionUpgradeQuorumTest.testCloseSessionWhileUpgradeOnLearner` uses a
follower. `FollowerZooKeeperServer.setupRequestProcessors` uses
`FollowerRequestProcessor -> CommitProcessor`, whereas the read-only server
uses `ReadOnlyRequestProcessor -> PrepRequestProcessor -> FinalRequestProcessor`.
The `PrepRequestProcessor` create-session call at lines 585-586 performs
`trackSession` then `setOwner` synchronously, without an I/O operation between
them. A single exception at an observed I/O point in these tests therefore
does not supply the required missing-local state at `setOwner`. A separate
session closing race would be needed; target reach under the unchanged tests
remains unproved.

Raw evidence is in this case's `branch-calibration-evidence` directory;
the test reused one isolated source copy under `ZOOKEEPER-08/.calibration`:
`healthy09-jacoco.log` SHA-256
`4a19bd06d3d68029ce4665fe247a77c619d0f1a2f99aaf706cee63ee5bd8abf5`;
`healthy09.exec` SHA-256
`39aeed8a7d6e591e5224de260d55363add0463f55283b75bd890902121f2fbe1`.
The copied POM only adds the JaCoCo Java agent to Surefire; original test
and production source files are unchanged. `CoverageLines.java` in the
ZOOKEEPER-08 evidence directory generated this case's `coverage-lines.txt`.

Checklist status remains `no_cluster_test` until an existing unmodified
embedded-cluster test demonstrates the selected branch.
