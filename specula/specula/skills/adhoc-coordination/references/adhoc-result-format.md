# `adhoc-result.json`

One JSON object, written last, in `.specula-output/`. It summarizes the run for the target. Every claim in it points to an artifact that already exists.

```json
{
  "schemaVersion": 1,
  "target": "<target id>",
  "check": {"file": "<path>", "line": 123, "thrown": "<exception type>"},
  "verdict": "REACHED_CONFIRMED",
  "mechanism": "<one value from the list below>",
  "scenario": "Scenario N: <name>",
  "finding": "MC-1",
  "counterexample": "spec/output/<file>.out",
  "reproduction": "repro/test_bugMC-1_<name>.java",
  "stackFrame": "<package>.<Class>.<method>(<File>.java:123)",
  "bounds": [{"config": "MC_hunt_<scenario>.cfg", "result": "VIOLATION", "states": 123456, "diameter": 17, "seconds": 210}],
  "traceValidation": {"traces": 3, "passed": 3},
  "notes": "<one paragraph: chain of events, or why nothing was found>"
}
```
## `verdict` values

| value | meaning |
| --- | --- |
| `REACHED_CONFIRMED` | A `TargetSafe` counterexample was reproduced in the real system. The target's exception was thrown at the target's line, under the rules of the skill's Phase 4. |
| `REACHED_UNCONFIRMED` | A `TargetSafe` counterexample exists, but reproduction did not succeed. Give the reason in `notes`, for example ENV_LIMITED or NEEDS MORE INFO. |
| `MODEL_ARTIFACT` | Every `TargetSafe` counterexample was judged a modeling artifact (FALSE POSITIVE or MASKED), and none was confirmed. |
| `NOT_REACHED_BOUNDED` | No hunt config violated `TargetSafe` within the reported bounds. |
| `BLOCKED` | The run could not reach a checkable model or harness. Give the reason in `notes`. |

## `mechanism` values

`FAULT`, `CLOCK`, `RESTART`, `INTERLEAVING`, `CONFIG`, `BRANCH`, `COMBINED`, or `null` when nothing was reached. Use `COMBINED` when the trigger needs more than one kind; list the kinds in `notes`.

## Fields that may be `null`

`finding`, `counterexample`, `reproduction`, `stackFrame` and `mechanism` are `null` when they do not apply. `bounds` lists every hunt config that ran.
