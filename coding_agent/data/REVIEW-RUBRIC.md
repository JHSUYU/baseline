# Review of a validated reproduction

A case is "validated" when the agent's test, run on an unmodified copy of the system, throws the check's
exception at the check's line. This review decides whether that failure is a **real bug found by realistic means**.

For case `<c>` read:
- `/bulk/codingagent/cases/<c>/target.yaml`: the check (file, line, method, exception, condition) and the starting test;
- `/bulk/codingagent/cases/<c>/agent/result.json`: the agent's claimed execution and why it is a bug;
- `/bulk/codingagent/cases/<c>/validation.json`: `changed_files` (the agent's test files, relative to the tree) and the
  matched exception line and frame;
- the test files themselves under `/bulk/codingagent/cases/<c>/agent/<tree>/` and the production code they exercise
  (the tree's production sources are unchanged; `git -C <tree> status` shows only the agent's files).

Judge, reading the code yourself (do not trust the agent's explanation):

1. **Realistic trigger.** Allowed: mini clusters; crashing, stopping or restarting nodes; a request, RPC or I/O call
   that fails, times out or is lost (e.g. a Mockito spy or test hook throwing at an I/O/RPC boundary); delays or latches
   that force an interleaving the real scheduler can produce; valid configuration values; clock skew between nodes
   where the system reads wall-clock time; ordinary client operations, including concurrent ones.
   Not allowed: reflection or similar to set system state the system cannot reach by itself; calling the check's
   method (or an internal method that feeds it) directly with fabricated arguments; mocks or subclasses that make a
   system component return values or behave in ways the real component never can; faults inside a single atomic
   local step that no crash or failure can produce; test-only shortcuts that skip the system's own protocol.
2. **A bug, not a correct rejection.** The check fails because the coordination produced state that a correct
   coordination should not have produced, with a consequence (an operation that should succeed fails for good or
   repeatedly, data loss or corruption, a wedged/crashed component, lost availability). It is NOT a bug if the check
   is doing its job by design (e.g. it fences a stale/zombie request, rejects an invalid user request, or the failure
   is transient and the system retries/recovers on its own, or the documented behaviour is to fail and the caller
   handles it).
3. **Severity** if a bug: data loss/corruption, outage/wedged component, operation failure (lasting), minor.

Write `/bulk/codingagent/cases/<c>/review.json`:
```
{"case": "<c>", "verdict": "BUG" | "BY_DESIGN" | "UNREALISTIC" | "UNCLEAR",
 "trigger": "<the trigger in one or two sentences>",
 "reason": "<why this verdict, citing file:line of the decisive code>",
 "severity": "data-loss" | "outage" | "operation-failure" | "minor" | null,
 "summary": "<one-line description of the bug, if BUG>"}
```
