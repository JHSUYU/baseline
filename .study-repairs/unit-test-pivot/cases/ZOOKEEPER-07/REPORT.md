# ZOOKEEPER-07: original rolling-restart unit test

## Verdict

The unchanged ZooKeeper 3.8.7 `QuorumRestartTest#testRollingRestart` reached
the exact ZOOKEEPER-07 target during its three in-JVM peer restarts. A
closure-selected `IOException` was applied at the first restarted learner's
`Learner.readPacket` archive read. The exception propagated through
`registerWithLeader`, the follower retried, and later executions reached the
target guard. Both later guard outcomes were nonfatal; the JUnit test passed.
This trial found **no ZOOKEEPER-07 failure**.

The original source checkout is tag `release-3.8.7`, commit
`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae` at
`/tmp/zk387-unit-smoke-20261006`. No ZooKeeper production or test source was
changed, and no Docker or handwritten workload was used. The case's isolated
GraphChecker checkout is `graphchecker/`, ending at commit `6ef51dd30`;
the matching jar SHA256 is recorded in `result.json`.

## Target resolution and static closure

The checklist selection line 525 is the last line of the exception message.
In this tag, the `else if (newEpoch == self.getAcceptedEpoch())` guard begins
at `Learner.java:515`, and `throw new IOException` begins at 522. The fatal
condition is the `else` after `newEpoch > acceptedEpoch` and
`newEpoch == acceptedEpoch`, namely `newEpoch < acceptedEpoch`. GraphChecker
resolved the target throw to
`<Learner: long registerWithLeader(int)>#u66` and its immediate guard to
`#u51` with fatal outcome `true`. The guard chain also includes `#u40=true`
and `#u29=false`. The target's static region is
`REGION.0635dd39-d01c-3e35-acc6-a3261bc55660`.

The static candidate graph includes an `explicit_symbolic_fault` at
`<Learner: void readPacket(QuorumPacket)>#u6`, marker
`FAULT:ZK_QUORUM:RESPONSE`, before `InputArchive.readRecord`. It also includes
the accepted-epoch field, `QuorumPeer.getAcceptedEpoch`,
`QuorumPeer.readLongFromFile`, and the target guard dependency. The door is
therefore on the target's backward static slice. The selected runtime
target-plan row has `targetClosureEvidence.evidenceTier=EXACT` and one
`READY` closure goal. Its `edgeEvidence` field is `UNAVAILABLE`: this proof
does not claim a complete retained predecessor-edge chain for each field
value.

## Peer and causal trace

The case-specific Soot weave identifies each original `QuorumPeer` object as
`zk-peer-{sid}#epochN`, aliases its follower/leader actor, and opens peer
scope before `QuorumPeer.start`, `Follower.followLeader`, and
`Learner.registerWithLeader` rich method recording. Six persisted epoch-file
reads in the healthy recording belong to restarted peers 1, 2, and 3 at
epoch 1. The original test body remained the recording window.

At the actual `LearnerHandler` `LEADERINFO` write and `Learner.readPacket`
archive read, the bridge pairs packets by directional TCP socket tuple and
FIFO position, verifying packet type and zxid. Four healthy
`EXCHANGE_SEND`/`EXCHANGE_RECEIVE` pairs match on transport, correlation ID,
and attempt ID across distinct peer sources. For the first target, leader
`zk-peer-3#epoch0` sent at trace seq 31697 and learner
`zk-peer-1#epoch1` received at seq 31799. The receive carries the producer's
remote parent span. There were no missing or mismatched `LEADERINFO` pairs.
`evidence.json` lists all four pairs and source IDs.

GraphChecker normally folds a nested target region into its running
`QuorumPeer.run` region. That first produced a BLOCKING shared address for
three follower activations and left two same-peer target entries in one
parent occurrence. The final opt-in GraphChecker change reads the static
region skeleton and preserves every `FAILURE_TARGET_ENTRY` as its own
occurrence in both recording and replay. Default folding behavior is
unchanged. Healthy peer-1 target entries now have distinct
`REGISTER_WITH_LEADER#1` and `#2` target addresses. Each target plan row has
one `enclosingActivationIds` link back to the peer's `QuorumPeer.run`
activation. The final healthy plan has no BLOCKING gaps. Two unrelated
leader-side `OCCURRENCE_ADDRESS_SHARED` gaps remain DIAGNOSTIC.

The healthy trace contains four `registerWithLeader` entries, with two
observed `#u51` guards, both `false`. `record-summary.json` reports
`ACTIVATED`, no fatal occurrence, and exit 0. The original JUnit log records
restart 1, 2, and 3 succeeding.

## Exact exception trial

`trial-03/plan.json` selects the first observed peer-1 target-region fault
point by its full occurrence address, source key, site, marker, and hit
ordinal 1. It was made from healthy `FAULT_POINT_OBSERVED` seq 31358. In the
trial trace, `FAULT_MATCHED` is seq 31321 and `FAULT_APPLIED` is seq 31322,
exactly once. `Learner.registerWithLeader` exits by
`java.io.IOException` at seq 31341. A later target invocation on peer 1
reaches guard `#u51` at seq 36417, outcome `false`; peer 2 reaches the same
guard at seq 52087, also `false`. `FAULT_TRIAL_SUMMARY` records
requested=matched=applied=1 and `targetAfterFault=true`. The fault trace
reaggregates successfully: its later target occurrences have their own
EXACT target-region plan rows, READY goals, and no BLOCKING gaps. The test
finishes all three restarts with process exit 0.

There were three exploratory fault trials in total. `trial-01` used a plan
with a BLOCKING shared parent address, and `trial-02` repaired peer scope but
still selected a parent containing multiple target entries. Both matched
and applied an exception, and both are retained as evidence, but only
`trial-03` is counted as strict. The target fatal arm was never observed.

## Verification and limits

- `mvn -q -Dtest=FailureTargetRegionPreservationTest test`: two tests passed,
  covering default folding and separate same-peer target occurrences under
  the static opt-in policy. `mvn -q -DskipTests package` passed.
- Final static seed: 23.212 s; final runtime weave: 24.288 s; healthy JUnit
  recording: 6 s; strict trial runner: 6.058 s; trial aggregation: 3.663 s.
  These successful steps exclude the native smoke, builds, earlier trials,
  and a failed attempt whose fixed test ports conflicted with another run.
- The final trial has one DIAGNOSTIC leader-side shared-address gap and one
  DIAGNOSTIC lineage gap. Its injected read prevents one `LEADERINFO` receive,
  so five sends and four receives are expected; four pairs still match.
  Complete predecessor-edge evidence for accepted-epoch values is not
  published by the current planner.

See `result.json` for the machine-readable verdict and `evidence.json` for
the trace events, target addresses, exact packet pairs, plan rows, and gaps.
