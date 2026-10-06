# Unit-test fault campaign core

This driver reruns one **original cluster JUnit method** for each selected
coordination check. GraphChecker supplies the static target policy, healthy
recording, target-rooted runtime region plan, and the exception door. The
driver chooses only observed fault points in that target closure, asks the
Java controller to flip an exact fault occurrence, records branch/method
coverage, mutates fault sequences, and checks whether the target exception
occurred after all requested faults.

## Entry points

```sh
python3 -m unittest -v test_fuzzer.py
python3 smoke.py --out /tmp/graphchecker-unit-fuzzer-smoke
python3 fuzzer.py /path/to/case.json --root /path/to/cases
```

`smoke.py` writes a runnable JSON case and a synthetic GraphChecker-format
healthy trace/plan. It executes one injection, aggregates the trial plan,
checks the exception oracle, writes `cases/CHECK-01/result.json`, then resumes
the same case and proves it does not repeat the completed trial. The fixture
proves the driver protocol; it is not a distributed-system bug report.

The core GraphChecker JAR used for the current plan/fault schema is
`/users/ZhenyuLi/.graphchecker-builds/unit-test-core-e73b2c09c-cd27a01fd058.jar`
(commit `e73b2c09c`). System-specific case branches use their own immutable
JARs; record each JAR digest in the case evidence. The opt-in
`-Dcausynth.region.preserve.failure-target=true` setting, together with
`-Dcausynth.region.skeletons=<static skeletons path>`, preserves a static
`FAILURE_TARGET_ENTRY` as its own runtime region in both recording and replay.
Do not run its workload from a shared
source checkout: each case needs its own GraphChecker build/worktree, system
test workspace, trace directory, temporary data directory, and ports chosen
by the original test or a per-case port allocator.

## Case configuration

The generated `smoke-run/case.json` is a complete schema example. For a real
case, set:

- `case_id`, `system`, `test_class`, `test_method`: the checklist item and the
  original JUnit test, including a parameterized child where applicable.
- `target.method`, `target.exception_type`: exact Soot method signature and
  exact runtime exception type. `target.occurrence` may pin one full runtime
  target address. `target.request_api` may pin the semantic request operation
  recorded by GraphChecker, including distinguishing arguments such as
  `deleteBlockPool(force=false)` and `deleteBlockPool(force=true)`. If it is
  omitted, the driver takes the request APIs observed for the healthy target
  and admits only those operations in trial plans; when GraphChecker provides
  no request API, it conservatively requires a matching healthy target
  occurrence. Retries of the same semantic operation may have different full
  occurrence addresses. `target.region_id` is the static target region and is
  mandatory; it is inferred from `TARGET_SITE` when `scope_map` and
  `throw_site_id` are supplied. The runtime plan must contain an explicit
  row for that region under the current plan schema. Merely listing it in
  a parent row's `foldedRegionIds` gives no one-to-one runtime mapping to
  the target method activation and guard, so it yields `graph_gap`.
  A future explicit containment/unique activation proof could satisfy
  this gate without a separate row. Supply `target.fatal_guards` as one
  ordered route of exact `siteId`/boolean outcomes or `target.scope_map`
  plus `target.throw_site_id` to read GraphChecker's `TARGET_SITE` policy.
  When distinct bytecode routes reach the same throw, supply
  `target.fatal_guard_paths` as a list of ordered guard lists; the routes
  are alternatives. Each route needs source/bytecode and runtime calibration
  evidence. The final guard of each route is the check that must execute
  after the fault; an earlier entry guard alone does not count. If the throw occurs in a nested
  method, set `target.throw_method` to that method; it is inferred from
  `throw_site_id` when supplied. The oracle follows `parentCallId` from
  that throw back to the selected target call. `target.site_id` is optional
  controller summary context; the Python oracle uses the fatal guards.
  For a selected `throw` caught inside the same Java method, set
  `target.throw_event` to `EXPLICIT_THROW` and provide the exact
  `target.explicit_throw_site_id`. The GraphChecker hook records the
  executed `ThrowStmt` before local catch handling; the default
  `METHOD_EXIT_THROW` oracle only sees exceptions escaping a method.
  The explicit site must belong to `throw_method` and, when supplied,
  equal `throw_site_id`. Calibrate its woven site ID against the original
  JUnit test before using it for trials.
- `seed.trace`, `seed.closure_plan`: healthy `runtime_trace.jsonl` and
  `concolic_region_plan.jsonl`. Provide `seed.command` to generate them or
  `seed.elapsed_seconds`/`seed.timing_manifest` if already generated. The
  healthy run must reach the target region and evaluate a target guard.
- `trial.command`: argv (not shell text) that reruns **the same JUnit test**
  using `JUnitMethodRunner`/GraphChecker. The driver sets
  `CAUSYNTH_FAULT_TRIAL`, `CAUSYNTH_TRACE_OUTPUT_DIR`, and appends
  `-Dcausynth.fault.trial=<absolute fault-trial.json>` to
  `CAUSYNTH_WORKLOAD_JAVA_OPTS`. The runner must pass that JVM property to
  the test JVM. Tokens `{fault_trial}`, `{trace_dir}`, `{trial_dir}` and
  `{case_dir}` are available in argv. `trial.env` values may use those
  tokens, plus `{trial_name}`, `{sequence_id}` and `{attempt}`. If a native
  runner writes its trace elsewhere inside a per-case workspace, set
  `trial.trace_path` to that trace file. The driver verifies its path stays
  inside one declared per-case workspace.
- Optional `target.source_file`, `target.source_line`, `target.code` are
  copied into the result table so each checklist row identifies the exact
  check in source, even when its runtime plan uses an enclosing method.
- `trial.aggregate_command`: argv invoking GraphChecker
  `CausynthTraceRecorder` on the new trace and writing a new target plan;
  `trial.closure_plan` names that output. `{aggregate_dir}` is available.
  Trial closure evidence must come from its own recording; a copied healthy
  plan is useful for the synthetic smoke only.
- `workspaces.graphchecker`, `workspaces.system_test`, `workspaces.temp`:
  three different absolute per-case directories. `cwd` must be one of the
  first two. Add checkout roots to `shared_readonly_roots`; validation
  rejects workspaces under them.
- `budget.max_trials`, `budget.max_faults`, `budget.max_seconds`:
  fault-sequence count, sequence length, and **active** seed/trial/aggregate
  runtime. Offline time between resumes is excluded. Increasing the budget
  in the same case directory preserves completed trials. `timeout_seconds`
  limits each command separately.

The fault selector JSON has `schemaVersion:1`, an ordered `faults` array,
and optional `targetSiteId`/`targetRegionId`. Each selector has a unique
`faultId`, `marker`, `siteId`, full `occurrence` (copied verbatim from
`FAULT_POINT_OBSERVED.occurrenceAddress`), `hitOrdinal`, optional
`sourceKey`, and `value:true`. The Java controller emits
`schemaVersion:3,faultSchemaVersion:1` events. The driver calls an injection
*strict* only if every `FAULT_APPLIED` has the requested identity and order.

The queue alternates breadth and depth as both become available: one-fault
seeds and extensions of previously tested sequences receive comparable trial
slots. Within a slot, it first prefers an untested I/O fault family
(`marker`, `siteId`, `sourceKey`), then coverage priority. For extensions it
also prefers a first-fault family with fewer completed trials. Full
occurrence addresses still govern injection identity; this grouping only
guides scheduling. Existing completed selectors are read from the checkpoint
so increasing the budget does not rerun them.

## Evidence and decisions

Only `CONCOLIC_REGION_PLAN.targetClosureEvidence` whose `targetOccurrence`
matches the selected target enters the closure. Its `evidenceTier` is
`EXACT` for the target and `CANDIDATE` for demand-walk admitted members.
The integrated plan currently reports `edgeEvidence:UNAVAILABLE`, so this
driver tracks **member novelty**, never claims new causal edges. A
`BLOCKING` catalog gap or absent membership evidence yields `graph_gap`:
the healthy probe is saved, fault trials do not start, and no coverage or
closure feedback from a blocked trial enters the corpus.

A target exception candidate requires all of the following in the selected
target call or a descendant and after the last applied fault: the exact
expected exception `runtimeType` from `throw_method` at the selected
`METHOD_EXIT_THROW` or `EXPLICIT_THROW` event, target
occurrence, and one complete ordered fatal guard route in the throw call.
An exception in the same method without
those guards is recorded as `target_exception_unlinked`; it is not marked
as a candidate. A matched injection that prevents target execution is
`lost_target` and is abandoned. Candidate status is evidence for source
review and replay, not a confirmed new bug.

A fault can remove a versioned state edge from the faulted graph. If the
healthy seed had a valid target closure, the exact fault applied, and the
post-fault target throw and guard route are observed, the trial remains a
candidate even when the new graph has a `BLOCKING` gap. The gap is recorded;
that trial contributes no graph or coverage feedback to mutation. A graph
gap without the exact target oracle remains `graph_gap`.

The healthy JUnit run may itself expect the target exception. The driver
records its target fatal exception count and still runs the fault campaign.
If a faulted run reaches the same fatal exception with no increase over
that baseline count, its status is `baseline_exception_recurrence`, not a
new-bug candidate. An increased count is a differential observation that
still requires source review and replay before confirmation.

The result table lives at `cases/<CASE-ID>/result.json`. It includes the
system, test, target status, strict injections, post-fault target reach and
lost-target trial counts, target-exception-after-fault count, oracle candidate
count, coverage gain, first/last I/O fault-family diversity, single/multiple
fault trial counts, evidence path, graph gaps, and
`setup_seconds`, `build_seconds`, `seed_seconds`, `fault_seconds`,
`aggregate_seconds`, `total_elapsed_seconds`. `setup_seconds` and
`build_seconds` are supplied by the case when those stages ran outside the
driver. The other times are measured or read from the healthy timing
manifest. Status `quality_complete`, `no_cluster_test`, `source_excluded`,
or `confirmed_bug` is terminal and will not be rerun. The driver never
labels a case `quality_complete` automatically.

An exact fault selector can still hit a different request if a test's request
ordinal changes between the healthy and faulted runs. The adapter should put
the request's semantic operation and arguments in the GraphChecker request
root so the occurrence address stays tied to that operation. The driver also
requires the trial target's `requestApi` to match the healthy target's
operation; a different command at the same static check cannot substitute.
Independently,
the driver requires a target check branch in the target call after the last
applied fault. A trial with only a pre-fault target check is `lost_target` and
does not contribute coverage or a bug candidate. If no trial remains valid,
the case result is `no_valid_target_trial`; it needs a different fault point
or adapter review before the check can be marked complete.

Each case stores `state.json`, one `trials/NNNN-<sequence-id>/` directory
per requested sequence, and an atomic `result.json`. A pending `active`
sequence survives process interruption. Its next attempt uses a new
`attempt-NN/trace` directory; completed sequences are skipped. Result and
state files are written via same-directory temporary files plus rename.

## Multiple hosts

On these CloudLab nodes `/users/ZhenyuLi/baseline` is **local ext3 on each
host**. Matching paths on node0/node1/node2 are not a shared filesystem.
`CaseLease` (`flock` plus atomic `mkdir(claim.d)` and heartbeat) therefore
protects only processes using the **same host-local case directory**.
It must not be treated as a cross-host checklist lease. The central
`coordinator.py` ledger on node0 owns global case claims. It uses a local
ext3 `flock` critical section, atomic `mkdir(lease.d)`, and O_EXCL temporary
JSON files followed by rename. Node1 and node2 cannot SSH back to node0:
they have no copy of node0's private key. Node0 therefore claims and
heartbeats centrally, SSHes into a worker, and uses `rsync` to pull artifacts
back after the worker exits. The SSH key remains on node0.

Create one node0 ledger from the existing 102-row checklist:

```sh
CORE=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/core-fuzzer
LEDGER=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/node0-ledger
python3 "$CORE/coordinator.py" init --root "$LEDGER" \
  --manifest /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/checklist102.json
python3 "$CORE/coordinator.py" status --root "$LEDGER"
```

For each worker, prepare a local bundle with `fuzzer.py` and per-case JSON
configs. The JSON file passed as `--command-json` is an argv array, for
example:

```json
["python3", "{remote_payload_dir}/fuzzer.py",
 "{remote_payload_dir}/configs/{case_id}.json", "--root", "{remote_root}"]
```

The configs in that bundle must name each worker's **local** GraphChecker,
system-test, and scratch directories. Start a node0 dispatcher in tmux for
each worker; `--system` can restrict a dispatcher to one system. For example:

```sh
python3 "$CORE/coordinator.py" dispatch --root "$LEDGER" \
  --host node1 --remote-root /users/ZhenyuLi/baseline/worker-cases \
  --payload-dir /users/ZhenyuLi/baseline/worker-bundle \
  --remote-payload-dir /users/ZhenyuLi/baseline/worker-bundle \
  --command-json /users/ZhenyuLi/baseline/worker-bundle/command.json \
  --sync-profile summary --sync-max-mib 32 \
  --max-cases 102
```

`init` queues only untouched mapping/search statuses. Existing case outcomes,
including `no_valid_target_trial` and graph/identity gaps, remain on hold so a
new ledger cannot repeat them automatically; use `resume --reason` after a
specific adapter, workload, or budget change. `dispatch` claims one queued
case at a time. Each runs in a uniquely
named tmux session on its assigned worker. The node0 ledger records the
worker host, session name, attempt number, and lease expiry. It renews the
lease while the remote session runs and copies a bounded evidence stage into
`LEDGER/cases/CASE/artifacts/attempt-NNN/` before publishing the central
`result.json`. The default `summary` profile transfers at most 32 MiB per
case, including the evidence manifest. It includes results, state, selectors,
manifests, summaries, and bounded log tails. Full traces and all other
artifacts stay on the worker. `evidence-manifest.json` records the worker
host, full case path, source size and SHA-256 for selected or omitted traces,
the transferred file paths, and any truncated logs. `--sync-profile trace`
adds gzip-compressed trace files only when they fit the same byte cap;
`--sync-max-mib` sets an explicit 1–1024 MiB limit. `status` shows the recorded tmux session for
inspection. An expired claim can be taken over; the new dispatcher probes
the recorded remote session or exit marker and collects the existing run
instead of starting it again. The original worker case directory preserves
the fuzzer's per-trial checkpoint if the remote process itself stops.

`quality_complete`, `no_cluster_test`, `source_excluded`, and
`confirmed_bug` are terminal. `candidate_review`, `graph_gap`,
`no_valid_target_trial`, `no_closure_fault_points`, and
`budget_or_queue_complete` stay out of the
automatic claim queue. After an adapter or config fix, explicitly reopen a
review/repair case with a recorded reason:

```sh
python3 "$CORE/coordinator.py" resume --root "$LEDGER" \
  --case-id HDFS-11 --reason 'GraphChecker closure identity fix v2'
```

The fuzzer rejects a changed workload/target configuration in an existing
worker case directory. After `resume` for an adapter/config revision, use a
new versioned `--remote-root` (and correspondingly updated per-case config
paths) so the old state remains as evidence. A routine disconnected retry
with identical configuration should keep the same remote root and resume
its pending trial.

Only an infrastructure `retryable` result automatically returns to the
pending queue. The CLI also exposes `claim`, `heartbeat`, and `complete` for
node0-local scheduling; `complete` requires the worker `result.json` to be
under that case's node0 ledger directory, so a result cannot be marked
complete before artifacts arrive.

On 2026-10-06, `RUN_REMOTE_COORDINATOR_TEST=1 python3 -m unittest -q
test_coordinator.py` passed all seven tests. The dry run launched one worker on
node1 and one on node2, heartbeated both claims, and pulled both results.
The recovery test killed the node0 dispatcher after the node1 tmux session
started, let its lease expire, and resumed through a new dispatcher invoked
with `--host node2`; it monitored the recorded node1 job and the worker
`runs.log` contained exactly one execution. Both workers had no remaining
tmux sessions after the tests.

## Current case decisions

The per-case `result.json` files and the 102-row checklist are authoritative.
An early HDFS-11 probe had a shared occurrence address and an early
ZooKeeper-07 probe folded the target region. Both required GraphChecker
identity/target-region repairs before strict trials could run. Their later
case results record those repairs and the resulting fault trials; do not use
the early probe outputs as the current closure.
