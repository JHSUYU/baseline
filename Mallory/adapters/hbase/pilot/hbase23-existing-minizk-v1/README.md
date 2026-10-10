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
provide another source-backed timing opportunity. The existing four-member
test subsequently passed once on node1: JUnit 1/0/0, exact named target,
two typed doors, and two same-occurrence local-timeline witnesses in 5.593 s.
`prior-admitted-healthy.json` SHA-pins that raw result, compressed event trace,
admission receipt, and offline audit. This result establishes a usable seed;
it does not claim a fault-induced bug.

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

The healthy runner refuses concurrent Java processes, holds the node1 lane lock, and
writes an immutable directory under
`data/mallory/HBASE-23/healthy/existing-minizk-four-member-v1/`.
It permits at most three healthy attempts, with one existing JUnit and zero
fault trials per attempt. The admitted attempt-01 passed the named target,
typed door, actor identity, and event-time checks.
`source-inventory.json` records the tested alternatives and the outstanding
decision if this selector also misses. The node0 `stage-preflight.json` checks
source, compiled test class, target bytecode, site, and config without starting
a JVM.

## Full campaign staged for dispatch

The full campaign uses the same existing JUnit, exact target, typed door,
agent, adapter, core release, and source-equivalent runtime. `full.json`
changes only the run mode and budget: at most 80 fault trials, 3600 seconds,
600 seconds per trial, and 3 faults per sequence. The earlier admitted healthy
run is prerequisite evidence, never reused as the full campaign's seed.

After HBASE-34 is terminal and dispatch grants the free node1 HBase lane,
sync this package to node1 and run:

```sh
python3 Mallory/adapters/hbase/pilot/hbase23-existing-minizk-v1/preflight_full.py --strict-runtime
MALLORY_NODE1_CAPACITY_GRANTED=1 python3 Mallory/adapters/hbase/pilot/hbase23-existing-minizk-v1/run_full.py --attempt 1
```

`run_full.py` makes a new fault-free r0000 in its own immutable attempt
directory. It synchronously verifies the selected JUnit, exact compiled check,
named actor, accepted Procedure worker token, typed `getData` read, and ordered
same-thread, same-occurrence door-to-check witness before scheduling any fault.
It writes `fresh-r0000-admission.json`; a rejection terminates the attempt with
zero fault trials. This gate wraps the frozen core's result application so the
event trace can be checked before the core selects the next fault sequence.
The node1 lane lock and Java process check prevent concurrent campaigns. An
interrupted attempt resumes from its checkpoint only if the full config and
fresh r0000 receipt still match. Dispatch may use attempts 2 or 3 in fresh
directories if needed.

The full output belongs under
`data/mallory/HBASE-23/full/existing-minizk-four-member-v1/`. Dispatch audits
the terminal output and classifies any target exception using its trace and
source. A target exception alone remains a candidate until reproduced and
explained.
