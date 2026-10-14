# Two-slot native GraphChecker queue

This queue runs the **native** `Mallory.native_graphchecker_campaign` for the
original 102-case inventory. It never reads Mallory's older custom campaign
results. Each host runs at most two worker processes. A worker takes a shared
host lease (excluding the older one-case `run-next`), an exclusive slot lease,
and an exclusive case lease. The native campaign keeps its own per-trial
checkpoint and fresh JUnit workdir, trace, fault plan, and result under
`STATE_ROOT/CASE-ID/trials/`. All case state and completion receipts stay on
the durable filesystem. `TMPDIR` is unique per case under `SCRATCH_ROOT`.

Use the same absolute inventory, ownership, config, state, scratch, and
isolation paths on all three hosts. `STATE_ROOT` should be the project mount;
`SCRATCH_ROOT` can be `/dev/shm/...`. The queue checks 12 GiB available RAM,
2 GiB free state space, and 4 GiB free scratch space before starting each
case. Change those floors only with the corresponding CLI options. No shared
source or build tree is modified by the queue; preparation and weaving must
have completed before a case becomes runnable. The pinned case config must
direct Java temporary files and cluster data to `{trial_workdir}`.

## Port policy

An isolation profile is required. For a workload whose service listeners all
bind port zero, provide a reviewed JSON receipt. The receipt must say
`all_listeners_bind_port_zero: true`, name the system, and be pinned by SHA-256
in the profile. `required_jvm_args` lists the exact already-pinned case config
arguments that select dynamic ports. For example:

```json
{
  "schema_version": 1,
  "systems": {
    "hbase": {
      "required_jvm_args": ["-Dhbase.test.port=0"],
      "ports": {
        "mode": "ephemeral",
        "receipt": "/ABS/hbase-dynamic-ports.json",
        "evidence": {
          "/ABS/hbase-dynamic-ports.json": "<sha256>"
        }
      }
    }
  }
}
```

For fixed listeners, use `mode: "assigned"` and `cases` entries with a
nonoverlapping `start`/`count` range for every runnable case. Each entry must
also list `required_jvm_args` already present in its pinned case config to
select that range. Pin source or configuration evidence in `ports.evidence`.
The queue rejects overlapping ranges. The queue also scans JUnit logs for an
actual bind collision; a collision writes `invalid-overlap/CASE-ID.json` and
prevents a queue completion receipt until reviewed. It does not erase a native
checkpoint or its evidence.

If an admitted direct campaign uses a different assigned range, pass a
case-scoped `--port-review` to `bind_and_run --bind-only`. The review must pin
the immutable native config, source port assignment, prepared-case receipt,
and owner-host admission; their exact thread ID and port range must agree.
Promotion updates only that case's range under the queue lock, then checks
all assigned ranges for overlap before writing the binding and pilot pins.

## Pilot and full host run

Run one native pilot on its physical owner host. A pilot receipt is written
only after `inspect_case` audits a completed native fuzz budget:

```bash
python3 -m Mallory.native_graphchecker_queue pilot \
  --host node1 --case-id HBASE-01 \
  --config-root /proj/silentfailure-PG0/ZhenyuLi/native/config \
  --state-root /proj/silentfailure-PG0/ZhenyuLi/native/state \
  --scratch-root /dev/shm/mallory-native/trials \
  --isolation /proj/silentfailure-PG0/ZhenyuLi/native/isolation.json \
  --pilot-receipt /proj/silentfailure-PG0/ZhenyuLi/native/pilot.json
```

After the pilot, run two slots on each physical owner host. The pilot receipt
pins the inventory, ownership, config, summary, and isolation profile. The
host command checks it and preflights all currently runnable cases before
spawning workers:

```bash
python3 -m Mallory.native_graphchecker_queue run-host \
  --host node1 --slots 2 \
  --config-root /proj/silentfailure-PG0/ZhenyuLi/native/config \
  --state-root /proj/silentfailure-PG0/ZhenyuLi/native/state \
  --scratch-root /dev/shm/mallory-native/trials \
  --isolation /proj/silentfailure-PG0/ZhenyuLi/native/isolation.json \
  --pilot-receipt /proj/silentfailure-PG0/ZhenyuLi/native/pilot.json
```

Use `--host node0` or `--host node2` on those nodes. A second invocation
resumes unfinished cases from the native checkpoint. It skips terminal cases
and reconciles a missing queue receipt without rerunning their JUnit. Each
audited terminal case has a separate JSON completion under
`STATE_ROOT/.native-queue/completions/CASE-ID.json` with source location,
native trial counts, elapsed time, and an exact bug-candidate mark. Only
`native_tested_complete: true` means an audited native campaign finished its
configured fuzz budget. It does not establish target-closure coverage,
temporal causality, or a new bug; `terminal_quality_note` records material
coverage gaps and any pending corrected rerun. A native-blocked case remains
distinct. This queue does not overwrite the old 102-row TSV;
the native dispatcher `status` command can build the audited native table.

For a sealed campaign whose graph receipt differs under newer analysis code,
`frozen_terminal.inspect_frozen_terminal` runs the inspector from that case's
hash-verified Python archive in a separate process. It pins the engine JAR,
checkpoint, summary, and every trial result and graph summary used by the
inspection. A frozen audit cache is reusable only while its completion,
source archive, engine JAR, and trial hashes remain unchanged. An archived
source that lacks the original inspector fails this path; a source and event
review must then describe its own method rather than claim a frozen inspector
run. No JUnit or fault trial is started by this audit.

A pre-JUnit static timeout can be recorded under
`STATE_ROOT/.native-queue/preparation-notes/CASE-ID.json`. The 102-row exporter
checks the note's exact review, request, and source preflight SHA-256, then
reports `preparation_static_timeout` with zero preparation JUnit and fault
trials. It leaves terminal trial counts unset and
`native_tested_complete: false`. A later bound campaign can still proceed
from its own immutable healthy gate and checkpoint.

A healthy JUnit whose original graph admission timed out can be pinned under
`STATE_ROOT/.native-queue/admission-notes/CASE-ID.json`. The exporter verifies
the immutable config, healthy result, exact target occurrence, and review.
It records one preparation JUnit and zero fault trials, without terminal credit.

A source-only original JUnit eligibility review can be pinned under
`STATE_ROOT/.native-queue/eligibility-notes/CASE-ID.json`. The exporter checks
the exact inventory row, selected JUnit, prior source review and failed
opt-in JUnit log, and every reviewed source file SHA-256. It reports
`skipped_no_eligible_original_cluster_test` with zero **native queue** JUnit
and fault trials, leaves terminal counts unset, and never grants
`native_tested_complete`. The SOLR-40 review applies to the pinned checkout
and current harness; fixture repair may make its original test eligible.

For an alternate original JUnit whose upstream test source and compiled class
exist only on the owner host, `bind_and_run --alternate-source-receipt` can add
a small shared copy of those two exact files to an existing binding. The
receipt pins their hashes, the official alternate attestation, and the
owner-verified source commit. Promotion accepts this monotonic evidence
addition only when every other binding field is unchanged. On the owner host
the original files and clean source revision are still checked; on another
host the shared byte-identical copies provide the source/class proof.

The isolation contract requires a real system-specific port setting or a
reviewed dynamic-port receipt. An unprepared case remains pending; no case is
made runnable merely by this queue.

## Adopt an existing concolic campaign

For a campaign started directly from the original native concolic adapter,
use `bind_and_run --bind-only` with `--adapter-proof`,
`--recording-admission`, and `--validation-stdout`. The admission stdout must
name the exact config path being bound. The binding verifies the original
JUnit and target occurrence, inventory throw site and source bytes, selected
task plan, weave receipt, and source-built engine. A shared source archive can
be supplied with `--target-source-archive` when the original source path is
local to its owner host. The config's Zero VM executable is pinned too. The
frozen Python source tree and tar must both contain the original feedback
Java entry point used after the JUnit. All evidence is pinned by SHA-256. A direct campaign
keeps its existing checkpoint and `.campaign.lock`; binding never launches a
second worker. A failed healthy seed remains blocked and cannot be promoted as
a completed fuzz run.

Tests that do not launch a distributed JUnit:

```bash
python3 -m unittest Mallory.native_graphchecker_queue.test_queue -v
```
