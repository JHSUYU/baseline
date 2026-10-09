# Coverage guided fault campaign for cluster tests

`original_hdfs_junit.py` is a small calibration helper for an unchanged
Hadoop 3.4.3 embedded-cluster JUnit method. It runs one method with its
native fixture in a fresh scratch directory and records JUnit outcome,
elapsed time, and a raw JaCoCo file. It does not instrument target checks or
inject faults, so a passing run alone never completes a candidate.

`fuzzer.py` reruns one existing cluster based JUnit test and injects faults at
I/O points observed in that test. It reads a healthy runtime trace to find the
target check, exact fault selectors, and initial method/branch coverage. Each
faulted run produces a new trace. The driver uses new I/O families and
production method/branch coverage to schedule the next sequence. It does not
need a runtime graph, closure plan, or per-trial aggregation.

## Run

```sh
cd /users/ZhenyuLi/baseline/crashfuzz/core-fuzzer
python3 -m unittest -q test_fuzzer.py
python3 fuzzer.py /path/to/case.json --root /path/to/results
```

Each case must use its **original cluster JUnit method** as the workload.
The case adapter should record a healthy `runtime_trace.jsonl` and pass the
same JUnit method and its original cluster fixture to every faulted run. The
injection controller must emit schema version 3 `FAULT_POINT_OBSERVED`,
`FAULT_MATCHED`, and `FAULT_APPLIED` events. Method entry, branch, and throw
events provide coverage and the target oracle.

A minimal case config has this shape:

```json
{
  "case_id": "EXAMPLE-01",
  "system": "example",
  "test_class": "example.ClusterTest",
  "test_method": "testCoordination",
  "cwd": "/case/system-test",
  "workspaces": {
    "system_test": "/case/system-test",
    "temp": "/case/tmp"
  },
  "target": {
    "method": "<example.Target: void check()>",
    "site_id": "<example.Target: void check()>#u8",
    "exception_type": "example.TargetException"
  },
  "seed": {
    "trace": "/case/healthy/runtime_trace.jsonl",
    "elapsed_seconds": 12.0
  },
  "trial": {
    "command": ["python3", "/case/run_original_test.py"]
  },
  "budget": {},
  "timeout_seconds": 120
}
```

`seed.command` may generate a missing healthy trace. When the trace already
exists, provide `seed.elapsed_seconds` or `seed.timing_manifest`. The trial
command is an argv list. The driver sets `CAUSYNTH_FAULT_TRIAL`,
`CAUSYNTH_TRACE_OUTPUT_DIR`, and `-Dcausynth.fault.trial=<selector>` in
`CAUSYNTH_WORKLOAD_JAVA_OPTS`. The command or adapter must pass that Java
option to the JUnit JVM. `trial.trace_path` can name a trace elsewhere within
a declared per-case workspace. `trial.env` supports `{trial_name}`,
`{sequence_id}`, `{attempt}`, `{trial_dir}`, `{trace_dir}`, `{fault_trial}`,
and `{case_dir}`. The driver rejects traces outside those workspaces.

`target.method` and `target.exception_type` are exact. `target.site_id` pins
the target branch checked after the final fault; its observed outcomes and
change relative to the healthy run are saved as evidence. For checks with
alternative final branches, `target.check_site_ids` lists the exact branch
sites; final sites can also be derived from `fatal_guard_paths`. A later
method exit alone does not count as reaching one of those checks. If no
check site is supplied, a method or branch event in the target call after
that fault is the weaker reach criterion. `target.occurrence` can pin one
runtime target occurrence.
For a call-site check such as `Journal.checkRequest#u78`, set
`target.check_events` to `["CALL_SITE_RETURN", "CALL_SITE_THROW"]`, and set
`target.throw_site_id` to the same exact site. `target.throw_event` can be
`CALL_SITE_THROW`; the recorder pairs `CALL_SITE_ENTER` with its return/throw
by `invocationId`. Since `CALL_SITE_THROW` currently carries no exception
class, the oracle also requires a typed `METHOD_EXIT_THROW` in the selected
method. A healthy expected exception is counted before the campaign, so the
same number of selected throws is a baseline recurrence.
For more precise exception attribution, optionally supply `fatal_guards` or
alternative ordered `fatal_guard_paths`; the final branch of a route must
execute after the last fault. `throw_method`, `throw_event: EXPLICIT_THROW`,
and `explicit_throw_site_id` support a throw inside a descendant call or a
locally caught explicit throw. Exclude synthetic injection branches from
coverage with exact `coverage_exclude_sites` when needed. Set
`coverage_include_prefixes` (for example, `["<org.apache.hadoop.hdfs."]`)
to keep JUnit and probe classes out of feedback. The case result reports
distinct gains for methods, branch outcomes, and call-site events;
`coverage_gain` is their combined ID count.

`io_scope` is an optional coarse hint. Its `marker_prefixes` and `site_ids`
arrays filter instrumented I/O points for scheduling. `source_keys` and
`source_key_prefixes` optionally restrict the stable runtime source/peer key.
For example, an encrypted HDFS DataNode mirror workload may select a
`DN->DN:writeBlock:` source prefix, whereas proxy movement uses
`DN->DN:replaceBlock:`. The instrumentation must actually emit those I/O
points; the scope cannot create a missing path. Leave it out to use all
valid fault markers emitted in the test. A fault selector still includes its
full runtime `marker`, `siteId`, `occurrence`, `hitOrdinal`, and optional
`sourceKey`. The controller must report every applied selector with the same
identity and in order. I/O family (`marker`, `siteId`, `sourceKey`) is used only
for prioritization; it never replaces the full runtime identity.
The occurrence may be any nonempty runtime address; it has no graph-format
requirement.

## Budget and decisions

When omitted from `budget`, `max_trials` defaults to **80** and `max_faults`
to **8**. `max_seconds` limits active run time if supplied. If new production
method/branch coverage or stable I/O families still appear near trial 80 in
valid target-retaining trials, raise the existing checkpoint's budget to
**128 trials / 10 faults** and resume it. Repeated hits or retry ordinals at
the same I/O family do not justify this extension.
Changing only `budget` or `timeout_seconds` keeps the same completed trials.
`max_unmatched_retries` defaults to 1: an unmatched sequence gets one fresh
attempt before it is recorded as unmatched. Every mutation adds exactly one
fault from the actual trace after the last applied fault. The scheduler
prefers untested I/O families, then higher coverage priority, while balancing
one fault and longer sequences.

A valid trial must prove all requested faults were applied in exact order and
must execute the target check after the final fault. A `lost_target` trial is
discarded from feedback and mutation. An exact post-fault target exception
that exceeds the healthy exception count is a `target_exception_candidate`.
This is a **source review and replay candidate**, not a confirmed bug. The
driver never marks `confirmed_bug` or `quality_complete` automatically.

Each case stores an atomic `state.json` checkpoint, `result.json`, and trial
selectors, traces, command logs, and per-attempt results. A pending sequence
survives process interruption; completed sequences are not rerun. The driver
uses a local file lock and heartbeat claim to prevent two processes on one
host from running the same case at once. Cross-host case allocation belongs
to `coordinator.py`; host-local case paths alone are not shared locks.
