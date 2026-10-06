# HBASE-23: source-only original-test mapping

Selected HBase 2.6.6 site:
`ZKProcedureCoordinator.sendGlobalBarrierReached(Procedure,List)` at line 131.
The selected negative arm throws `IOException` when nonempty data from an
already-existing `reached/<member>` ZooKeeper child lacks the HBase protobuf
magic prefix. Its control-flow prerequisites are:

1. `watchAndCheckExists` sees the member's reached child.
2. `ZKUtil.getData` returns a nonnull, nonempty payload.
3. `ProtobufUtil.isPBMagicPrefix(payload)` returns false.

The proposed original `TestZKProcedureControllers.testZKCoordinatorControllerWithSingleMemberCohort`
uses a real MiniZKCluster but mocked coordinator/member callbacks. Its helper
calls `controller.sendGlobalBarrierReached(p, expected)` at line 213, then
calls each `cc.sendMemberCompleted(sub, memberData)` at lines 216–218. The
member's reached child has not been posted when this direct call checks it,
so the selected predicate is not forced by this test. The no-cohort and
multiple-cohort tests use the same helper. The `runEarlyPrepareNodes` helper
has the same ordering, and the tests that would call it are commented out.

`TestZKProcedure.testSingleMember` and `testMultipleMembers` run real
asynchronous cohorts. A fast member might create its reached child before
the coordinator's loop checks that child, so source review alone cannot rule
out evaluation of the **predicate** in those methods. However,
`ZKProcedureMemberRpcs.sendMemberCompleted` converts null data to empty and
always calls `ProtobufUtil.prependPBMagic(data)` before creating the child
(lines 265–278). They do not provide the malformed nonempty payload needed
for the selected negative arm. `testEmptyMemberSet` has no child to inspect;
`testMultiCohortWithMemberTimeoutDuringPrepare` aborts before the reached
barrier. `TestProcedureCoordinator` mocks the RPC controller instead of
executing this production ZK method. A source search of the original test
tree found no test that prewrites malformed reached-child data before calling
the real method.

The current fault model injects exceptions at observed I/O calls. An
exception from `ZKUtil.getData` follows this method's `KeeperException`
handler, a different `IOException` path, rather than producing a malformed
payload at the selected check. This is also a byte-format validation
predicate within a coordination protocol, not an aggregate multi-actor state
invariant. The source-only audit therefore found no suitable original
embedded-ZooKeeper JUnit for the selected malformed-data arm. **No test was
run, no target hit was measured, and no fault trial was attempted.** This is
not a quality-complete negative bug result.
