# SOLR-09 node2 healthy admission review

This is a source and event audit of the one authorized healthy JUnit on node2
lane3. It is not a fault trial or a bug finding. `audit_healthy.py` rechecks
SHA-256 for the raw evidence, the source and runtime inputs, compiled class
identities, token and actor continuity, branch order, and the graph witness.
The generated `healthy-audit-node2-lane3.json` is the compact receipt.

## Exact observed path

The unchanged `DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup`
passed 1/1 tests with zero failures and errors. The source checkout was
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`; the executed
`DeleteReplicaCmd.class` had SHA-256
`a76f7f732bd13437f37a44e4e0eaee13e053b0a6ae72b571bea1b3ec6b623c3b`.
The site catalog gave the typed door owner class SHA-256
`a13bdec21685f267f30ca01db19338b0cb84e94813ba3471847687189c6e779f`.
Both used loader `sun.misc.Launcher$AppClassLoader@18b4aac2`.

| Sequence | Event | Actor and meaning |
| --- | --- | --- |
| 249–250 | `TASK_SUBMIT` → `TASK_CLAIM` | Node4 token `9e71d651-eb9f-4769-893b-2b1cecec50e1:task:113`; claim on thread 217. |
| 251–252 | `processMessage` → `deleteCore` region enters | Node4 epoch 0, thread 217; observed `region_parent` edge from event 251 to 252. |
| 266 | `DOOR_OBSERVED` | Exact `OverseerCollectionMessageHandler#waitForCoreNodeGone(...)@434:door:1`, `TimeoutException`, door ordinal 1. |
| 280 | `TARGET_CHECK` | Exact `DeleteReplicaCmd#deleteCore(...)@277:branch:7`, outcome `TAKEN`; no target throw. |

The door and target share node4, epoch 0, thread 217, command token, and the
same `deleteCore` occurrence. Event 266 precedes event 280. The graph builder
returns an empty-edge same-occurrence witness for 266→280, and **no nonempty
event-time edge path**. The observed parent edge ends at the earlier region
entry, so it cannot be reused as a door→target edge. The broader feedback
count of eight eligible doors does not mean eight target-related doors: this
review selects this one typed wait door. The clean target check and JUnit pass
show the guard executed without its line-278 throw. The trace does not emit a
separate branch event for the first wait at line 260, so assigning event 266
to that source call is a source-and-sequence inference, not a direct callsite
measurement.

## Pinned source control flow

`DeleteReplicaCmd.java` SHA-256 is
`da2c12e6a8bc2cfd279fcebdb4c1bc4929c6c020e5aca975a3b5e7c49a6ca793`.
For a live replica, line 251 sends CoreAdmin `UNLOAD`; line 257 consumes its
response without aborting on response error; line 260 performs the first
`waitForCoreNodeGone`. When that wait is false, line 264 calls
`deleteCoreNode`, which offers a `DELETECORE` state update at
`OverseerCollectionMessageHandler.java:450-457`, then line 265 performs a
second wait. Two false waits yield `Boolean.FALSE` at line 266. The
synchronous `!callable.call()` guard at line 277 then takes the line-278
`SolrException` path. A successful second wait instead returns true and
retains line 277 with its healthy branch.

`OverseerCollectionMessageHandler.java` SHA-256 is
`15313dd15ba45ade14ae077b21b7972e26ae49c6400305c2b0605c5da8232d51`.
Its line 434 calls the typed `ZkStateReader.waitForState`. Lines 443–444
catch `TimeoutException` and return false. Thus a single exception injected
at that exact call has a plausible path through the fallback and back to the
selected guard. This is a coordination wait on watched state, not a direct
ZooKeeper read. A different exception escaping the callable reaches the
wrapper catch at `DeleteReplicaCmd.java:282-283` and would bypass the
selected line-278 throw.

## Bounded next pilot proposal

One diagnostic, single-fault trial could replay `EXCEPTION` /
`java.util.concurrent.TimeoutException` at exact site
`OverseerCollectionMessageHandler#waitForCoreNodeGone(...)@434:door:1`,
door ordinal 1, on the registered Overseer actor. The healthy replay point is
node4, epoch 0; node identity can change across JUnit runs, so a fixed node4
plan that never matches is inconclusive. Keep one fault maximum, one JUnit,
no automatic expansion or full campaign, a fresh output, and the same
SHA-pinned source, adapter, agent, sites, and JUnit. This is a proposal only;
dispatch must grant a fresh lane/resource gate before any JVM run.
`pilot-plan-node2-lane3.json`, `pilot-node2-lane3.json`, and
`run_node2_lane3_exact_timeout_pilot.sh` stage that exact replay. The runner
calls one JUnit trial directly and cannot select another door from a campaign
queue. `manifest-pilot-node2-lane3.json` pins its inputs by SHA-256.

The postfault audit must observe `FAULT_MATCHED` and `FAULT_APPLIED` for that
exact site/node/epoch/ordinal, with the fault on the same thread and
`deleteCore` occurrence as a subsequent line-277 target check. It must
establish the first timeout's false return, the `DELETECORE` fallback, and
the second wait by direct events or a clearly labeled local source timeline.
The target check must occur after the applied fault. A wrapper exception at
line 283, a missing target, an unmatched node/ordinal, or a door only in
global counts is a negative or inconclusive result. A nonempty event-time
door→target path remains an open graph requirement; a passing JUnit or local
timeline alone cannot support full admission. The pilot would test recovery
control flow and makes no failure claim by itself.
