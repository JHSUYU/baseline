# Native GraphChecker fault adapter

The production insertion point is `MalloryNativeFaultWeave` in the vendored
GraphChecker engine. An opt-in `native_fault_manifest` names the static scope
planner's selected I/O calls and THROW targets. A capture phase resolves each
`unitIndex` to its original Jimple `Unit` before GraphChecker transforms the
body. An insert phase places a hook immediately before that same `Unit` after
the original GraphChecker pass. Missing classes, methods, units, lines, or
callees stop the weave. The bytecode fixture writer in `src/test` is not used
by the campaign; same-line bytecode calls without exact offsets are ambiguous.

At runtime, `NativeFaultHooks` uses GraphChecker `Attribution`, `Identity`,
and `RowRuntime`. Each selected I/O reports `FAULT_DOOR` with the static
site, physical actor, actor epoch, ordinal, and fresh occurrence ID. A planned
exception reports `FAULT_APPLIED` with the identical identity before it is
thrown at the I/O door. A selected actual `ATHROW` reports `TARGET_THROW`.
The selected target branch reports `TARGET_CHECK` immediately before its
`IfStmt` in that same event stream, with the original target anchor site and
exact occurrence ID. Thus a trial can prove the applied fault precedes a
reached target within one occurrence; the target row alone has a separate
GraphChecker sequence clock.
After `RowRuntime` accepts an export or attach row, its optional observer
emits `ENDPOINT_EXPORT` or `ENDPOINT_ATTACH` in that same local receipt
clock. The receipt carries the original endpoint ID, occurrence ID, physical
actor, session ID, and VM event ID. A mismatched current actor or occurrence
is a lineage gap, not a temporal proof. The campaign can use these markers
with original directed wire edges to check fault-before-export and
attach-before-target order across occurrences.
Unknown actor or occurrence attribution emits a GraphChecker gap and refuses
the fault. A JUnit failure alone never counts as an applied fault or target
throw.

The weave is immutable across trials. `native_original_weave.verify_existing`
checks the manifest hash, process class directories, engine, and woven output
without invoking Soot. Every healthy or faulted JUnit uses a fresh process,
session directory, plan, and event file. The adapter JAR must be included in
both the weave dependency classpath and the JUnit runtime classpath.

## Verification

`mvn -q -f Mallory/native_fault_adapter/pom.xml
-Dnative.engine.jar=/path/to/pinned-engine.jar test package` exercises two
fresh JVMs, exact door/applied/target-throw receipts, accepted export and
attach endpoint receipts, and the original `SessionReader`. `python -m unittest
Mallory/native_fault_adapter/test_native_weave_contract.py` checks read-only
pretrial verification and rejection of a changed static manifest.

The ZooKeeper unchanged JUnit `QuorumRestartTest.testRollingRestart` was also
run on one Soot-woven class tree with a healthy plan and two fault plans.
Its source-selected `Learner.registerWithLeader` I/O hooks produced exact
physical actor and occurrence receipts. A pre-target fault in the target's
own occurrence prevented that target check from being reached, so that trial
is excluded from closure-guided results. See `evidence/zk07_gate.json` for
the receipt summary and pinned JAR hashes.
