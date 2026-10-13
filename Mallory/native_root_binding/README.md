# Native GraphChecker actor binding for embedded ZooKeeper tests

The source-built GraphChecker ZK07 pilot reached
`Learner.registerWithLeader` four times under the unchanged
`QuorumRestartTest#testRollingRestart` JUnit. The original `ConcolicRegionRuntime`
admitted none of them. Its refusal rows identify two independent mismatches:
the run attributed every peer thread to the JUnit driver's
`native-junit#epoch0` source and `Root:CLIENT/testRollingRestart#1`, while the
pilot task demanded a synthetic `zk-peer-1#epoch0` occurrence under
`Root:PEER/zk07#1`. The woven entry and branch hooks were present and ran.

`NativeZooKeeperActorBridge` uses the original GraphChecker `MessageDoors`
source and tick APIs. It registers each `QuorumPeer` object from its real
`getMyId()`, increments the epoch when a replacement object uses the same
server ID, opens a peer turn over `QuorumPeer.start()` and `run()`, and aliases
each `Learner` receiver to its actual `self` peer. The paired
`NativeZooKeeperActorWeave` adds these system-level hooks to the classes
already woven by GraphChecker. No check ID or target branch appears in this
adapter. A production weave must include both original `QuorumPeer.class`
and `Learner.class` in its immutable input tree; the post-weaver is run once
and its classpath/output hashes belong in the native weave receipt.

In an isolated pilot, the unchanged JUnit passed (one test, zero failures) in
62.95 seconds. The first observed Learner occurrence was:

```
zk-peer-1#epoch0/region/REGION.0635dd39-d01c-3e35-acc6-a3261bc55660/ctx:Root:PEER_RUN#1/idx:<org.apache.zookeeper.server.quorum.Learner: long registerWithLeader(int)>@0
```

Further roots were attributed to peer 2 and to replacement peer objects with
`#epoch1`. The isolated native session contained six peer-attributed root
refusals and zero gaps. It still contained zero activations, decisions, and
target rows because the pilot plan retained the invented context/index. This
is a source-binding diagnosis, not a completed check or bug result.

A subsequent fresh two-class GraphChecker weave with the observed initial
peer-1 address admitted one activation (two decision rows, one target row,
zero gaps) while the original JUnit passed. That target row says
`reachedAnchor=false`: `Learner.registerWithLeader`'s target branch at Jimple
unit 51 lies on the equal-or-lower epoch path; the initial peer took the
newer-epoch path. The existing independent healthy trace reached this check
on restarted peer 1 and peer 2 (`#epoch1`). The next native pilot must select
the recording-derived restarted-peer occurrence and require
`reachedAnchor=true`; merely emitting a target row does not suffice.

The next proof uses a fresh original GraphChecker weave and a task whose full
occurrence comes from a healthy recording. The real workflow should use
`CausynthTraceRecorder`'s recording aggregation (`aggregateTarget`), which
calls `RuntimeRegionPlanner` to write `concolic_region_plan.jsonl` from
observed method, branch, field, and protocol rows. Copying a refusal address
into a task by hand is acceptable only as an isolated admission smoke test.

`NativeZooKeeperActorBridgeSmoke` verifies that peer ticks override an
inherited JUnit client request, that a Learner alias resolves to its peer,
and that replacement peer objects get the next epoch. It passed on the
isolated GraphChecker Zero VM.
