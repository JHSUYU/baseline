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
newer-epoch path. An isolated follow-up with the observed restarted-peer
`#epoch1` address passed the unchanged JUnit in 44.819 seconds. Its original
GraphChecker session `trial3-37229dfa` contains a target row at unit 51 with
`reachedAnchor=true`, `phiTerm=false`, `observedFatal=false`, and zero gaps.
This is target reach evidence, not a bug or fault-injection result. Both
addresses were copied from diagnostic runtime observations and were used only
to isolate the actor-binding defect.

The recording-derived proof uses a fresh original GraphChecker static seed,
`REGION_STATE` weave, and a task whose full occurrence comes from a healthy
recording. The original
workflow aggregates method, branch, field, and protocol rows with
`CausynthTraceRecorder` into `concolic_region_plan.jsonl`; then
`plan.ConcolicScheduler` converts that runtime region plan and the static
candidate graph/scope map to `execution_task_plan.jsonl` and a workflow
index. The latter task plan is what `ConcolicTaskPlan` admits. Copying a
refusal address into a task by hand is acceptable only as an isolated
admission smoke test.

The unchanged ZK07 JUnit passed under the recording weave, producing a CLOSED
trace with 72,606 runtime rows and two `Learner.registerWithLeader` branch
events at Jimple unit 51, both with outcome `false`. Its exact first
target-region activation did **not** execute unit 51. In the original plan,
`branches[].observed` means executed, while `observedOutcome` carries the
branch polarity. Selecting the first activation therefore produced a
misleading target task: the diagnostic concolic run passed JUnit but emitted
only `reachedAnchor=false`.

The branch events identify the first actually reached target as call ID
118976 on `zk-peer-1#epoch1`. Re-aggregating the same CLOSED trace with the
original selector
`zk-peer-1#epoch1/region/REGION.77ac7573-6fd5-35c3-b2e6-edccead64143#1`
gave a declared target whose unit-51 branch has `observed=true`,
`observedOutcome=false`, `selectedRuntimeEventSeq=119477`, and
`selectedCallId=118976`. The original `ConcolicScheduler` then emitted 36
tasks. Its target task was selected verbatim from that task plan.

The source-built original engine pin for this diagnostic is
`c0e937bf07c374a62858475b8238dc0ad4a0415f26ac68b418b7c45e0735ee58`.
The original concolic weave plus the actor post-weave were run once. Two
independent executions of the unchanged JUnit on the same task and class
tree both passed, in 69.827 and 72.827 seconds. The class-tree SHA-256 was
`91dd9c59a61bbe1342adc888867e67bb09e95d3eda862b7e6077e0a84db58ac9`.
In both original sessions, the same peer-1 epoch-1 occurrence emitted a
later target row with `reachedAnchor=true`, nonempty `phiTerm`, and
`observedFatal=false`. Original `SessionReader` and `ClosurePlanner` read
both sessions and retained the target region. These are no-fault target
admission results, not bug findings.

This static seed did not include the ZooKeeper communication mapping: the
native closure retained one region and 107 observed STATE edges, with zero
WIRE edges and 375/374 gaps across the two runs. Complete cross-process
causal closure needs the mapped static seed and its concolic communication
hooks. A case dispatcher must select the first target *check event* reached
in a healthy trace; choosing the first target-region activation is not
sufficient.

The first recording attempt exposed a static-stage compatibility gap. The
existing ZK07 static artifacts were generated inside Mallory's Soot Scene
and contain synthetic lambda class names such as
`ZKUtil$lambda_deleteInBatch_0__140`. Original `GraphCheckerMain` installs
its content-stable `LambdaClassNames` before building method bodies, so its
`REGION_STATE` weave refuses that old skeleton method as outside the
application scope. A fresh static seed and recording weave must use the
same original GraphChecker lambda naming before a recording-derived plan can
be trusted. These old static artifacts cannot serve as the native recording
authority. The fresh original static seed used above resolves that lambda
naming mismatch.

`NativeZooKeeperActorWeave` closes a peer turn on normal return, and on
an exception escaping the whole method. An `ATHROW` handled inside
`QuorumPeer.start()` must not close the turn early. The weaver computes both
rewritten classes before writing either and recomputes verifier frames
against the woven application classpath.

`NativeZooKeeperActorBridgeSmoke` verifies that peer ticks override an
inherited JUnit client request, that a Learner alias resolves to its peer,
and that replacement peer objects get the next epoch. It passed on the
isolated GraphChecker Zero VM.
