# Coverage guided fault campaign for cluster tests

## Current Soot-selected checklist runner

Use `rerun102_worker.py` for the current 102-check campaign. Its per-check
inputs are the target source site and an original cluster JUnit method from
`data/crashfuzz/checklist102.json`. `prepare_case_selection.py` supplies only
system-wide binary and communication mapping paths. Soot derives the coverage
methods, branches, and I/O callsites; `soot_selection.py` stores them in the
case's `soot-selection.json`. The runtime agent records and injects only those
selected sites. No per-check I/O or coverage list is required.
The coarse selector reserves a bounded part of its method budget for I/O in
the target's state-reading actor and its callback classes. It also recognizes
system-level RPC and data-transfer APIs and records concrete I/O exception
subclasses constructed by a selected callee or its nearby local callees.
Those classes become additional fault variants alongside generic IOException.
The replay identity keeps the node, actor role, selected callsite, callee, and
per-thread hit number. It normalizes ephemeral socket ports, block IDs, UUIDs,
and JVM object hashes in actor names so a fresh embedded cluster can match an
observed I/O point. A matched injection is still checked separately from a
target exception or test failure.

When the healthy trace contains no selected I/O, the worker automatically
reselects with a wider Soot caller path and reruns that JUnit. It keeps the
expanded selection and healthy trace beside the initial ones for replay. If
the wider path still yields no observed I/O, a final automatic selection uses
an 800-method coarse budget. A transient failure of the healthy JUnit is
retried once, with the first failure log retained.

Run `audit_rerun102_selection.py --result-root /path/to/isolated-results`
on each node to verify that the target and I/O sites came from the Soot
artifact, the healthy JVM applied the same digest, and the campaign did not
declare per-check I/O or coverage sites. Archived campaigns are checked
against their retained result and archive receipt.
The three-node selection audit snapshot is saved in
`data/crashfuzz/static102-selection-audit.json`; it distinguishes runnable
checks from checks without an original cluster JUnit.

```sh
python3 rerun102_worker.py --system Solr \
  --checklist ../../data/crashfuzz/checklist102.json \
  --result-root /path/to/isolated-results --case-id SOLR-40
```

The generic `fuzzer.py` config described below also supports older manual
adapters, so its optional `io_scope` and `coverage_include_prefixes` fields
remain documented for those archived campaigns.

On node0, `archive_completed.py` can watch the result root and copy completed
HDFS campaigns without exception candidates to node1. It verifies
the remote files with an rsync checksum pass before removing local raw trials;
the local case summary and final result remain. Unfinished cases keep their
checkpoints in place.

`data/crashfuzz/static102-offloads.json` records HBase cases temporarily
assigned to node0 or node2. Node1 holds each case's local claim lock while the
other node runs. On node0, `/users/ZhenyuLi/static-rerun/results` points to the
local result root so mirrored artifact paths resolve unchanged on node1.
`mirror_offloads.py --watch` copies a completed case back to node1, verifies
file checksums, releases the lock, and marks the offload mirrored. The table
collector reads the execution host's live summary until that mirror is complete.

`original_hdfs_junit.py` runs an unchanged Hadoop 3.4.3 embedded-cluster
JUnit method in fresh scratch storage. In the current Soot-selected mode, the
ASM runtime agent records the target, I/O, and coverage events; the helper
does not also collect JaCoCo data. Its legacy calibration mode records a raw
JaCoCo file. A passing JUnit run alone never completes a candidate.

`fuzzer.py` reruns one existing cluster based JUnit test and injects faults at
I/O points observed in that test. It reads a healthy runtime trace to find the
target check, exact fault selectors, and initial method/branch coverage. Each
faulted run produces a new trace. The driver uses new I/O families and
production method/branch coverage to schedule the next sequence. It does not
need a runtime graph, closure plan, or per-trial aggregation.
For selected RPC calls that return an object, the post-call hook also records
the return class and the element classes of its immediate object-array fields.
This bounded response shape becomes part of the observed fault identity. A
replay can therefore distinguish a state-changing command response from an
empty response at the same callsite, without declaring either as a per-check
fault site. The selector reserves one in seven choices for an observed
nonempty object-array response; other choices retain the existing coverage,
I/O novelty, temporal, and actor-diversity rules.

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

The standalone fuzzer defaults to **80** trials and **8** faults. The 102-check
JUnit worker uses **80 base trials, up to 240 total trials, and 10 faults**.
After 80 trials it continues until 30 trials have both an exact fault match
and a post-fault target hit, or it reaches the 240-trial cap. If none of the
first 80 trials reaches the target after an exact fault, the worker stops for
workload and scope review. A smaller explicit `--max-trials` remains a hard
cap. `max_seconds` limits active run time if supplied.
Changing only `budget` or `timeout_seconds` keeps the same completed trials.
The checkpoint stores visited sequence IDs as a JSON object for constant-time
deduplication; older list-based checkpoints migrate on resume.
`max_unmatched_retries` defaults to 1: an unmatched sequence gets one fresh
attempt before it is recorded as unmatched. Every mutation adds exactly one
fault from the actual trace after the last applied fault. The scheduler
prefers untested I/O families and coverage while balancing one fault and
longer sequences. Every third trial reserves a slot for an I/O point selected
near a target-side field writer or its actor callback, when one is queued.
This rule uses the same Soot reasons for every check.
Every eleventh selection reserves a slot for a sequence affecting two or more
confirmed logical nodes in the observed runtime identities. Heartbeat and data
threads on one node count as one node. When no queued sequence has two
confirmed nodes, the scheduler falls back to distinct observed actors. This
explores reply loss and subsequent I/O across nodes without declaring any
case-specific fault site.
For MiniDFSCluster, the runtime identifies outbound `DataNode.DataTransfer`
tasks through their enclosing DataNode's configured storage slot, as it does
for heartbeat and inbound DataXceiver actors. An isolated agent build can be
selected with `CRASHFUZZ_RUNTIME_AGENT_JAR` when running the unchanged HDFS
JUnit; campaigns without that environment variable use the repository's
packaged runtime agent.
The DataXceiver and DataTransfer actor scopes also carry that identity into
their SASL helper calls on the same thread. Actor scopes clear on method exit,
including exceptional exit. Exact target throws retain the observed logical
node ID in `target_fatal_exception_nodes` when the runtime supplied one.
New campaigns prefer an untried static I/O callsite in three of every four
selection rounds. The fourth round retains the existing timing and fault-type
diversity rule. This keeps phase and later-occurrence variants from crowding
out distinct I/O locations under a bounded budget. A checkpoint records its
site-diversity version; older campaigns retain their original order unless
explicitly migrated with a saved checkpoint.
New campaigns also distinguish the first, second to third, fourth to seventh,
eighth to fifteenth, and later occurrences of a recurring I/O site when
diversifying the queue. This gives later protocol rounds a chance within a
bounded budget while retaining call-stack families. Resumed campaigns keep
the scheduler version with which they started.

A fully matched trial must prove all requested faults were applied in exact
order and must execute the target check after the final fault. A `lost_target`
trial is discarded from feedback and mutation. An exact post-fault target
exception that exceeds the healthy exception count is a
`target_exception_candidate`. If later planned faults do not occur, the driver
accepts the actually applied faults only when they exactly match a nonempty
prefix of the selected sequence. A new target exception on that prefix is a
`partial_target_exception_candidate`, with `strict_injection=false` for the
unmatched full plan and `strict_applied_prefix=true` for the observed prefix.
Both statuses require source review and strict replay before claiming a bug.
The driver never marks `confirmed_bug` or `quality_complete` automatically.
The healthy JUnit only has to expose an I/O seed. If its target check is
unreached, the driver still tests those observed I/O points: a fault may
expose the target branch. Such a trial contributes feedback only after the
target is reached following the fault.

Each case stores an atomic `state.json` checkpoint, `result.json`, and trial
selectors, traces, command logs, and per-attempt results. A pending sequence
survives process interruption; completed sequences are not rerun. The driver
uses a local file lock and heartbeat claim to prevent two processes on one
host from running the same case at once. Cross-host case allocation belongs
to `coordinator.py`; host-local case paths alone are not shared locks.
