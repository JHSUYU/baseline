# Source-built native GraphChecker fixture

`run.sh` builds the pinned original GraphChecker sources vendored in
`../static_scope_port/original_engine`, then runs a bounded fixture on the
isolated GraphChecker Zero VM. It uses no live `GraphChecker/target` JAR.
The original `ConcolicRegionRuntime` opens a root and records a branch; the
original `RowRuntime` publishes the session, and `SessionReader` verifies the
activation, decision, target, and expression references. The expression log
must contain a VM-authoritative guarded read-from expression.

Run `./run.sh`, optionally setting `GC_ZERO_VM` to an isolated compatible VM
image. The script prints its scratch directory under `/dev/shm` so the exact
session remains available for inspection. The fixture invokes the hook
contract explicitly; it establishes runtime and VM capability, not automatic
Soot weaving of an unchanged JUnit.

`./run_unmodified_junit.sh` exercises the separate opt-in native weave.
`PlainFixture` and `PlainFixtureTest` contain no instrumentation calls. The
script pins their original Jimple sites, invokes the original GraphChecker
`CausynthPipeline` from Mallory's source-built JAR through
`native_original_weave.py`, and runs the unchanged JUnit on the isolated VM.
It checks the source-built weave receipt, native target and decision rows,
one write row, and a VM-authoritative exact read-from expression. The healthy
branch takes the nonfatal outcome; a branch marker alone is not an exception
oracle. Session startup and source attribution are provided by an external runner, as they
would be by a system adapter. The fixture does not have a work handoff and
does not establish that system adapters supply correct source binding.

`native_original_weave.py --prepare-engine` is a separate build step. It
records the vendored source tree, source-built JAR, and Maven dependencies in
an engine receipt. A case weave requires that receipt and never calls Maven.
It runs Soot once and records exact hashes for the original and woven class
trees, task plan, region skeletons, Java executable, and dependency inputs.
`native_original_weave.py --config CASE.json --verify-only` checks the receipt
without invoking Maven or Soot; the fixture proves that tampering with either
class tree is rejected. Trials must reuse the already woven output after this
gate and collect their own fresh native sessions. This opt-in path is not yet
selected by the 102-case campaign driver.

An optional `post_weave` stage lets a system-level adapter add actor binding
after the original GraphChecker weave, before the final class hash is taken.
The adapter main class and its classpath inputs are also pinned. The fixture
executes this stage with a validation-only adapter and rejects tampering with
its compiled class.

The two-trial proof is archived at
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/diagnostics/native-unchanged-junit-postweave-b41d9a64-20261013`.
Both independent session manifests have one activation, decision, target,
and write row; the target's `observedFatal` is false. The two sessions share
one weave receipt (SHA-256
`c72e054441ae7c5baa6b3585fbf3dfc6d56afc7d89a3ce7f9e2e8d4d43794286`).

An isolated ZooKeeper 3.8.7 `QuorumRestartTest#testRollingRestart` pilot
used the same opt-in wrapper to weave an unchanged `Learner.class` from the
frozen source-built engine. The original Jupiter test passed twice on the
isolated Zero VM, in 45.3 and 42.4 seconds. The native hook saw four
`Learner.registerWithLeader` roots, but the task's synthetic peer occurrence
did not match their runtime source and request context. The original runtime
therefore refused those roots and emitted no native activation, decision, or
target rows. This is a MiniCluster source-binding gap, not evidence that the
target was checked by the native campaign. Exact refusals and receipts are
archived at
`/proj/silentfailure-PG0/ZhenyuLi/Mallory/diagnostics/native-zk07-b41d9a64-20261013`.
