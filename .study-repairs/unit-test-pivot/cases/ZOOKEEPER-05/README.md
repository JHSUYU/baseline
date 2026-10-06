# ZOOKEEPER-05: follower leader epoch check

The selected check is `Follower.followLeader()` at `Follower.java:98-103`,
`<org.apache.zookeeper.server.quorum.Follower: void followLeader()>#u68`.
The original Apache ZooKeeper 3.8.7 test
`org.apache.zookeeper.test.QuorumRestartTest#testRollingRestart` starts three
embedded quorum peers and rolls each peer through shutdown/restart. The native
test passed: one test, zero failures/errors/skips (`native.log`). ZooKeeper
source is the unmodified release-3.8.7 worktree in `source/`; GraphChecker
instrumentation is isolated to the `graphchecker/` worktree.

The healthy GraphChecker trace is `record2/runtime/runtime_trace.jsonl`.
It records four `Follower.followLeader` entries and four safe outcomes of
guard `#u52=true`. Its target-rooted plan
`record2/targets/zk05/runtime/concolic_region_plan.jsonl` maps the selected
check one-to-one to explicit region
`REGION.1e25f543-ad81-3ed6-b419-eabbb2153db4` with `EXACT`
target-closure membership and zero blocking graph gaps. The region has ten
observed exact-identity checked-I/O fault markers. The plan reports
`edgeEvidence:UNAVAILABLE`, so the membership claim is not a proved
cross-peer transport edge.
The adapter source key suffix `#epochN` counts that peer's successive
`followLeader` activations for trace identity; it is not the persisted Zab
epoch value.

The healthy target guard occurs at trace sequence 67399. The first quorum
WRITE, first quorum READ, and second quorum WRITE fault points occur before
that guard (66774, 66814, 67336). The remaining seven occur after it. In
particular, the sole observed file WRITE point at 72600 is inside
`QuorumPeer.setCurrentEpoch` reached from `syncWithLeader`, rather than the
earlier `setAcceptedEpoch` handshake. A file WRITE trial can be assessed
against a later follower activation, not the already evaluated comparison.

## Caught exception oracle

The original bytecode compares `newEpoch` and `getAcceptedEpoch()` at
offsets 178-188. `ifge 250` is the safe branch; the fatal branch falls
through to `new IOException` at 240, constructor with literal
`Error: Epoch of leader is lower` at 246, and `athrow` at 249. The woven
class (`record2/instrumented-classes/.../Follower.class`) records the same
guard as `BRANCH #u52`: `false` enters the fatal arm. It records the
`IOException(String)` constructor as `CALL_SITE_ENTER`, `CALL_ARGUMENT`,
and `CALL_SITE_RETURN` at `#u67`, with the exact literal, followed by
`athrow` at woven offset 1702. The selected static throw site is `#u68`;
that first core build has no dedicated runtime event at the `ATHROW` instruction. The
exception is caught by `Follower.followLeader()`'s own `catch (Exception)`
at source line 127 / original bytecode handler 417, so a normal method exit
does not refute that the target exception occurred. Every trial is audited
for same-call `#u52=false` and exact `#u67` constructor events as well as
the generic method-exit oracle.

## Fault campaign

`fuzzer-config-r2.json` uses the stock JUnit method through GraphChecker
`JUnitMethodRunner`, exact observed closure selectors, checked `IOException`
doors, one case-local source build, case-local temporary directories, and
ZooKeeper's test-process port partition 9/12. `fuzzer-r2/ZOOKEEPER-05/`
holds versioned trial selectors, traces, independently recomputed target
plans, and results. The first exploratory `trials/` attempt omitted a loop
bound property from its independent aggregator, so its Python verdict was
discarded. Its underlying workload trace and a repaired aggregation are
preserved in `aggregate-check/`; the corrected campaign is authoritative.

The first corrected budget in `fuzzer-r2/ZOOKEEPER-05/` completed five
strictly applied fault sequences. Every faulted plan retained an explicit
target-region row and had zero blocking graph gaps. Four trials re-evaluated
the selected `#u52` comparison after the final fault, always on its safe
arm. The fifth selected target activation was lost after its second fault;
the other peers' later guard evaluations were not counted as the selected
target call. Trial-level results give the exact full-occurrence selectors,
times, and coverage. Across the five, there were 8 newly observed global
method/branch-outcome coverage items, zero selected fatal guards, and zero
target exception candidates. Fault workloads took 398.295 seconds;
independent faulted-plan aggregation took 198.134 seconds. The five completed
raw trial traces were compressed after hashing; `fuzzer-r2-trace-manifest.json`
records raw and archive SHA-256 values, and each archive was decompressed
and checked against the raw hash.

GraphChecker core `e73b2c09c` was then built in separate `graphchecker-v2/`
with the same case-local adapter and doors. The original JUnit passed one
isolated healthy reweave in `record-v2/`; the woven-body verifier accepted
1598 bodies, and the target region remained explicit with zero blockers.
The reweave puts `recordExplicitThrow(callId, Follower.followLeader, 68,
exception)` immediately before the selected `ATHROW` at woven offset 1722.
It uses the same `callId` local as guard `#u52`. The healthy trace emitted six
`EXPLICIT_THROW` events at other ZooKeeper sites, confirming the hook executes
and carries site ID, runtime type, and call ID; it emitted none at selected
`#u68`, consistent with four safe guard outcomes. The second singleton
campaign in `fuzzer-v2-single/ZOOKEEPER-05/` uses the exact event/site oracle.
Its six strictly applied one-fault trials covered quorum WRITE ordinals 1
and 2, quorum READ ordinals 1, 2, and 3, and the observed file WRITE. Three
re-evaluated the *selected* guard after the fault, always on its safe arm.
The file WRITE and quorum READ ordinals 2 and 3 lost that selected target
activation; later guards on other peers did not substitute for it. Every
faulted plan retained the exact target-region row and had no blocking graph
gap. No selected `#u52=false`, `#u67` exception constructor, or `#u68`
`EXPLICIT_THROW` event occurred. The second campaign's fault workloads took
498.244 seconds and independent aggregates took 226.916 seconds.

The 3.8.7 source handshake matters to this guard. `Learner.registerWithLeader()`
puts protocol version `0x10000` in `LearnerInfo` (`Learner.java:498`).
`LearnerHandler.run()` reads that version and sends `LEADERINFO` for version
`0x10000` or newer (`LearnerHandler.java:490-536`). In the `LEADERINFO` arm,
`Learner.registerWithLeader()` rejects `newEpoch < acceptedEpoch` with its
own `IOException`, accepts equality, or calls `setAcceptedEpoch(newEpoch)`
before returning (`Learner.java:506-525`). `setAcceptedEpoch` writes the file
before assigning the in-memory value (`QuorumPeer.java:2243-2246`). Its
checked I/O failure therefore aborts the current handshake before the
selected downstream check. The only source calls that set acceptedEpoch are
this Learner handshake and the separate LEADING role; `QuorumPeer.run()`
executes FOLLOWING and LEADING in distinct role arms on one peer thread
(`QuorumPeer.java:1535-1554`). An `IOException` in the early quorum handshake
or `setAcceptedEpoch` aborts that attempt and can lead to a retry. The
observed file WRITE door is in the later `setCurrentEpoch` call, after the
selected comparison, and can only affect a later selected activation. This
source argument is limited to the original same-version cluster and the
checked I/O failure model. The selected downstream guard remains audited
for an unexpected fatal path in each trial.

## Final assessment

Across both budgets, 11 of 11 fault trials applied their complete exact
selectors, seven re-evaluated the selected guard after the last fault, and
four lost the selected target activation. The seven valid trials saw only
the safe guard arm. The exact target `EXPLICIT_THROW #u68` oracle produced no
candidate; a normal `METHOD_EXIT_NORMAL` was never used as evidence that a
locally caught throw was absent. `trials-audit.json` audits selected call IDs,
guard outcomes, constructor events, explicit throws, and normal/throw exits
for both healthy runs and all 11 faulted traces. `trials-summary.json` joins
that audit to each exact selector, faulted plan, result, and trace hash.

The union of the two healthy traces covers 228 methods and 464 branch
outcome pairs. The seven valid checked trials add eight branch outcome pairs,
including two in the target closure; lost-target trials are excluded from
that gain (`coverage-summary.json`). The total measured case effort is
1710.754 seconds, including setup, both builds and healthy records, one
discarded exploratory attempt, 896.539 seconds of fault workloads,
and 425.050 seconds of independent faulted-plan aggregation. All 11 raw
faulted traces were compressed to 49,989,359 bytes after hashing, then
decompressed and checked against their raw SHA-256 digests
(`trace-integrity.json`, the two `*-trace-manifest.json` files).

This is `quality_complete` for the original 3.8.7 rolling-restart workload
and the checked I/O exception model exercised here: exact healthy target
reach, explicit target-rooted region and strict fault trials were observed,
the selected guard remained safe in every valid trial, and source review
explains the pre-guard handshake invariant and post-guard file-write timing.
It is not a claim that the fatal branch is unreachable under other workloads
or failure models. GraphChecker reports `edgeEvidence:UNAVAILABLE`; the
region's exact membership and valid faulted plans do not prove cross-peer
causal edges. No bug is marked.
