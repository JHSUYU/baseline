# GraphChecker Mallory three-node dispatch preparation

This directory contains the 102-case planner and a gated three-node launcher.
The launcher defaults to a read-only dry run. No campaign has been launched
through it; the native static manifests and a complete pilot must be reviewed
before using `--launch`.

## Verified on 2026-10-13 UTC

| Host | SSH | Java | RAM available | `/dev/shm` free | Root disk free |
| --- | --- | --- | ---: | ---: | ---: |
| node0 | local | OpenJDK 8u492 | 57 GiB | 25 GiB | 2.3 GiB |
| node1 | key-based | OpenJDK 8u492 | 61 GiB | 32 GiB | 3.3 GiB |
| node2 | key-based | OpenJDK 8u492 | 61 GiB | 30 GiB | 1.4 GiB |

All four `/users/ZhenyuLi/.graphchecker-sources/` directories and the
baseline workspace exist on each host. Only node0 has intact Git metadata
for HDFS, HBase, and ZooKeeper; node1/node2 have copied trees whose broken
Git pointers yield no commit. Do not use `git rev-parse` as their provenance
proof. `Mallory/dispatch/verify_sources.py` already knows how to fingerprint
each tracked file against node0's clean commit using
`Mallory/dispatch/source_reference.json`. The source trees together occupy
under 1 GiB on node0. A read-only full tracked-file fingerprint on all three
hosts matched the reference for all four systems (HDFS 15,586 files, HBase
6,062, Solr 13,836, ZooKeeper 1,404). No source or scratch was deleted
during this check.

On 2026-10-13, a subsequent disk audit removed only node0's unused
downloadable HBase 2.4.8 and 3.0.0 binary distributions (856 MiB combined),
its regenerable Ivy cache (211 MiB), and three superseded node2 SOLR-40
`state.json.tmp.<pid>` files (214 MiB combined; their PIDs were absent and
the final state file was newer). No active source, data, evidence, result,
checkpoint, or current immutable snapshot was removed. Node2 remains below
the default 2 GiB durable launch floor. Its large remaining directories are
principally prior experiment evidence, so they need an explicit offload or
compressed-output plan before a full campaign.

## Planned isolation

| Wave | node0 | node1 | node2 |
| --- | --- | --- | --- |
| 0 | HDFS | HBase | Solr |
| 1 | ZooKeeper | idle | idle |

At most three campaigns run at once and at most one system runs on a host.
The second wave starts only when node0 has no HDFS case running. Each case
gets one owner host, one core checkpoint, and a unique trial scratch path.
Agents or workers must not mutate a shared build tree. The worker takes a
nonblocking host `flock` lease, and the launcher refuses a host with an
existing `mgc-` tmux session. Only one system can run per host.

After the native tool is frozen, stage a content-addressed release in each
host's `/dev/shm/mallory-gc/releases/<release-id>/`. It must contain the
GraphChecker/Mallory tool jars, runner Python files, selected class inputs,
per-case config, and all classpath artifacts identified by a manifest of
SHA-256 hashes. Stage the appropriate source tree separately under
`/dev/shm/mallory-gc/sources/<system>-<digest>/` and verify its tracked-file
digest against `source_reference.json` before use. Apply read-only permissions
to staged inputs, publish by atomic rename, and verify the same manifest
again on the worker before a trial. The live repository and old dispatch
release cannot serve as an immutable input while they are being edited.

Place transient per-trial scratch at
`/dev/shm/mallory-gc/trials/<release-id>/<case-id>/<attempt-id>/`. Require a
free-space floor on both `/dev/shm` and the durable filesystem before launch;
the root filesystem currently has too little headroom for full traces. The
worker invokes the new core as
`python3 -m Mallory.core.graphchecker_fuzzer --config CASE.json --out
PERSISTENT_CASE_DIR`, where `PERSISTENT_CASE_DIR` is under
`data/mallory/graphchecker_port/cases/<case-id>/`. The core atomically persists
`checkpoint.json` after each trial, plus `summary.json` at terminal state;
`prepared/weave-receipt.json` pins selected original/woven classes, manifest,
static map, graph jar, and runner bytecode. `/dev/shm` may hold only disposable
scratch and staged release inputs; it cannot hold the sole copy of a trial's
checkpoint or evidence because it does not survive reboot. Never remove
current campaign scratch or legacy results as part of dispatch.

The planner and worker examine only the *new core* checkpoint (schema 1). A checkpoint
with `terminal: true` and a matching `summary.json` is skipped; `status:
running`, `terminal: false` is resumed only with its original
`config_sha256`; a malformed or unfamiliar checkpoint is blocked for review.
Missing config or snapshot receipts are waiting states. For node1 and node2,
the worker reads checkpoints on the owning host; the node0 controller never
uses a local copy to claim their completion. The 102 inventory entries are
never marked complete from the older Mallory table.

## Deployment manifest and launch gate

The deployment JSON has `schema_version: 1`, absolute `release_root` and
`state_root`, `release_files` (every relative release file to SHA-256),
`sources` (system to `{root,paths,digest}`), `configs` (case ID to relative
release config), and exactly these assignments: HDFS/node0, HBase/node1,
Solr/node2, ZooKeeper/node0. It also pins `inventory` and `inventory_sha256`;
the launcher checks that it contains the original 102 distinct case IDs and
that every deployed config belongs to the inventory. The JSON itself can live
outside the release snapshot; `--expected-sha256` pins its bytes on each
worker. Stage identical absolute release and source paths on each assigned
host before launch.

The release includes `Mallory/core/graphchecker_fuzzer.py`,
`Mallory/core/graphchecker_campaign.py`, and this worker. Every release file
and directory is read-only, and every source file/directory is checked against
the tracked-file fingerprint. Case configs may use a `cwd_template` directory
inside a pinned release/source snapshot and set `cwd` to
`/dev/shm/mallory-gc/workspaces/<release-id>/<case-id>`. The worker copies that
template once into a writable case workspace, records its config/template
identity, and refuses an unrecognized preexisting workspace. Static maps,
weave manifests, classpath inputs, class files and graph jar still have to
resolve inside immutable snapshots. The preferred core field is
`trial_cwd_template`: it points to a pinned fixture directory, and the core
copies it into a fresh writable `/dev/shm` cwd for each trial. An omitted
template means an empty fresh trial cwd. The optional dispatcher
`cwd_template` only supplies a case cwd for prepare-time commands.

Before each case, the worker verifies the snapshots again, validates the
native core config and budget, reads its own durable checkpoint, and skips
terminal cases. A changed config, unknown checkpoint, or preexisting case
data without a checkpoint blocks the lane. For a run, it appends full
`launcher.stdout.log` and `launcher.stderr.log` and atomically writes
`dispatch.json` with cumulative launch-attempt elapsed time and evidence
paths. It never removes old
results. The default resource floors are 2 GiB free on the durable disk and
6 GiB free on `/dev/shm`; node2 currently fails the durable floor. The worker
checks the exact Java executable named in each config and rejects non-Java-8
versions. Before each run it rejects selected original/JUnit classes with
classfile major greater than 52. The core checks generated woven and adapter
classes again before the first JUnit starts.

`launcher.py` selects at most one *runnable* case per host by default. A
higher explicit `--max-cases-per-host` only changes that cap. `--launch`
requires a reviewed pilot receipt with `schema_version:1`, `passed:true`,
the exact deployment SHA-256, a pilot case ID, and evidence paths. It performs
remote input/resource preflight before creating any detached tmux session.
Wave 1 waits for all configured HDFS cases to have terminal checkpoints.

```bash
python3 -m Mallory.dispatch.graphchecker_port.launcher \
  --deployment /dev/shm/mallory-gc/deployments/DEPLOYMENT.json --wave 0

# Only after a reviewed full pilot and staged snapshots:
python3 -m Mallory.dispatch.graphchecker_port.launcher \
  --deployment /dev/shm/mallory-gc/deployments/DEPLOYMENT.json \
  --wave 0 --max-cases-per-host 1 --launch \
  --pilot-receipt /persistent/path/pilot-receipt.json
```

The returned `mgc-...` session names can be inspected with `tmux attach -t`.
Use `python3 -m unittest Mallory.dispatch.graphchecker_port.test_plan
Mallory.dispatch.graphchecker_port.test_launcher -v` for the isolated tests.

## 102-check result table

`aggregate.py` reads native `checkpoint.json` and `summary.json` from each
case's owner host via read-only SSH (node0 locally). It emits all 102 inventory
rows, including checks with no config or execution. It records the exact
inventory target source/class/method/line, the selected JUnit workload,
terminal status, completed fault trials, strict injections, post-fault target
reaches, target-exception candidates, and the sum of trial elapsed seconds.
`receipt_status` reports the native campaign receipt independently from
`quality_state` and `quality_reason`. Quality comes from the pinned,
human-reviewed `quality_reviews.json`; the default is `unassessed`. A review
applies only to a terminal receipt with the same config SHA-256, status, and
completed trial count. A changed rerun makes the old review stale and returns
the row to `unassessed` until the metadata is updated. In particular,
ZOOKEEPER-07 is `budget_finished_preliminary`, not high-quality complete:
its 64-trial receipt is terminal, while the static scope misses a read-side
I/O door and the injected fault sites lack diversity.
It cross-checks terminal summaries against checkpoint trial records. A remote
read failure or inconsistent receipt is `receipt_error`, never `unrun` or
`confirmed`. The command does not read the legacy table and does not alter
any trial artifact.

```bash
python3 -m Mallory.dispatch.graphchecker_port.aggregate \
  --inventory Mallory/cases/inventory.json \
  --config-root data/mallory/graphchecker_port/configs \
  --state-root data/mallory/graphchecker_port/cases \
  --out data/mallory/graphchecker_port/final-results.tsv
```

Use `--local-only` only when receipts from all hosts have already been mirrored
into the supplied state root. Without `--out`, the table prints to stdout.
A native differential target-exception trial is marked `candidate`; it is
never auto-confirmed. An optional manual review JSON with `schema_version:1`
and `reviews` entries of `{case_id,mark,reviewer,evidence_paths}` can change a
candidate to `confirmed` or `rejected`; `confirmed` requires at least one
native candidate and explicit evidence paths. The table is a derived view and
may be regenerated at any time.
Use `--quality-file` to supply a different quality review file with
`schema_version:1` and `quality_reviews` entries. Each entry needs `case_id`,
`state`, `reason`, `config_sha256`, `receipt_status`,
`completed_fault_trials`, and nonempty `evidence_paths`. Accepted states are
`budget_finished_preliminary`, `high_quality_complete`, and `needs_rerun`.

## Read-only plan

Once the new case configs exist:

```bash
python3 -m Mallory.dispatch.graphchecker_port.plan \
  --inventory Mallory/cases/inventory.json \
  --config-root data/mallory/graphchecker_port/configs \
  --state-root data/mallory/graphchecker_port/cases
```

The command prints case ID, system, host, wave, config hash, checkpoint state,
and evidence paths. It does not write files or start Java. Run its tests with
`python3 -m unittest Mallory.dispatch.graphchecker_port.test_plan -v`.
