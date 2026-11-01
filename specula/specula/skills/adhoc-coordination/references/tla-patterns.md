# TLA+ Patterns for an Ad Hoc Target

These patterns extend the spec-generation skill's `base-spec-methodology.md` and `mc-spec-pattern.md`.

## 1. The target

```tla
VARIABLE targetFired

TargetCheck(n, req) ==        \* <Class>.<method> L..L
  /\ <the code path that reaches the check>
  /\ IF <guard exactly as the code evaluates it>
       THEN targetFired' = TRUE                    \* throw new <Exception>(...) at L
       ELSE /\ targetFired' = targetFired
            /\ <the normal continuation of the method>

TargetSafe == ~targetFired
```

Once `targetFired` is TRUE, every other action may stop (`/\ ~targetFired` in `Next`); this keeps counterexamples short.

## 2. Sanity and convergence

Before hunting, `MC.cfg` with every fault counter at 0 must:

- pass the structural invariants (types, and "a message carries only values its sender held");
- satisfy `TargetSafe`, since the workload passes;
- reach `TargetCheck` at all: add `TargetReached` as a temporary `~(state where TargetCheck is enabled)` invariant and confirm TLC violates it.

A model that never enables `TargetCheck` proves nothing.

## 3. Hunt configs

Each Scenario gets one `MC_hunt_<scenario>.cfg`, which:

- enables `TargetSafe`;
- sets only the counters that Scenario uses, for example `MaxFaults = 1`;
- keeps every other counter at 0.

Report the bounds with each result.
