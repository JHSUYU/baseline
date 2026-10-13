# GraphChecker static selection migration (experimental)

This migration lives inside `Mallory/static_scope_port` and is disabled unless
`analysis.graphchecker_region_port=true`. It does not change the default
`ScopePlanner` output or any pinned campaign jar. The source baseline is
GraphChecker revision `c4a90033c654737206466ed36ce837c5b3c12457`.

## Source provenance

`GraphCheckerRegionPlanner` ports executable algorithms from these original
GraphChecker methods:

| Original source | Migrated method | Adaptation |
| --- | --- | --- |
| `StaticProgram.closure` | `closure` | FIFO/early-stop body copied with equivalent Java collections. |
| `StaticProgram.invocationTarget`, `declaredField` | same private methods | GraphChecker edge names retained. |
| `SymbolicRegionPlanner.Anchors`, `root`, `addSkeleton` | `Anchors` | `StaticProgram` mutable state replaced by explicit `Input`/`Result`; GraphChecker's root/anchor/selection order retained. |
| `SymbolicRegionPlanner.forwardClosure`, `failureRelevantState`, `fold` | same private methods | GraphChecker traversal and demanded-state logic retained; constant fields supplied explicitly rather than looked up in Soot `Scene`. |
| `SymbolicRegionPlanner.declareCommunicationPorts` | same private method and `declareWireEndpoint` | Producer OUT / consumer IN and capture identity retained; unresolved captures become explicit gaps. |
| `RegionSkeletonInstrumentationSelection.regionRootsFromEnvironment`, `methodsFromEnvironment` | `Result.regionRoots`, `instrumentedMethods` | Reads the in-memory selected skeletons instead of a file. |

The new `ScopePlanner.graphCheckerRegionPort` bridge is **new adapter code**,
not a GraphChecker source copy. It exports selected Soot Jimple call, field,
local, controlling-branch and port-capture facts into GraphChecker's edge
shape, invokes the ported planner, and writes four separate files:

* `graphchecker_static_facts.json`
* `graphchecker_region_skeletons.json`
* `graphchecker_static_scope_map.jsonl`
* `graphchecker_weave_manifest.json`

This is a switchable region-selection version, not yet a replacement for
GraphChecker's full `SeedBackwardStaticAnalyzer`. In particular, the bridge
does not yet copy that analyzer's complete value demand, exact formal/actual
and returned-value jumps, or all of its RPC service/protobuf leaf-port
derivation. The legacy Soot scope first selects candidate units and ports;
the migrated region planner consumes their exported facts. A port with no
selected producer/consumer is not promoted into a proven causal edge.

The source audit follows GraphChecker's actual `CausynthPipeline` ordering:
`SeedBackwardStaticAnalyzer.analyze()` creates value/call/wire edges;
`SymbolicRegionPlanner.planSelectedSkeleton()` selects authorities and
region skeletons; `StaticScopeMap.sites()` converts those edges and regions
into instrumentable sites; `RegionSkeletonInstrumentationSelection` reads
the selected skeletons during weaving. GraphChecker's protobuf RPC rule in
`SeedBackwardStaticAnalyzer.deriveWirePort` links a demanded getter on an
RPC-carried message to all matching `M$Builder.setF` argument captures.
Its `propagateCallArguments`/`propagateCallReturns` add formal/actual and
return-value edges, while `resolveDispatchTargets` admits type-compatible
implementations. Those value-demand and RPC derivation methods have **not**
yet been transplanted into this switch. The bridge uses the legacy planner's
candidate port catalog for now. Thus this version tests the migrated
GraphChecker region decision with real Jimple facts, but it is not yet a
complete replacement for GraphChecker's full backward slice.

## Verification

`mvn -q test package` runs 13 passing tests, including three migrated
GraphChecker skeleton fixtures and an opt-in Soot fixture that selects a
real `BufferedReader.readLine` door while the default path remains unchanged.

An isolated ZOOKEEPER-07 run used the unchanged original JUnit class and
the exact ordered classpath of the pinned ZooKeeper 3.8.7 campaign. The new
static run finished in about 25 seconds. It exported 30,464 edge facts and
selected 11 skeleton roots, 1,043 frame methods, 67 typed doors, and both
target sites (`Learner.registerWithLeader` branch `#u51`, throw `#u66`). The
default manifest from the same run had 3,061 method regions and 280 doors.
The generated manifest passed `WeaveMain`; the post-weave adapter ran, and
the unchanged `QuorumRestartTest#testRollingRestart` healthy JUnit passed and
reached the target branch. Artifacts are under
`/dev/shm/mallory-gc-migration-zk07-v3-out` and
`/dev/shm/mallory-gc-migration-zk07-v3-campaign`.

The first one-fault campaign exposed a compatibility bug in the older graph
analyzer JAR: it lacked `--healthy-summary`, interpreted the healthy archive
as an output path, and truncated it. The runner now probes that capability
before using the command. With immutable analyzer
`graphchecker-runtime-d975fc8c3e2ab774.jar` (SHA-256
`d975fc8c3e2ab774a636fdd626c09e24765b8082aac01641b156511addcf5644`),
an isolated fresh one-fault campaign completed. Both archived healthy traces
retained their receipt sizes and SHA-256 values. The healthy original JUnit
passed and reached the target. The fault trial passed the unchanged JUnit,
strictly applied its one selected `IOException` fault at
`Learner.registerWithLeader#u24`, reached the target branch afterward, and
placed the fault occurrence in the target's causal closure. The target throw
did not fire. Its receipt is
`/dev/shm/mallory-gc-migration-zk07-v3-d975-campaign/trials/r0001/result.json`;
the full campaign summary is in the same root. This verifies one target
preserving fault trial; it does not establish full budget behavior or bug
detection.
