# Native GraphChecker campaign core

This is an isolated, opt-in campaign driver. It does not modify the frozen
`Mallory/core` campaigns or the original JUnit workload.

## Admission and one-time instrumentation

An external preparation step runs the original GraphChecker `REGION_STATE`
recording weave on the unmodified JUnit and closes its trace. It runs the
original `CausynthTraceRecorder` and `ConcolicScheduler` to derive
`execution_task_plan.jsonl` from the healthy execution. The original
`CausynthPipeline` then weaves a separate class tree once for that selected
task. The `native_original_weave.py` receipt pins that class tree, task plan,
source-built engine, weave dependencies, and Java executable. The campaign
checkpoint also pins the JUnit runner classpath and Zero VM executable.

At campaign admission this driver verifies the immutable weave receipt,
re-runs the original recorder and scheduler, and requires byte-identical
scheduled tasks and selected region skeletons. It refuses a manually written
task occurrence. The source-built engine must contain the original scheduler;
the older seed engine that omits it cannot pass admission. In particular, old
ZooKeeper pilot static artifacts with synthetic lambda names are not accepted
as a recording-derived campaign seed.

`recording-admission.json` saves the successful admission. A resumed campaign
reuses it after hashing every file in the closed healthy recording, the static
inputs, pinned weave receipt, scheduler source, and engine JAR. A changed input
causes refusal. Recorder and scheduler run once for that immutable input set;
they do not run at each resume or trial.

Every trial starts a fresh Zero VM process on the same JUnit class and method,
using the same woven classes, task plan, and task ID. There is no trial-time
Soot or weave. Each process emits a fresh native session. The driver invokes
`Mallory.native_graphchecker_feedback.summarize_target_set` and `delta` on
that session, compares observed target closure families and branch outcomes,
and updates a persistent fault queue. It gives most queue slots to observed
closure doors and reserves one in eight fault trials for doors outside it.

## Input contract

Call `run_campaign(Path("case.json"), Path("case-output"))` or run
`python3 -m Mallory.native_graphchecker_campaign --config case.json --output case-output`.
The manifest has
the following shape (paths are absolute in an actual campaign):

```json
{
  "case_id": "CASE-01",
  "target_site": "exact GraphChecker anchorSiteId",
  "target_throw": {
    "siteId": "exact throw site ID",
    "exceptionClass": "java.io.IOException"
  },
  "target_actor_names": ["optional physical actor name"],
  "native_weave_config": "/path/to/verified-native-weave.json",
  "recording": {
    "trace_dir": "/path/to/closed-region-state-trace",
    "test_id": "original JUnit ID in trace",
    "target_name": "recorded target name",
    "candidate_graph": "/path/to/candidate_dataflow_edges.jsonl.gz",
    "static_scope_map": "/path/to/static_scope_map.jsonl",
    "region_skeletons": "/path/to/region_skeletons.jsonl.gz",
    "max_jobs": 256
  },
  "junit": {"class": "OriginalTest", "method": "testOperation"},
  "runner": {
    "zero_vm_java": "/path/to/zero-vm/bin/java",
    "main_class": "JUnit runner main class",
    "classpath": ["/path/to/test-classes", "/path/to/dependencies.jar"],
    "jvm_args": []
  },
  "budget": {"fault_trials": 32, "seconds": 7200,
             "max_faults_per_trial": 3},
  "timeout_seconds": 300
}
```

`recording.target_occurrence` is optional only when the original recorder and
scheduler can select the recorded occurrence without ambiguity. The selected
task ID comes from the pinned weave configuration, never from a refusal log.

The fault adapter is a separate contract. It reads `MALLORY_NATIVE_FAULT_PLAN`
and writes monotone JSONL events to `MALLORY_NATIVE_FAULT_EVENTS`. A plan item
selects `siteId`, physical actor `node`, zero-based `actorEpochOrdinal`
(increments after that actor restarts), event `ordinal` in that epoch, and
`exceptionClass`. It also retains `sourceOccurrenceId` as provenance from the
prior trial. The adapter binds this selector to a fresh exact
`occurrenceId` in the current JVM and emits both `FAULT_DOOR` and
`FAULT_APPLIED` with that same exact identity. A target
exception is reported by a `TARGET_THROW` receipt with exact `siteId`,
`exceptionClass`, and target `occurrenceId`. An exit code, assertion failure,
or GraphChecker `observedFatal` flag is not a target exception. The driver
requires the entire planned fault sequence to match applied receipts in
order and the native target to remain reached. To label a trial `candidate`,
the last applied fault must precede an exact `TARGET_CHECK` receipt for a
reached target in the same occurrence and actor epoch, and that occurrence
must later produce the exact `TARGET_THROW`. All three receipts use one
monotone event stream. A fault in a different occurrence of the target's
closure needs separate causal and endpoint-order proof; closure membership
alone is not enough. Observed WIRE and STATE edges identify their endpoints,
but their native VM event IDs cannot currently order a fault receipt against
the producer endpoint. Such trials remain `needs_causal_review`. The native
target row's VM event ID is not compared with the fault receipt sequence.

## Checkpoints and status

`checkpoint.json` is atomically replaced after each trial and records the
queue, cumulative closure feedback, budget, active trial, and result links.
An interrupted run resumes from a completed `result.json` without rerunning
the JUnit. If a recorded JVM is still alive, resume refuses a duplicate.
An incomplete stopped trial is moved to `interrupted/` before a new attempt.
Each trial keeps process logs, the exact fault plan and receipts, native
session, summary, and result. `summary.json` is written at terminal status.

The fixture tests exercise zero fault and one generic fault, exact receipt
matching, target loss, fresh JUnit invocation, and restart behavior:

```bash
python3 -m unittest Mallory.native_graphchecker_campaign.test_campaign -v
```

These fixture tests do not establish a system campaign result. A real fault
trial still requires a transport or I/O adapter that emits the typed receipt
at the actual event, plus a new immutable static scope and recording-derived
weave that passes admission.
