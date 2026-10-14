# Native GraphChecker 102-check dispatcher

This package reads the original 102-case inventory and the pinned three-host
ownership map. It is separate from the former custom-graph campaigns and their
import table. It never counts those old runs as native completion.

`prepare-next` derives each case's target and original JUnit selector from the
102-row inventory. It invokes a **shared per-system native adapter**, which
must produce original GraphChecker static scope, a REGION_STATE recording
weave, a closed healthy recording, and the recording-derived concolic weave.
The native adapter supplies a proof for each stage. The dispatcher checks
those proofs and promotes a `native_graphchecker_campaign` config at
`CONFIG_ROOT/CASE-ID.json`. It never supplies a hand-picked I/O door. The
former custom-graph `prepare_case.py` scripts do not implement this protocol.
At present, no real per-system recipe is included, so a missing config remains
`needs_native_preparation`; this package alone does not make any case ready.

The shared ZooKeeper adapter is
`python3 -m Mallory.native_graphchecker_dispatch.zookeeper_native_adapter
/ABS/zookeeper-profile.json {request} {output}`. Its profile names pinned
source/classes, the source-built planner and runtime classpaths, the
communication map, Java, bounded budget, and a native protocol gate. Put the
profile and every referenced source/classpath/mapping artifact in the recipe's
pin maps. There are no case IDs, target branches, or I/O doors in the profile.
For ZooKeeper, `prepare-next` audits the nested gate inputs too: its full
session directory, verifier source/build/receipt, static map, postweave and
adapter builds, passing seed JUnit stdout, closed trace manifest, profile,
Java, adapter code, and every ordered classpath entry
must be present in the matching pin map. An omitted input is rejected before
the preparation cache can be reused.

Build the shared gate from a closed, unchanged ZooKeeper seed session:

```bash
python3 -m Mallory.native_graphchecker_dispatch.build_zookeeper_protocol_gate \
  /ABS/shared-zookeeper-profile.json /ABS/seed-evidence.json \
  /ABS/new-protocol-gate.json
```

The profile's `protocol_gate` must equal the new gate path. The seed evidence
JSON has these six absolute paths:

```json
{
  "session_dir_path": "/ABS/healthy/sessions/seed-id",
  "healthy_stdout_path": "/ABS/healthy/stdout.log",
  "healthy_trace_manifest_path": "/ABS/healthy/trace/streaming_trace_manifest.json",
  "static_map_path": "/ABS/static/static_scope_map.jsonl",
  "postweave_class_tree_path": "/ABS/recording-woven-classes",
  "adapter_build_path": "/ABS/zookeeper-protocol-classes"
}
```

The seed evidence names the original session directory, passing JUnit stdout,
closed streaming trace manifest, static map, postweave class tree, adapter
build. The builder compiles its pinned `NativeZooKeeperSessionVerifier`
source against the original engine. The verifier uses the
original `SessionReader` and discovers ZooKeeper SEND/RECV wire sites from
the schedule. It admits only paired producer endpoints with no session gaps.
The generated gate contains hashes of its inputs and no target or fault door.
Each new case must still pass its own healthy JUnit, reach its own target, and
yield one executable original GraphChecker target task.

The adapter derives the original THROW from inventory, runs original
GraphChecker static seed analysis and REGION_STATE weave, then applies the
ZooKeeper protocol and actor post-passes in that order. It executes the exact
inventory JUnit without faults, invokes the original target occurrence
resolver in AUTO guard mode, and admits only its observed check and the unique
matching original Scheduler `TARGET_REACH_CLOSURE` task. The native anchor
ordinal comes from that task's `targetBranch.occurrence`. The concolic weave
is then cached under the same exact input pin. Both post-passes use
`NativeZooKeeperCombinedPostWeave.java`, whose compiled class must be pinned
in the profile classpath. The adapter refuses to launch until a frozen
protocol and actor-attribution gate exists.
The gate must pin the source/class tree, communication map, postweave tree,
adapter build, source-built engine, static map, full original session tree,
and a source-built `SessionReader` verifier receipt with empty `incomplete()`.
Admission reruns the pinned verifier against the pinned session and compares
its fresh result with the gate receipt; this is a lightweight read, not a JUnit.
The original `SessionManifest` has no closure field; a manifest alone cannot
pass this gate. The verifier also parses the schedule and attests a `SEED`
session with paired typed SEND/RECV events and no pairing gaps. The gate must
show an unchanged JUnit pass; target reach is checked for each new case.
Campaign JUnit trials use fresh
`{trial_workdir}` directories. The adapter itself performs static Soot and
both weaves only during preparation; `run-next` only reruns the cached woven
JUnit and records a new trace for each fault trial.

The recipe file must pin the 102-row inventory SHA and contain one reusable
command per implemented system. For example, the schema for one adapter is:

```json
{
  "schema_version": 1,
  "inventory_sha256": "<sha256 of inventory.json>",
  "systems": {
    "hdfs": {
      "argv": ["python3", "/ABS/native-hdfs-adapter.py", "{request}", "{output}"],
      "timeout_seconds": 3600,
      "pins": {"/ABS/native-hdfs-adapter.py": "<sha256>"},
      "source_tree_pins": {"/ABS/hadoop-source": "<file-tree-sha256>"},
      "classpath_pins": {"/ABS/hdfs-classes": "<file-tree-sha256>"},
      "mapping_pins": {"/ABS/hdfs-runtime-map.json": "<sha256>"},
      "class_tree_pins": {"/ABS/hdfs-classes": "<class-tree-sha256>"}
    }
  }
}
```

The adapter receives absolute `request.json` and output directory paths. It
must emit `case.json`, `adapter-proof.json`, a static scope receipt, and a
REGION_STATE recording-weave receipt. It must also emit the original runtime
`MalloryTargetOccurrenceResolver` receipt: the selected check must have been
observed in the closed healthy trace, with an exact event, call, and
occurrence address. The dispatcher verifies this receipt against the original
JUnit, target throw site, trace manifest, graph, scope, and skeleton bytes;
`first` or an unobserved check cannot be used as a selector. The proof names
those receipts and
original source evidence for the selected cluster JUnit. The request contains
the check, original JUnit, and build identity, with no fault point list.
Preparation fails closed if the original cluster JUnit or any original
GraphChecker receipt cannot be verified.

```bash
python3 -m Mallory.native_graphchecker_dispatch prepare-next \
  --host node1 --recipes /ABS/native-recipes.json \
  --config-root /ABS/CONFIG_ROOT --state-root /ABS/NATIVE_STATE_ROOT
```

Each case has a locked preparation state under `STATE_ROOT/CASE-ID/preparation`.
The cache key includes the inventory target and JUnit, pinned source bytes,
classpath bytes, runtime mapping, adapter command, and verified source-built
GraphChecker engine. Identical inputs reuse the static scope and both weaves;
the dispatcher audits their receipt and output hashes before reuse. A changed
input fails closed and requires a fresh isolated preparation directory. Each
fault trial still runs the already woven original JUnit and creates a fresh
session trace. Static analysis and weaving do not run inside the trial loop.
If the controller disconnects during adapter execution, its PID and start
ticks prevent a second launch; a closed adapter output can be adopted after
the process exits. The recipe and produced config are host-local, so run
`prepare-next` on each case's owner node.

On each owner host, run one case at a time. `run-next` checks the physical host
name (`node0`, `node1`, or `node2`) and uses a host lock plus a case lock.
`native_graphchecker_campaign` has its own trial lock and resumes at the last
closed trial. Repeating the command advances to the next unfinished case. A
terminal native checkpoint is never run again, even when a receipt is damaged;
such a case is reported as `receipt_error` for inspection.

```bash
python3 -m Mallory.native_graphchecker_dispatch run-next \
  --host node1 --config-root /ABS/CONFIG_ROOT \
  --state-root /ABS/NATIVE_STATE_ROOT
```

Read the 102-row table from node0. `--remote` asks node1 and node2 to audit
their own local state over the existing SSH connection and refuses missing or
version-mismatched responses. Paths passed to the command must exist with the
same spelling on all hosts. Without `--remote`, `status` reads only the local
filesystem; use `--host` for an owner-only view.

```bash
python3 -m Mallory.native_graphchecker_dispatch status \
  --config-root /ABS/CONFIG_ROOT --state-root /ABS/NATIVE_STATE_ROOT \
  --remote --format tsv --out /ABS/data/mallory/native-102-results.tsv
```

The table always retains the 102-case denominator. Each row includes source
file, function, line, check code, original JUnit, owner, elapsed JUnit time,
fault trials, strict injections, post-fault target retention, exact target
throws, candidate count, and receipt path. `tested_candidate` and
`tested_no_target_throw` require a closed native budget, reached healthy
target, and audited original SessionReader/ClosurePlanner summaries. A closed
budget with no strict target-retained fault trial is `tested_inconclusive`.
`native_blocked` is terminal but not a completed fuzz check.

For new REGION_STATE trials, the terminal auditor also replays every exact
target check/throw pair from the fault-event bytes. It compares the count with
the healthy run and marks a strict post-fault increase as a candidate when the
target is retained, even if the graph selected a different check occurrence.
The per-trial receipt keeps this raw differential separate from the selected
occurrence's graph and temporal verdict. A raw candidate is a source-review
lead; it does not by itself establish a causal bug. Historical trial receipts
without raw fields retain their original selected-target audit semantics.

For a case with no suitable **original cluster JUnit**, record a reviewed
terminal disposition in a separate JSON file, then pass `--reviews FILE` to
both `run-next` and `status`:

```json
{
  "schema_version": 1,
  "no_eligible_original_cluster_junit": {
    "HBASE-32": {
      "reason": "Source review found no original cluster test reaching the target",
      "evidence_paths": ["/ABS/path/to/source-review.md"]
    }
  }
}
```

The review file is accepted only when every evidence file exists. This
disposition is terminal for scheduling, but `native_tested_complete` remains
false. It cannot override an existing native checkpoint.

The terminal audit checks the recording-derived admission, pinned weave and
static scope files, exact per-trial fault plan and ordered `FAULT_DOOR` /
`FAULT_APPLIED` receipts, landed native session bytes, target occurrence in
the original closure, target throw receipts, and recomputed graph delta. An
assertion failure or JUnit exit code cannot stand in for `TARGET_THROW`.

Receipt-level tests (no live distributed JUnit):

```bash
python3 -m unittest Mallory.native_graphchecker_dispatch.test_checklist \
  Mallory.native_graphchecker_dispatch.test_preparation -v
```
