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
Soot weaving of an unchanged JUnit. It makes no claim about ZK07 end-to-end
execution, which currently fails during quorum startup on the Zero VM before
the target region.
