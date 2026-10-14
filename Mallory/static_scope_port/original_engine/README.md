# Original GraphChecker seed engine in Mallory

This opt-in module builds the **original** GraphChecker static engine from
source inside Mallory. It is separate from the default `ScopePlanner` artifact
and does not change frozen campaigns. `MalloryOriginalSeedBridge` calls the
original `SeedBackwardStaticAnalyzer.analyze`,
`SymbolicRegionPlanner.planSelectedSkeleton`, `RootDemand.of`, and
`StaticScopeMap.sites/rows` on Mallory's already loaded Soot `Scene`. It writes
the original candidate edge graph, region skeletons, root demand, demanded
doors, scope frontier and static scope map before Mallory adapts the selected
sites into a JUnit weave manifest.

## Provenance

The source baseline is GraphChecker revision
`c4a90033c654737206466ed36ce837c5b3c12457`. The 230 files under
`vendor/src/main/java` are the compiler-transitive Java source closure of
`MalloryOriginalSeedBridge`, `SeedBackwardStaticAnalyzer`, and the original
post-run `Corpus`, `Branches`, `ClosurePlanner`, and `ConcolicScheduler`. The selection was obtained
by compiling those entry sources with GraphChecker's source tree on
`javac -sourcepath` and **without** a GraphChecker JAR. Per-file upstream
and copied SHA-256 digests are in `UPSTREAM_SOURCES.json`. The vendored files
with Mallory adaptations are `SeedBackwardStaticAnalyzer`,
`ConcolicScheduler`, `GraphCheckerMain`, `RuntimeSelectedRegionFinalizer`,
`CausynthTraceRecorder`, and `RuntimeRegionPlanner`; the manifest records their
exact hashes. The former
names its own class rather than
`CausynthPipeline` as the SLF4J logger category, and upgrades a discovered
protobuf message from Soot `HIERARCHY` to `SIGNATURES` before enumerating its
getters. If that upgrade fails, it emits a blocking communication gap instead
of silently omitting a possible RPC message. This keeps the planner's
`whole_program(false)` Jimple identity stable.
`ConcolicScheduler.fatalDecider` adapts to the ported `StaticScopeMap`'s
list-valued guard deciders: it accepts one exact decider and rejects ambiguous
lists explicitly. No guard is selected arbitrarily.
The additional changes support the opt-in native fault weave, an
order-preserving runtime aggregation speedup, and package-private reuse of
the original CLOSED trace and selected-skeleton readers.
The exercised-skeleton selection pass omits signatures because it reads only
region IDs and observed anchors. The full planning pass computes the same
signature bytes after sorting references to recorded events, so a large trace
does not retain one formatted String per event per activation.
The failure-directed demand walk caches repeated incoming-edge queries in a
bounded map; its edge order and admitted closure remain unchanged.
The original `runtime.Listings` and `runtime.Randoms` are copied byte for
byte as well: `CausynthPipeline` rewrites application calls to these helpers
in REGION_STATE weave, so the woven original JUnit needs both classes at run
time. Their exact upstream hashes are recorded in `UPSTREAM_SOURCES.json`.
`src/main/resources/edu/uva/liftlab/graphchecker/library-catalog.jsonl` is
copied unmodified from the same revision. No root-level license file was
present in the source GraphChecker tree at the time of migration; no license
designation is inferred from unrelated `third_party` files.
The resource digest and its upstream digest are also recorded in
`UPSTREAM_SOURCES.json`.

The module's `pom.xml` has only published Soot, Guava, SLF4J and Gson build
dependencies. Its compile and runtime classpaths contain the Mallory module
JAR and these libraries, and contain **no** `GraphChecker/target` JAR.
The older `Mallory/graphchecker_closure_port` copies those three post-run
classes but obtains their remaining dependencies from `GraphChecker/target`;
this module builds the transitive dependencies from source too.

## Invocation

Build with `mvn -q test package` in this directory. Put this module JAR and
its Maven dependency classpath on the static planner's Java classpath. In the
case input, set:

```json
{
  "analysis": {
    "original_graphchecker_seed": true,
    "original_engine_output_dir": "/isolated/output/original",
    "original_loop_default_bound": "3"
  }
}
```

The loop bound is the explicit value required by GraphChecker's original
`LoopBoundPolicy`, not a static-scope truncation. The original engine expects
an exception **construction** site. Mallory resolves the configured target
branch and its controlled fatal throw, follows the thrown local to its unique
`new Exception` definition, then declares that source line to GraphChecker.
It restores the captured `wjtp` Jimple bodies before invoking the original
analyzer because Soot otherwise lowers active bodies to Baf after `runPacks`.
The original concolic weave also reads bodies in `wjtp`; `jtp` can change
unit order, so its site indices cannot be used for this opt-in path.

The `original` output directory contains unmodified GraphChecker artifacts.
The Mallory output directory contains a converted `weave_manifest.json` and
`static_scope_map.jsonl`. Conversion preserves the original selected region
IDs and static READ/WRITE/EXPORT sites, adds the healthy controlling branch
and exact THROW oracle, and includes only verified injectable demanded doors.
Each skipped door is recorded in `analysisGaps`. No legacy Mallory backward
worklist runs in this mode.

## Current semantic boundary

The original GraphChecker analyzer requires a declared communication mapping
for protocols it cannot infer. The first ZK07 run supplied none and produced
zero communication ports. A subsequent system-wide ZooKeeper mapping supplied
two typed ports and produced two original static `wire_handoff` edges. The
mapped REGION_STATE recording weave passed the unchanged original JUnit and
reached the target guard twice. REGION_STATE records field and branch state;
the original pipeline installs communication handoff hooks only in its
task-specific concolic weave. Static ports alone do not prove a runtime
cross-process edge. That proof requires a mapped concolic replay.

## Source-built ZK07 validation

The original source-built engine ran on ZooKeeper 3.8.7's unchanged
`QuorumRestartTest#testRollingRestart`, with `GraphChecker/target` absent from
both the planner's compile classpath and its runtime classpath. It selected
1,316 original regions, 13,177 original static scope sites, 211 demand rows,
and 7 demanded I/O doors. The original static scope artifact was byte-identical
to an earlier run that loaded the same engine through a GraphChecker JAR.
The adapted Mallory manifest selected the healthy branch at
`Learner.registerWithLeader:515`, the explicit `IOException` throw at line
525, and 2 currently verified typed doors. The unchanged healthy JUnit passed
and reached its target check twice.

A one-fault scheduled run selected a restart-epoch occurrence that did not
recur; its status was `unmatched`. A separate exact replay of the observed
startup `FileTxnSnapLog.restore` door emitted one `FAULT_APPLIED` with the
planned site, source, occurrence, ordinal, and `IOException`. That fault
prevented quorum startup, so the JUnit failed before reaching the target
check (`lost_target`). This verifies the source-built analysis-to-weave-to-
injection path; it is not evidence of a target exception bug. The ZK run
is an unmapped diagnostic, not the mapped pilot.

## Exact healthy target occurrence

`MalloryTargetOccurrenceResolver` accepts the original candidate graph,
static scope map, region skeletons, and one CLOSED native healthy trace. It
checks the trace's static artifact digest, runs the original
`RuntimeRegionPlanner.planSkeletonGraph` and selected-skeleton step, then
finds actual branch events for the inventory check in the exact target or
folded owner activation. It chooses the earliest reached event and writes an
address, event sequence, call ID, all reached candidates, and input SHA-256s.
When the scope map declares exactly one controlling guard, the CLI derives
it without a manually supplied `--check-site-id`; ambiguous maps fail closed.
The original Recorder and Scheduler consume that exact address through
`--target-occurrence`. In mapped ZK07, this selected epoch1 branch u51 at
event 120849; the original region plan marks it `observed=true` and emitted
one target task requiring the fatal arm. This is a healthy planning result,
not a fault-induced target failure.

## Original post-run closure

`Corpus.read(iteration, null)` reads native `SessionReader` contract files,
`Branches.of` checks which focused sessions can parent tasks, and
`ClosurePlanner.plan` demands observed values and static may-writers from a
target occurrence. `OriginalClosureSessionTest` writes a native seed session
with two different threads, one versioned shared-state write and read, a
target predicate, and a static target site. It verifies that the original
planner includes the writer in the target closure. This test does not use the
older Mallory trace-to-contract translator. The native feedback adapter is a
separate integration point; adding these classes does not change frozen
campaign behavior.

The Java source closure includes GraphChecker's `Z3` helper because the
compiler dependency graph reaches it. The focused post-run closure test does
not launch an external solver. Broader Explore/Compose solving may require a
`z3` executable; this module does not bundle one. Static planning still needs
target-system bytecode and Soot's dependency classpath. Post-run closure needs
native session files and a static scope map.
