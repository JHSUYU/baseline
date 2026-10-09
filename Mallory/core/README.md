# Mallory campaign core

Run one configured original cluster JUnit workload in a fresh process per trial:

```bash
python3 -m Mallory.core.campaign \
  --config Mallory/cases/HDFS-01.json \
  --out data/mallory/cases/HDFS-01
```

The case config is a JSON object. Required fields are `case_id`, `system`,
`cluster_test`, `cwd`, `command` (an argv array), `target` (`check_sites`,
`throw_site`, and `exception_class`), and `budget` (`trials`, `seconds`, `max_faults_per_trial`,
`trial_timeout_seconds`). The command must launch the selected cluster test
and its runtime instrumentation. Optional `agent_jar` adds the agent to
`JAVA_TOOL_OPTIONS`; this also instruments Maven's JVM, so a direct forked
JUnit command or explicit test JVM options are preferable when available.
The runner sets `MALLORY_EVENT_FILE`, `MALLORY_PLAN_FILE`, `MALLORY_RUN_ID`,
`MALLORY_SITE_CATALOG`, and optionally `MALLORY_SITE_FILE` for every process.
The catalog is saved as `trials/rNNNN/sites.jsonl` with a SHA-256 in that
trial's result. For Maven Surefire
workloads, set `agent_transport: "surefire_argline"`; the controller appends
the trial-specific `-DargLine=-javaagent:...` to the Maven command and leaves
Maven's own JVM uninjected. The default `java_tool_options` transport is for
direct Java commands and small smoke tests.
For a POM with a hardcoded Surefire `argLine`, arrange an explicit property in
that POM and set `agent_arg_property` to its name (for example,
`mallory.agent.arg`); the runner then supplies `-Dmallory.agent.arg=...`.

Each trial has a `plan.json`, an event trace, stdout/stderr logs, and a
`result.json`. The controller atomically updates `checkpoint.json` and a
case-level `result.json` after each trial. A restart resumes unfinished work;
if the previous test process group is still alive, the controller refuses to
start a duplicate. If a controller died after a process exited but before
writing its result, it retains that partial evidence under `interrupted/` and
reruns the plan.
After analyzing a trial, the controller gzip-compresses the trace and records
both raw and compressed SHA-256 digests and byte counts. It removes the raw
trace only after verifying the gzip round trip. Logs above 1 MiB are likewise
compressed. Each result records `MALLORY_ATTEMPT_ID` when dispatched remotely.

Preliminary configs can set `calibration_only: true`, or the runner can receive
`--calibration-only`, to stop after healthy trial `r0000`. A promoted config
must set `auto_promote_if_healthy: true` and pin the original loaded target
class SHA-256 as `expected_target_class_sha256`. Before fault trial 1, the
controller checks the exact guard and throw IDs in the runtime site catalog,
the loaded class hash and loader identity, named target actors and regions, a
clean healthy target outcome, and an eligible observed I/O door. The receipt
is stored as `runtime_attestation` in the checkpoint and case result. If any
check fails, it does not run a fault trial. Commands may use `{trial_dir}` for
trial-specific temporary paths.

The trace uses `type`, `id`, `seq`, `node`, `epoch`, `occurrence`, `site`.
`TARGET_CHECK` identifies an exact guard branch site. `TARGET_THROW` identifies
the separate bytecode throw site and carries `exception_class`. A legacy
single `site` target is accepted only when the two site names coincide.
The Java agent names these sites `Class#method(desc)@line:branch:N` and
`Class#method(desc)@line:throw:N`; take the ordinal from its site catalog.
The target event must belong to a named region occurrence. A healthy run may
visit the target multiple times and on several named logical nodes. The seed
binds the set of named actors and retains a separate backward closure for each
target occurrence. Unnamed startup occurrences are recorded as identity gaps
and do not qualify as target evidence in fault trials.
The compact agent emits `COVERAGE_DEF` rows mapping integer `coverage_ref` to
full coverage IDs, followed by `COVERAGE_SUMMARY` with unique `coverage_refs`
for each `(node, epoch, occurrence)`. Feedback rejects undefined or conflicting
references and unions the resolved IDs globally and for summaries whose
occurrence lies in the target closure. The summary's late sequence number is a
flush time, not the execution time of its individual coverage IDs. Older
string `coverage_ids` summaries and `METHOD`/`BRANCH` rows remain readable.
`DOOR_OBSERVED` carries `door_ordinal`, a one-based counter scoped by
`node`, `epoch`, and exact `site`. Fault plans use these four fields and omit
the occurrence because RPC call IDs can change between test runs. The trace
still keeps the full occurrence for within-run causal edges. Older agents
without `door_ordinal` fall back to exact occurrence and `hit` matching.
`DOOR_OBSERVED` also carries `hit` and optionally
`fault_type`, `fault_types`, and `exception_class`. `FAULT_MATCHED` and
`FAULT_APPLIED` carry the plan's `fault_id`. SEND/RECV require matching
`transport`, `correlation`, `attempt`, `half`, `port`; task handoffs require
`correlation`; state accesses require `object`, `key`, `version`. Optional RPC
`attempt` and `half` must agree when present. The graph accepts only unique
complete message pairs. Missing or ambiguous pairs are counted as gaps.
State probes installed after field or Map calls report sampled versions and
form candidate edges, never proven read-from edges. Static candidate sites may
broaden selection but are never reported as observed causal edges.

The scheduler first tries fault doors within the observed target closure,
then doors at static frontier locations. By default it also retains lower
priority exploration doors outside those sets, because instrumentation gaps
could otherwise leave a reachable target with no testable candidate. Set
`explore_outside_closure: false` for a strict ablation. Every trial records
the selection reason.

For workloads where deeper sequences replay unreliably, optional
`single_fault_breadth_interval: 3` chooses the highest ranked one-fault plan
on two of every three fault-trial picks while one remains queued. Every third
pick uses the usual priority order, so multi-fault sequences remain eligible.
Candidate replays retain first priority. The interval is counted from
completed fault trials and is stored in the immutable case config, making
selection deterministic after checkpoint resume. Omitting the field preserves
the original scheduler behavior. When `validated_recovery_sites` are also
configured, their periodic exploration pick takes precedence over this
breadth preference.

An optional `validated_recovery_sites` list gives higher priority to exact
door sites that retained the target in independent pilot trials. Each row has
`site` and a nonempty `evidence` list of `{trial_result, sha256}` receipts.
The runner verifies each pinned trial belongs to the same case, applies only
faults at that site with exact runtime identity, and reaches the target after
the fault. The loaded target class hash must match when pinned. Such sites
receive `validated_recovery` as their selection reason. Every fifth fault
trial, when available, explores another candidate; configure
`validated_recovery_exploration_interval` to change that cadence. This
priority affects only newly started campaigns; a running checkpoint's config
must stay fixed.

`target_exception_candidate` requires that every planned fault was matched
and applied in order, then an exact guard event precedes the exact target throw
with the configured exception on the same bound node, epoch, and occurrence.
Replays are queued by default, but the result remains a *candidate* pending
source review. Other test failures, hangs, and target loss cannot satisfy the
oracle. The summary leaves `new_bug` null.

Run core contract and archive checks with
`python3 -m unittest Mallory.core.test_core Mallory.core.test_audit`.

## Offline causal audit

Audit a terminal campaign without rerunning its workload:

```bash
python3 -m Mallory.core.audit \
  --campaign data/mallory/cases/CASE-ID \
  --out data/mallory/cases/CASE-ID/offline-causal-audit.json
```

The auditor verifies raw and gzip trace hashes, recomputes the graph and
target oracle from each archived trace, and checks exact runtime identities
for applied faults. It compares eligible door closure membership, closure
occurrences and edges, and coverage/closure novelty against the live result.
The machine-readable artifact includes `report_gate_passed` and separate
integrity, identity, target-claim, and guidance gates. Door membership is
stored as a count and SHA-256 with at most ten differing entries per trial;
the full maps are compared in memory. Only the named audit artifact may be
written inside the case directory; archived campaign results and traces are
read-only.
The independent `healthy_closure_proven` gate requires at least one uniquely
observed causal edge in healthy trial `r0000`'s target backward closure and
at least one named pre-target I/O door with a nonempty path to the target made
entirely of observed edges. The artifact records this as
`healthy_observed_path_doors`. Sampled state edges remain available for
exploration but cannot prove this audit gate. A reached target with a
singleton closure or only a candidate-edge door path cannot pass
`report_gate_passed`.

For a new, separately versioned campaign, `allow_local_timeline_doors: true`
also admits a named I/O door that occurs strictly before an exact nonthrowing
target check in the same node, epoch, and region occurrence. Feedback records
the two event IDs and sequence numbers as `observed_local_timeline`; the
audit reports `healthy_local_timeline_doors` and
`healthy_closure_evidence_types`. This proves local temporal order, not data
flow or a cross-region causal link. The option defaults to false, so existing
campaigns and their audit meaning remain fixed. Create a new config and output
directory for any opt-in run; do not edit a running campaign checkpoint.

For a terminal campaign whose healthy evidence is *only* local timeline
evidence, the future audit also requires one effective fault at a door site
admitted in that healthy run, followed by an exact target check in the same
named node, epoch, and occurrence. It binds the fault, observed door, and
check event IDs and records `same_actor_target_trials`. The older
`strict_target_trials` count only says the target was reached somewhere after
an effective fault; another actor or occurrence can satisfy that count.
Healthy-only calibration needs no post-fault proof. Frozen 5820 campaign
results and releases remain unchanged; a separately versioned re-audit may
change the quality gate for local-timeline-only cases.
