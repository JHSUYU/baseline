# HBASE-23 existing four-member MiniZK test

This package selects the unchanged HBase 2.6.6 test
`TestZKProcedure#testMultipleMembers`. Its `@BeforeAll` starts a real MiniZK
cluster, and `runCommit("one", "two", "three", "four")` creates a real
`ZKProcedureCoordinator`, four real `ZKProcedureMemberRpcs` controllers, and a
`ProcedureCoordinator` worker. Test callbacks and subprocedures use Mockito,
as in the upstream test. The production target class and the test class are
both the original compiled HBase artifacts. No new JUnit or HBase source
overlay is used.

The target is the PB-magic check in
`ZKProcedureCoordinator.sendGlobalBarrierReached` at source line 127, with its
IOException throw at line 131. It executes only when a member completion child
already exists during the coordinator's synchronous scan. In contrast,
`TestZKProcedureControllers` explicitly calls `sendGlobalBarrierReached`
before posting member completion children, so it normally exercises the
separate ZooKeeper `nodeCreated` callback. The original full MiniCluster test
`TestProcedureManager#testSimpleProcedureManager` reached the exact check once
in archived v13 but missed it in subsequent passing attempts, including a
16-procedure repetition. Four active members in this existing MiniZK test
provide another source-backed timing opportunity. This is a healthy-only
admission attempt, not a claim that the target will be reached.

The selected physical fault door is
`RecoverableZooKeeper.getData@405 → ZooKeeper.getData` with a typed
`KeeperException.ConnectionLossException`. The frozen `fa5f` core and existing
HBase adapter provide named ZooKeeper actors and accepted procedure
submit/claim tokens. `verify_healthy.py` requires the exact named check and
typed door in the same target occurrence and ordered local timeline. It
records any graph path separately. A passing JUnit without that evidence is
inconclusive, and no fault campaign starts.

## Dispatch gate

After synchronizing this package to node1 and when its HBase lane is free:

```sh
python3 Mallory/adapters/hbase/pilot/hbase23-existing-minizk-v1/preflight.py --strict-runtime
MALLORY_NODE1_CAPACITY_GRANTED=1 python3 Mallory/adapters/hbase/pilot/hbase23-existing-minizk-v1/run_healthy.py --attempt 1
```

The runner refuses concurrent Java processes, holds the node1 lane lock, and
writes an immutable directory under
`data/mallory/HBASE-23/healthy/existing-minizk-four-member-v1/`.
It permits at most three healthy attempts, with one existing JUnit and zero
fault trials per attempt. Do not promote to full fuzzing until a fresh attempt
passes the named target, typed door, actor identity, and event-time checks.
`source-inventory.json` records the tested alternatives and the outstanding
decision if this selector also misses. The node0 `stage-preflight.json` checks
source, compiled test class, target bytecode, site, and config without starting
a JVM.
