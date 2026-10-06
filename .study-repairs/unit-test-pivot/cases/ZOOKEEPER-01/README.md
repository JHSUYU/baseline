# ZOOKEEPER-01: closing-session check

## Completed coverage/I/O campaign

An unchanged `testCloseSessionWhileUpgradeOnLeader` JUnit healthy run in
`discovery` trace mode reached the selected `#u15` check and observed 34
runtime I/O points. The new campaign used exact runtime fault selectors,
production method/branch coverage, and newly observed I/O to select and mutate
sequences. Its selection algorithm did not build a graph or use a closure.
Its node2 tmux session is `zk01_coverage_io`, and the resumable checkpoint is
`/users/ZhenyuLi/zk01-unit/campaign/results/ZOOKEEPER-01/state.json`.
The case-local `result.json` and `evidence/new-trial-ledger.json` were mirrored
atomically from that checkpoint after each trial. The authorized budget was
64 sequences with at most 6 faults, extendable on the same checkpoint to
128/8 if the final 12 initial trials still yielded new production method or
branch coverage or a new I/O family.

The runtime recorder is still the earlier GraphChecker prewoven ZooKeeper
classes plus `graphchecker-client.jar`; the weave that created those classes
read a static `region_skeletons.jsonl.gz`. Thus **the recorder has a legacy
static-weave dependency**, although this campaign's runtime used
`causynth.trace.mode=discovery`, passed no `causynth.region.skeletons` property,
and neither the fuzzer nor its feedback parser read a skeleton, static scope
map, graph, or closure. The static-weave dependency and the graph-free
selection algorithm are recorded separately in
`evidence/instrumentation-provenance.json`.

The six trials below came from the earlier closure-guided selection process.
Their selectors match the new healthy seed and their fault/target events can
be reevaluated, but they are excluded from the new campaign's trial count,
coverage, and prioritization. Their six selector IDs remain in the new
checkpoint's seen set so they are not rerun. The new campaign begins at zero.

### Final result

The original three-peer embedded-cluster JUnit completed **64 new fault
sequences**, comprising 28 one-fault, 14 two-fault, and 22 three-fault
sequences. Eleven sequences needed a retry, for **75 attempts and 408.122
seconds of fault-run time**; the new healthy seed took 4.227 seconds, yielding
412.349 measured seconds total. All requested faults matched in 58 sequences.
Six sequences were unmatched after retries; 18 strict injections lost the
selected check and were discarded as feedback. The remaining **40 strict
sequences reached the selected guard after their last fault**. None executed
the selected explicit `SessionExpiredException` throw. There is no new bug
candidate from this campaign.

The admitted faulted runs added 64 production methods and 152 branch outcomes
beyond the new healthy seed. The 1,119 additional call-site return/throw IDs
are separate feedback, not method/branch coverage. Three JUnit runs exited
with `ConnectionLossException` on `/node-1` (trials 20, 48, and 52); each lost
the selected check, so none satisfies the exact target exception oracle.
The final 12 sequences added zero production method/branch IDs and zero I/O
families. The 128/8 extension was therefore not taken. The fixed budget ended
with 897 queued sequences, so `quality_complete` describes **this workload and
budget**, not exhaustive absence of a bug. `evidence/new-trial-ledger.json`
records every sequence, all-attempt time, exact injection, target retention,
fault marker, JUnit exit, and feedback; `evidence/extension-decision.json` and
`evidence/source-review.json` record the stopping and source review decisions.

The selected check is `SessionTrackerImpl.checkSession(long,Object)` in
`zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java:316-317`:
`if (session.isClosing()) { throw new KeeperException.SessionExpiredException(); }`.
The exact instrumented guard is `#u15`, and the throw is `#u18`. A JUnit
failure or an exception elsewhere is not a hit at this check.

## Original cluster workload

The mapped, unchanged
`SessionUpgradeQuorumTest.testCloseSessionWhileUpgradeOnLearner` passed as a
native JUnit, but its `learnerId > 0` condition skipped the close/upgrade
workload under the observed election. The unchanged sibling
`testCloseSessionWhileUpgradeOnLeader` ran the same helper on the elected
leader in the original three-peer embedded cluster. It delayed request
submission, sent an asynchronous ephemeral create, closed the client,
reconnected, and checked that the node was gone. The earlier healthy run passed
in 4.126 seconds. It reached the selected method on both the global and local
trackers; neither call threw at `#u18`.

## Bounded fault trials

The healthy trace exposed six writes at
`ClientCnxnSocketNIO.doIO` → `SocketChannel.write(ByteBuffer)`. Each stored
selector fixes the runtime marker, source, site, occurrence, and hit ordinal.
The occurrence string is treated as an opaque runtime identity. Four points
are xid>0 requests; two are connection packets retained as exploratory
faults. The same original leader JUnit was rerun with one `IOException` at
each selected write. Every selector matched and applied once.

| Trial | TCP packet | JUnit exit | Global guard after fault | Exact throw | New branch outcomes | Total seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `tcp-connect-01` | connection | 0 | 1 | 0 | 10 | 8.815 |
| `tcp-connect-02` | connection | 0 | 0 | 0 | 17 | 9.557 |
| `tcp-xid1-01` | request | 0 | 0 | 0 | 6 | 5.806 |
| `tcp-xid1-02` | request | 1 | 0 | 0 | 6 | 4.338 |
| `tcp-xid2-01` | request | 1 | 1 | 0 | 7 | 5.821 |
| `tcp-xid2-02` | request | 0 | 0 | 0 | 11 | 4.742 |

The six trials took 39.079 seconds in total. Their union added 23 distinct
instrumented `(branch site, outcome)` pairs beyond the healthy seed's 241.
Two JUnit failures occurred after injection, but neither executed the exact
`SessionExpiredException` throw. The global target remained after one of the
four request faults; its guard stayed nonfatal. ZooKeeper's source explicitly
rejects closing sessions here, so even a future exact throw needs source-level
review before being called a bug.

The historical result was **pending after a bounded campaign**: no new bug
was confirmed. Its measured cluster-run time was 63.080 seconds across nine
healthy runs and six trials; build and preparation time was excluded.
`evidence/legacy-result.json` and `evidence/campaign-summary.json` preserve
that result and its per-trial times.
`fault-door.json` names the injected I/O operation, `evidence/plans/` holds
the exact selectors, and `evidence/checkpoint.json` lists completed fault IDs
so later coverage-guided runs can skip them. Full raw traces remain in the
isolated node2 experiment directory `/users/ZhenyuLi/zk01-unit` for audit.
