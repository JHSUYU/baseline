# HBASE-23 typed ZooKeeper-read healthy admission

This case-local package keeps the unmodified
`TestProcedureManager#testSimpleProcedureManager` MiniCluster JUnit and exact
`ZKProcedureCoordinator.sendGlobalBarrierReached` check at line 127. The
existing test reaches that check intermittently: the reached/member child must
appear before the coordinator's synchronous scan. Archived v13 passed the JUnit
and recorded one named nonthrowing exact check; v21–v23 passed but missed it.

`sites.json` selects one physical I/O call: `RecoverableZooKeeper.getData` line
405 invokes `ZooKeeper.getData`, with a typed
`KeeperException.ConnectionLossException` fault. HBase 2.6.6 retries that
exception within the read; a successful retry can return the PB-prefixed bytes
to the selected check. Exhausted retries leave the method before the check.
The read fault by itself does not imply a malformed-prefix exception at line
131.

The frozen future-handoff adapter registers the `zk-coordinator:<name>` actor
and wraps each accepted `ProcedureCoordinator.pool.submit` in an exact
`TASK_SUBMIT`/`TASK_CLAIM` token. The door executes inside the selected region
on the worker thread. The frozen core labels an ordered door and check on that
same thread and occurrence as `observed_local_timeline`; a same-region sequence
does not claim an observed cross-region graph edge. The config requires event
time validation and enables only this explicit typed door.

`preflight.py --write` checks source and compiled HBase bytecode without a JVM.
Its node0 receipt is `stage-preflight.json`; node1 runtime files remain deferred
there. Dispatch must sync the package to node1 and run
`python preflight.py --strict-runtime` before any MiniCluster attempt. That mode
checks all pinned runtime files, source equivalence, and the selected test.

With node1 capacity granted, dispatch can run one fresh healthy attempt using:

```sh
MALLORY_NODE1_CAPACITY_GRANTED=1 python Mallory/adapters/hbase/pilot/hbase23-zk-read-admission-v1/run_healthy.py --attempt 1
```

The runner holds `/tmp/mallory-lanes/hbase-lane9-next.lock`, refuses a running
JVM, and writes under `data/mallory/HBASE-23/healthy/typed-zk-read-v1/`. One
attempt uses one JUnit and zero fault trials. Dispatch may use attempts 1–12
for the natural check race, stopping at an admitted healthy receipt. Each
attempt has a separate immutable directory. `verify_healthy.py` requires a
passing JUnit, valid exact site catalog, named check, typed door in the target
closure, matched worker token, and an offline audit of the same-thread,
same-occurrence ordered events. It records graph-path count separately.

The next decision is based on that raw healthy trace and receipt. No fault
campaign is included in this package.
