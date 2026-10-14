# Native GraphChecker campaign core

This is an isolated, opt-in campaign driver. It does not modify the frozen
`Mallory/core` campaigns or the original JUnit workload.

## Admission and one-time instrumentation

For `REGION_STATE`, the original `CausynthPipeline` weaves a class tree once
without a concolic task. The unmodified JUnit then produces a closed healthy
trace; the original `CausynthTraceRecorder` and `ConcolicScheduler` derive
`execution_task_plan.jsonl` from that trace. Concolic mode still requires a
recorded task plan and task ID at weave time. The `native_original_weave.py`
receipt pins the woven class tree, source-built engine, dependencies, Java
executable, and any concolic task supplied to the weave. The campaign
checkpoint also pins the JUnit runner classpath and Zero VM executable.

At campaign admission the default mode verifies the immutable weave receipt,
re-runs the original recorder and scheduler, pins the generated schedule, and
checks selected region skeletons. Concolic mode additionally requires the
woven task to match a generated schedule row. It refuses a manually written
task occurrence. For a `REGION_STATE` weave with no concolic task, set
`recording.admission_mode` to `region_state_no_schedule`. This opt-in mode pins
the closed healthy trace and static inputs without precomputing a task plan;
the fresh `r0000` JUnit must then pass and reach the exact target, and its
original Resolver, Recorder, and Finalizer graph must succeed before any fault
enters the queue. Every fault trial uses those same original graph stages.
Existing scheduled REGION_STATE and concolic checkpoint semantics are unchanged.
An optional `recording.analysis_engine_jar` with
`recording.analysis_engine_sha256` may select a source-built compatible
GraphChecker JAR for the per-trial REGION_STATE Resolver and Recorder. This
does not change the original JAR or receipt used to verify the woven class
tree. Admission and each trial verify the analyzer's SHA-256; the analyzer
path and digest are stored separately in the admission fingerprint. Without
these keys, the original woven engine is also the analyzer.
The source-built engine must contain the original scheduler;
the older seed engine that omits it cannot pass admission. In particular, old
ZooKeeper pilot static artifacts with synthetic lambda names are not accepted
as a recording-derived campaign seed.

`recording-admission.json` saves the successful admission. A resumed campaign
reuses it after hashing every file in the closed healthy recording, the static
inputs, pinned weave receipt, scheduler source, and engine JAR. A changed input
causes refusal. Recorder and scheduler run once for that immutable input set;
they do not run at each resume or trial.

Every trial starts a fresh Zero VM process on the same JUnit class and method,
using the same woven classes. Concolic mode also reuses its task plan and task
ID. There is no trial-time
Soot or weave. Each process emits a fresh native session. The driver invokes
`Mallory.native_graphchecker_feedback.summarize_target_set` and `delta` on
that session, compares observed target closure families and branch outcomes,
and updates a persistent fault queue. It gives most queue slots to observed
closure doors and reserves one in eight fault trials for doors outside it.

New campaigns use scheduler version 5. The last fault's `siteId` and
`exceptionClass` form a fault ID; physical actors and event ordinals remain in
the exact injection selector but do not split this scheduling identity. A
new or less-tested fault ID outranks repeated IDs before closure novelty and
depth break ties. One in eight selections goes to the oldest waiting plan,
and another one in eight favors a multi-fault sequence when one is queued. The outside
closure slot is still one in eight. Attempt and successful-injection counts
are checkpointed, so resuming does not reset diversity. Version 5 also records
whether each observed fault door appeared before or after the final check of
the selected target occurrence in the append-only fault receipt. Most queue
slots favor doors seen before that check; one in eight admits later doors to
explore recovery and later target instances. This is a scheduling heuristic:
receipt order across actors does not prove a causal order. If the exact selected
check is absent, doors retain an unknown phase and normal feedback ranking.
Versions 1 through 4 keep their frozen checkpoint selection rules.

When a REGION_STATE trial misses its exact selector, versions 3 through 5 verify any already applied prefix
against its original door receipts, then offers alternate actors observed at
the missing fault's same `siteId` and `exceptionClass` after that prefix.
These are new exact plans with their observed node, epoch, and ordinal; the
old occurrence ID remains provenance only. The append-only receipt row order
is used across actors because their local `seq` numbers are incomparable.
Unobserved doors generate no successors. Version 1 and version 2 checkpoints
retain their previous selection and mutation rules.

## Terminal successor campaigns

An additional campaign may continue an exhausted queue under a newer generic
scheduler without changing or restarting the terminal source campaign. Use a
new output directory and add `predecessor_campaign` to the new config. Generate
its exact pins from the completed source:

```python
from pathlib import Path
from Mallory.native_graphchecker_campaign.campaign import build_predecessor_pins

pins = build_predecessor_pins(Path("/absolute/source-config.json"),
                              Path("/absolute/source-output"))
# Add pins as the successor config's "predecessor_campaign" value.
```

The pins contain absolute paths and SHA-256 hashes for the source config,
checkpoint, and summary, plus aggregates over its exact tested plan keys,
per-trial result files, and unmatched native fault receipts. Import refuses an
active, inconsistent, or mutated source. It requires the same original JUnit,
target, runner, static scope, weave, recorder origin, and fault-depth limit;
the successor may set a fresh time and trial budget. A fresh healthy JUnit runs
in the new directory. The successor keeps the source's untested queue and
feedback, removes every completed exact plan (including old unmatched retries),
and derives new exact actor alternatives only from the pinned unmatched
receipts. The source's completed trials do not count against the new budget.
`predecessor-import.json` records the import lineage and counts. Every resume
rechecks the predecessor hashes and refuses changed source evidence.

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
    "local_work_root": "/mnt/mallory-scratch/junit",
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
In `runner.jvm_args`, `{trial_workdir}` expands to that trial's fresh work
directory, for example with `-Djava.io.tmpdir={trial_workdir}` and
`-Dbuild.test.dir={trial_workdir}` for JUnit cluster data.
`runner.local_work_root` is optional and applies only to new campaigns whose
config includes it. It must be an existing absolute directory on a separate
host-local mount; NFS, an unmounted directory on the root filesystem, and a
path inside the campaign output are rejected. The mount is checked again at
every trial, so losing the scratch mount cannot silently fill `/`. Each campaign and
each trial attempt receives a separate directory beneath that root. The JUnit
process uses it as its current directory, and `{trial_workdir}` resolves there.
The exact path is retained in `process.json`. Fault plans, trace, original
graph, stdout/stderr, trial result, and checkpoint stay in the campaign output
directory. Local work directories are retained for diagnosis; after a trial
result and checkpoint are durable, they may be pruned separately. If local
scratch disappears during an incomplete trial, normal resume retries that
trial in a new directory. Changing `local_work_root` in a running campaign
changes the config SHA and is rejected by checkpoint validation.

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
reached target in the same occurrence and actor epoch, or have a directed
path of original GraphChecker WIRE edges to the target. Each WIRE hop requires
accepted `ENDPOINT_EXPORT` and `ENDPOINT_ATTACH` receipts whose session,
endpoint, occurrence, actor, and VM event IDs match the original rows. The
fault precedes the export on its actor; each attach precedes the next export
or target check on that actor. The exact `TARGET_THROW` follows the check on
the target actor. Temporal admission compares receipt sequences only within
one actor, never across processes. Closure membership, an unpaired endpoint, or an observed
STATE edge alone cannot prove this order; those trials remain
`needs_causal_review`.

Every trial also records `raw_exact_target_throw_after_applied_prefix` and
`raw_target_throw_observation`. These fields retain an exact target throw
after a verified prefix when a later planned fault misses, as well as in
strict trials. The observation records the matching target check and throw,
the applied prefix length, and `lifecycleContext=unclassified`. Append
order across actors is not causal proof, and the runner cannot generally
distinguish workload execution from a JUnit's own teardown. Source and log
review must classify such observations. This raw field never changes
`target_exception_triggered`, the campaign status, or the candidate oracle.

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
