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
`c4a90033c654737206466ed36ce837c5b3c12457`. The 185 files under
`vendor/src/main/java` are the compiler-transitive Java source closure of
`MalloryOriginalSeedBridge` plus `SeedBackwardStaticAnalyzer`; the selection
was obtained by compiling those entry sources with GraphChecker's source tree
on `javac -sourcepath` and **without** a GraphChecker JAR. Per-file upstream
and copied SHA-256 digests are in `UPSTREAM_SOURCES.json`. The only Java source
change is that `SeedBackwardStaticAnalyzer` names its own class, rather than
`CausynthPipeline`, as the SLF4J logger category. That avoids importing the
whole pipeline solely for its logger and does not change analysis behavior.
`src/main/resources/edu/uva/liftlab/graphchecker/library-catalog.jsonl` is
copied unmodified from the same revision. No root-level license file was
present in the source GraphChecker tree at the time of migration; no license
designation is inferred from unrelated `third_party` files.
The resource digest and its upstream digest are also recorded in
`UPSTREAM_SOURCES.json`.

The module's `pom.xml` has only published Soot, Guava, SLF4J and Gson build
dependencies. Its compile and runtime classpaths contain the Mallory module
JAR and these libraries, and contain **no** `GraphChecker/target` JAR.

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
It restores the captured `jtp` Jimple bodies before invoking the original
analyzer because Soot otherwise lowers active bodies to Baf after `runPacks`.

The `original` output directory contains unmodified GraphChecker artifacts.
The Mallory output directory contains a converted `weave_manifest.json` and
`static_scope_map.jsonl`. Conversion preserves the original selected region
IDs and static READ/WRITE/EXPORT sites, adds the healthy controlling branch
and exact THROW oracle, and includes only verified injectable demanded doors.
Each skipped door is recorded in `analysisGaps`. No legacy Mallory backward
worklist runs in this mode.

## Current semantic boundary

The original GraphChecker analyzer requires a declared communication mapping
for protocols it cannot infer. The initial ZooKeeper 3.8.7 ZK07 run selected
27 thread entries and 13 task entries, but produced zero communication call
sites because no ZooKeeper wire mapping was supplied. Therefore this pilot
does **not** establish cross-process causal edges. Its `RootDemand` selected
7 I/O doors; only 2 satisfied Mallory's currently verified typed injection
contract. The other 5 are explicit `original_graphchecker_door_uninjectable`
gaps. These are limitations to address before claiming a complete GraphChecker
port across all systems.

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
still has no established cross-process communication port.
