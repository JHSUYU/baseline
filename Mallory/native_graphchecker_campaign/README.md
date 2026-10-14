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
For a scheduled preparation that already ran Recorder and Scheduler on the
same CLOSED trace, `seal_precomputed_schedule` can seal their actual JVM
command receipts and output paths. Set `recording.precomputed_schedule` to
the absolute seal path. Admission then verifies the trace and static input
hashes, source-built engine, Java executable, commands, plan, selected
skeletons, schedule, and weave task before using those exact bytes. Resuming
rechecks the plan artifacts. HDFS preparation emits this seal for new cases;
existing campaign configs keep their original behavior. This skips the
duplicate admission Recorder and Scheduler, while `r0000` still executes a
fresh unchanged JUnit and builds its own graph.
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

New campaigns use scheduler version 10. The last fault's `siteId` and
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
Version 8 adds an optional peer identity hint for REGION_STATE campaigns with
an independently pinned static RPC scope. It pairs the original GraphChecker
`EXCHANGE_SEND` and `EXCHANGE_RECEIVE` request events by correlation, attempt,
and half, then reads the actual receiver process epoch. A correlation key
with multiple sends or receives is ambiguous even when the counts match; the
runner does not use per-actor sequence numbers to pair it. It joins an already
observed `FAULT_DOOR` to a request only when method, source actor, ordinal,
and cardinality agree; ambiguous joins remain `unknown`. The selected target
actor's pretarget requests identify its peer for the same receiver role. The
native hook receipt's append order marks a door as observed before or after
the selected target check; this is a scheduling heuristic, not a cross-actor
causal order. Only a same-peer RPC door with `before_selected_target` phase
gets a bounded scheduling bonus, including one peer-aware static-producer slot
in eight selections. This does
not change static eligibility, the original graph, strict injection, or bug
verdict. The per-trial `peer-ranking-receipt.json` pins the trace and selected
target receipt. Resume, terminal reopening, and predecessor import verify
that durable peer receipt against the result's SHA-256; the local raw-trace
artifact manifest does not cover this separate file. Old checkpoints retain
their frozen scheduler version.

Version 9 reserves one in sixteen selections for a later occurrence of an
observed-closure I/O site whose fault ID previously injected successfully.
The exact actor and ordinal remain in the selector. Within that slot it first
prefers less-tested fault IDs and lower ordinals, then spreads across later
observed positions. If no eligible repeat exists, ordinary version 8 ordering
applies. This changes only queue priority; eligibility, target retention,
strict injection, and the bug oracle remain unchanged.

Version 10 reserves a separate one-in-sixteen slot for fault sequences of
depth four through six. The slot cycles its preferred depth from four to five
to six, then repeats, so a queued deeper sequence cannot be displaced forever
by depth-three plans with less-tested fault IDs. Its candidates must descend
from a strictly injected run that retained the selected target check after the
last fault. At least one graph delta, observed fault-in-closure relation, or
admitted target temporal relation is required; an observed pretarget phase and
a matching RPC peer together also qualify. Phase and peer are scheduling
hints, not proof of causality. The selected depth is bounded by the campaign's
existing maximum fault count. The existing outside-closure, oldest-waiting,
retry, and depth-three slots keep their positions. Checkpoints created under
earlier scheduler versions keep their original ordering.

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
    "local_artifact_root": "/mnt/mallory-scratch/raw",
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
The exact path is retained in `process.json`. With only this option, fault
plans, trace, original graph, stdout/stderr, trial result, and checkpoint stay
in the campaign output directory. Local work directories are retained for diagnosis; after a trial
result and checkpoint are durable, they may be pruned separately. If local
scratch disappears during an incomplete trial, normal resume retries that
trial in a new directory. Changing `local_work_root` in a running campaign
changes the config SHA and is rejected by checkpoint validation.

`runner.local_artifact_root` is a separate, optional setting for **new**
campaigns. It must point to an existing host-local mounted directory; the
same root-filesystem and NFS checks apply. When enabled, each trial allocates
a unique local attempt directory. Its raw runtime trace, original session
files, original GraphChecker analysis tree, and JUnit stdout/stderr are linked
from the familiar trial paths to that directory. If `local_work_root` is not
also set, the JUnit current directory moves there too. The fault plan,
append-only fault events, JUnit result marker, process receipt, schedule
lineage, native summary, `result.json`, and checkpoint remain as real files
in the shared campaign tree. Graph feedback and injection selectors are
unchanged. Existing campaigns with no `local_artifact_root` keep their exact
layout. Changing this setting changes the config SHA, so it cannot silently
alter a running campaign.

Before `result.json` is published, `local-artifacts.json` in the shared trial
directory records the physical host, unique local path, symlink targets,
file count, byte count, a SHA-256 tree commitment, and hashes of selected
trace/graph/log files. The result pins that manifest's SHA-256. An interrupted
trial is moved to `interrupted/` and a fresh attempt gets a new local path;
the old local files are retained. A completed trial with a durable result is
accepted on resume without rerunning it, even if its raw local files are no
longer accessible. The source graph and trace can only be independently
recomputed on the host with that local directory. A copied tree can be
reviewed manually, but queue promotion remains bound to the recorded host.
The frozen terminal inspector publishes a host-identified audit
receipt only after reading every local raw tree and the original graph. Queue
promotion rehashes those bytes on the owner host. On another node, the shared
summary, fault events, result, and manifest support identity and outcome
review, but raw graph replay and terminal promotion are held. A stale audit
receipt cannot substitute for a missing local file. Losing the local
directory loses that raw evidence; the checkpoint and compact result survive
on shared storage, and completed trials are not silently rerun. Do not delete
local attempt directories before required raw audit and promotion are complete.

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

For `region_state` trials, `native_target_retained` means that the original
graph contains a reached target. The separate `post_fault_target_check_observed`
field counts only selected `TARGET_CHECK` receipts appended after the last
`FAULT_APPLIED` when the native hook's single-JVM receipt sequence is
globally gapless; its evidence gives check counts on each side of the fault.
If that clock cannot be verified, cross-actor order is unknown, while
same-actor sequence comparisons remain available. A later event on another
actor establishes observed order, not causal influence.
The observation is `null` when no selected check receipt or a cross-actor
ordering proof is available.
When all selected checks precede the fault, the campaign records zero
post-fault target checks and gives the graph delta no target-directed novelty
score. It still retains exact eligible doors for a later fault sequence.
A completed trial in this state does not claim that the faulted execution
reached the check.

Every trial also records `raw_exact_target_throw_after_applied_prefix` and
`raw_target_throw_observation`. These fields retain an exact target throw
after a verified prefix when a later planned fault misses, as well as in
strict trials. The observation records the matching target check and throw,
the applied prefix length, and `lifecycleContext=unclassified`. Append
order across actors is not causal proof, and the runner cannot generally
distinguish workload execution from a JUnit's own teardown. Source and log
review must classify such observations. This raw field never changes
`target_exception_triggered`, the campaign status, or the candidate oracle.

The native runner also records `raw_exact_target_throw_count` across all
check/throw pairs, including those in the unchanged healthy JUnit. Fault
trials carry `healthy_raw_exact_target_throw_count` and set
`raw_target_throw_differential_candidate` only when every planned fault was
strictly injected, an exact throw appeared after the last applied fault, and
the run has more exact throws than its healthy seed. This is a source-review
lead, separate from the original GraphChecker selected-region verdict and
caller-path attribution. The selected-region verdict only examines the
original finalizer's `targetCheckOccurrenceIds`, so an expected throw at a
different occurrence does not block a nonthrowing healthy selected target.

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
