# GraphChecker-style JUnit weave for Mallory

This module rewrites only sites selected by a JSON manifest in compiled
application/test classes. `WeaveMain` uses Soot Jimple, keeps source lines, and
refuses a selected target or door that resolves to zero or multiple original
instructions. The original JUnit 4 runner, rules, setup and teardown remain
the workload. `JUnitTrialMain` opens the trace before JUnit cluster setup and
exits the test JVM after teardown, because embedded clusters can leave
non-daemon threads running.

Build after installing `Mallory/graphchecker-runtime`:

```sh
mvn -q -f Mallory/graphchecker-runtime/pom.xml install
mvn -q -f Mallory/instrumentation/graphchecker_port/pom.xml test
```

Weave and run with the module and runtime dependencies on the classpath:

```sh
java -cp "$TOOL_CP" edu.uva.liftlab.mallory.graphchecker.weave.WeaveMain \
  sites.json original-classes woven-classes "$TEST_CP"
MALLORY_GC_TRACE=trial.jsonl java -cp "woven-classes:$TOOL_CP:$TEST_CP" \
  edu.uva.liftlab.mallory.graphchecker.weave.JUnitTrialMain \
  org.example.ClusterTest testOperation
```

The manifest contains `regions`, `targets`, `coverage`, `frames`, `doors`, and
optional `stateCandidates`.
Every site identifies a class, method and JVM descriptor. A target also has
`kind` (`BRANCH`, `SWITCH`, or `THROW`), source `line`, and `siteId`; a door has a source
`line`, exact Soot `callee` signature, and `siteId`. An optional `unitIndex`
pins a site to one Jimple instruction at the `jtp` pack entry. The static scope
producer must use the same Soot phase, options, and input bytecode. Run
`InspectSitesMain <classes-dir> <dependency-classpath> <class> <method+JVM-descriptor>`
to inspect those exact indices. If the static manifest includes
`sootDependencyClasspathSha256`, `WeaveMain` checks the exact ordered
dependency classpath string before touching classes; different Soot hierarchy
inputs can shift Jimple indices. Before output, the weaver narrows each original
typed catch to the first and last operations that Soot's throw analysis says
can raise its caught type. This preserves the caught operations while avoiding
Soot StackMap failures where a catch range starts before a local used by its
handler is initialized. The verifier regression covers a live integer in an
original catch and a selected `FileReader` constructor door. `frames` selects
methods whose original calls get balanced execution-index frames. Each call
uses an opaque runtime receipt, so a request or tick scope opened or ended
inside the call can be restored without leaving a stale caller frame. The weave
accepts `sourceOwner` on each region (`CURRENT` or `THIS`); `THIS` requires a
source alias registered for the method receiver by the system adapter. The weave
records actual branch arms (`TRUE` and `FALSE` in Jimple condition terms),
explicit target throws, selected region activations, coverage, and fault doors.
Region exits are balanced internally; the runtime materializes an activation
row only when an observation uses that exact occurrence.
Selected branch coverage fires only on a taken arm; `COVERAGE` carries
`branchSiteId` and boolean `outcome` for `if` branches. Switch coverage uses
`siteId/CASE:value` or `siteId/DEFAULT`.
It does not infer successful RPC sends or state versions from these hooks;
those are the protocol adapters' responsibility.
Executed `stateCandidates` emit `STATE_ACCESS_UNHOOKED` GAP rows, once per
site/access/field and at most 256 distinct candidates per trial JVM. A single
truncation GAP reports further sites. These hooks do not claim a read-from
relation or produce exact STATE edges.

`faultController` is `NONE` by default. Set it to
`MALLORY_GC_FAULT_PLAN` for the native controller. Pass
`MALLORY_GC_FAULT_PLAN=/path/plan.json` to each fresh trial JVM. The plan is:

```json
{"faults":[{"siteId":"door-id","node":"node-id#epoch0","occurrenceId":"seed-occurrence-id","ordinal":1,"exceptionClass":"java.io.IOException"}]}
```

Each fault must match the exact observed GraphChecker door identity and is
applied once in array order. `ordinal` is one based for the door within its
occurrence. `FAULT_APPLIED` uses the same occurrence, node, site, and ordinal
as `FAULT_DOOR`. The exception class must match the selected manifest door.
If the seed door supplies `replayOccurrenceId`, a plan may include it and the
controller matches that stable cross-trial selector instead of the seed's
exact occurrence. The actual `FAULT_APPLIED` row still records the trial's
exact occurrence and the replay ID; graph joins always use exact identity.
The controller fails on a missing or malformed plan; an unattributed door
cannot receive a fault.
Selected constructor sites before the actual `this` or `super` initializer
returns cannot carry the receiver as a source. The weave emits bounded
`PREINIT_HOOK_UNATTRIBUTED` GAP rows for such doors, targets, and coverage,
and does not inject at those doors. This preserves JVM verification and makes
the untested scope explicit. A resource constructor called after the enclosing
method's own initialization, such as `new FileReader(file)`, can be selected
as a door; the verifier fixture runs that pattern with all-call framing.

The legacy `MALLORY_PROBE` controller calls the
existing `Probe.beforeDoor(siteId, exceptionClass)` after recording each
GraphChecker `FAULT_DOOR`. In that mode the old `Probe` class must be on the
trial classpath, and its old Java agent transformer must not instrument the
same doors a second time. A fault thrown by Probe goes through the woven
call's exception handler, which pops its call frame and then follows the
original application catch. The smoke test covers a JUnit catch around a
woven call and checks that the target still records before the test finishes.
The legacy Probe receipt does not share GraphChecker occurrence identity and
should not be used for exact-identity result claims.

This module does not implement GraphChecker's static backward slice or its
cross-thread/process carrier mapping. It consumes the selected sites and
records exact observed runtime events. The static scope map and system
protocol adapters must be supplied separately; absent identity creates a
trace gap rather than an inferred edge.

`JUnitTrialMain` runs original JUnit 4 methods. JUnit Jupiter tests need a
JUnit Platform runner that opens/closes `MessageDoors` around the full
extension and MiniCluster lifecycle; the offline weave itself is independent
of the JUnit version.
