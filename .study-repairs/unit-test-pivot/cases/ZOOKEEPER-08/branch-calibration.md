# ZOOKEEPER-08: existing cluster-test calibration

Source revision: Apache ZooKeeper 3.8.7, `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`.
Selected check: `LearnerSessionTracker.checkSession(long,Object)`, source lines
173-174. The throw requires `localSessionTracker.checkSession` to raise
`UnknownSessionException` and the session ID to be absent from
`globalSessionsWithTimeouts`. A valid local session returns at line 167.

Unmodified `ReadOnlyModeTest.testReadOnlyClient` was run in its original
three-peer embedded `QuorumUtil(1)` setup with a case-local copy of the
ZooKeeper source and JaCoCo's ASM bytecode instrumentation restricted to
`LearnerSessionTracker`. JUnit passed (1 test, 0 failures, 0 errors).
The method entered: lines 164 and 166-167 executed. The selected condition
at line 173 had 0/2 covered branches, and throw line 174 had 0/4 covered
instructions. Thus this cluster test exercises the method, but it has not
demonstrated a visit to the selected check under the required session state.

An injected socket I/O exception can close the connection without removing
the session (`NIOServerCnxn.close`, lines 595-622). The test has one read
before its explicit `zk.close()` and no later request on that local session.
The exception therefore does not itself establish the missing-local plus
absent-global state at a subsequent request. A separate queued-request or
expiration race would be needed; this exact branch remains unproved for the
existing test. This is an eligibility finding, not an impossibility claim
about ZooKeeper in general.

Raw local evidence (ignored scratch, no production source modifications):
`.calibration/healthy08-jacoco.log` SHA-256
`8d77426c76bc51af80d6af13cb07e46dc6fca7f158797a44193039dcece1b1c9`;
`.calibration/healthy08.exec` SHA-256
`e5c96c830fb8235c8cfabafbac7bb8df0888f20b8d3f5c9ed1fefc2a93a03d4e`.
The copied POM only adds the JaCoCo Java agent to Surefire; original test
and production source files are unchanged. `CoverageLines.java` in the same
scratch reads the exec data against the compiled class.

Checklist status is unchanged: `no_cluster_test` means no existing unmodified
embedded-cluster test has demonstrated the selected branch, not no cluster
test reaches the method.
