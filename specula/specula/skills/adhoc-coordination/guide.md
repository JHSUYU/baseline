# Checking One Ad Hoc Coordination Check

In ad hoc coordination, the components of a distributed system keep the states an operation depends on consistent without an explicit protocol, and developers guard that consistency with local checks: an exception thrown, an assertion, a `Preconditions` call. When the coordination breaks, the check fails.

In this mode, the run is anchored at one such check, the **target**. The question is not "is the whole protocol correct" but:

> Can an execution of the system, under faults in its fault model, reach the target's failing branch?

The target file named by the launcher prompt (`--adhoc-target`) gives the check, the workload test that exercises it without failing, and a starting set of classes. Its format is in `references/target-file-format.md`. Read it first.

## Shared Rules

1. **The target's failing branch is the oracle.** The model's correctness property is "the target check never fails": `TargetSafe == ~targetFired`. Do not invent unrelated protocol invariants as hunting targets. One or two structural sanity invariants are allowed to keep the model honest (see `references/tla-patterns.md`).
2. **No answer leakage.**
   - **Phases 1-3** (analysis, spec, harness, validation): do not search git history, the issue tracker, mailing lists, or the web for anything about the target: its file and line, its exception message, the code that computes the guard's values, or fixes touching any of them. Do not read any other tool's output about this target. Git history of code unrelated to the target may be used for general understanding of a component.
   - **Phase 4**: the bug-confirmation skill's novelty step may search the tracker and history, but only after the reproduction verdict is settled. Record every query in `investigation.md`. The search may set the Novelty field only; it must not change the reproduction or the verdict.
   - **Always**: the source tree is pinned at the target file's `base_commit`; do not check out another revision.
3. **Model the implementation, not the design.** Every guard, update, and message in the model cites `file:line` in the pinned tree.
4. **The workload is the anchor for traces and reproduction.** The named workload test reaches the target's method without failing the check. Trace validation and reproduction start from this test (or a minimal variant of it in the same module) so the model stays tied to an execution the system really performs.
5. **Phase ownership.** This skill changes how each pipeline phase is scoped. It does not authorize running a later phase. Complete only the phase the launcher assigns, and finish with that phase's ordinary output contract so the next phase can consume it.

## Phase 1: Code Analysis

Follow the installed **code-analysis** skill, with these changes only:

- Skip its Bug Archaeology phase, and any history or issue lookup about the target (Shared Rule 2).
- **§1 of `modeling-brief.md`** also names the target (file, line, method, thrown type), the failing predicate `phi_T`, and the workload. Write `phi_T` from the guard as the code evaluates it: the condition under which the failing branch executes.
- **§2 Scenarios** are hypotheses for how the failing branch could be reached. Their **Evidence** is code analysis only, with `file:line`; never history of the target.
- **§5 Proposed Invariants** puts `TargetSafe` first, followed by at most two structural sanity invariants.
- **§6.1 Model-Checkable** has one finding per Scenario, phrased as "can Scenario N make `phi_T` true?".

The target file's `scope_hint` classes are a starting set, not limits.

## Phase 2: Spec Generation

Follow the installed **spec-generation** skill. Read `references/tla-patterns.md` from this skill first. Then:

- Add the variable `targetFired`.
- Model the code path that reaches the check as an action `TargetCheck`. It is enabled when that path is taken, evaluates the guard exactly as the code does, and sets `targetFired' = TRUE` when the failing branch is taken.
- `TargetSafe == ~targetFired` is enabled in `MC.cfg` only after the sanity checks of `references/tla-patterns.md` §2 pass, and in every `MC_hunt_*.cfg`.
- Each Scenario gets one `MC_hunt_<scenario>.cfg` that sets only that Scenario's counters.

## Phase 2.5: Harness Generation

Follow the installed **harness-generation** skill. Read `references/java-harness.md` from this skill for Java, Maven and Ant specifics. Rules:

- Drive traces with the target's workload test, run as written, plus at most two small variants in the same test module.
- Variants must not write the target guard's operands.
- Never modify the target check itself.

## Phase 3: Validation and Hunting

Follow the installed **validation-workflow** skill unchanged, with three additions:

- Hunting focuses on `TargetSafe`. A `TargetSafe` violation is the primary finding type: its `findings.json` entry names `TargetSafe` as the violated invariant and the Scenario it came from.
- When a hunt config ends with no violation, record in `bug-report.md`:
  - the bounds explored, distinct states, diameter and wall time;
  - why the explored bounds cover the Scenario, or what was left out.

  A bounded "no violation" is a legitimate result for an ad hoc check.
- A counterexample whose trigger is outside the system's fault model (for example, an operator setting an invalid configuration value) is a Case B model issue, not a bug.

## Phase 4: Confirmation

Follow the installed **bug-confirmation** skill. The same-bug test is strict and replaces the generic one:

- A reproduction confirms a `TargetSafe` finding only if the real system throws the target's exception type from the target's file and line. Show the stack trace frame (class, method, line) in the evidence.
- The reproduction must start from the target's workload test or a variant of it in the same module. It may inject only the faults the counterexample uses, with the test utilities the codebase already uses.
- It may control timing and order with the codebase's own test utilities to realize the counterexample's order.
- It may not:
  - write the guard's operands directly;
  - edit the target method;
  - inject a state the system cannot reach through its own APIs and the counterexample's steps.
- Keep the persistent proposal's `title` at most 160 characters, and run the findings validator on `issue.json` before you finish. A rejected proposal discards the finding's verdict.

## Phase 4b: Classification and the Ad Hoc Result

After the normal **bug-classification** outputs, when the launcher assigns this responsibility, write `.specula-output/adhoc-result.json` in the format of `references/adhoc-result-format.md`. It summarizes, for the target, whether the check was shown reachable, how, under which bounds, and with what evidence. Do not change any verification artifact while writing it.
