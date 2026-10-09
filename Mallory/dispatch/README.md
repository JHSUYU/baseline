# Mallory dispatch on node0, node1, and node2

The 102 original checks have immutable, disjoint system-owned shards in
`shards/`: HDFS 38 on node0, HBase 30 on node1, and Solr plus ZooKeeper 34 on
node2. Each host runs a **local** scheduler in tmux, with its own case result,
checkpoint, scratch, and build directories. The nodes do not share a
filesystem. `launch.py` stages only Mallory source/config plus the shaded agent
jar on node1/node2, validates prerequisites, then starts sessions.

```sh
python3 Mallory/dispatch/launch.py --phase calibration            # print plans
python3 Mallory/dispatch/launch.py --phase calibration --apply    # stage + validate + tmux
python3 Mallory/dispatch/launch.py --hosts node2 --phase calibration --cohort v2 --apply
python3 Mallory/dispatch/launch.py --phase campaign \
  --core-release-manifest Mallory/dispatch/releases/<ID>/manifest.json --apply
python3 Mallory/dispatch/collect.py                               # verify and sync results
python3 Mallory/dispatch/collect.py --hosts node2 --cohort v2     # v2 archive and receipts
```

Sessions are `mallory-node0-calibration`, `mallory-node1-calibration`, and so
on. The same launch command resumes unfinished cases after a session ends.
`tmux attach -t mallory-node0-calibration` attaches locally; use SSH first for
node1/node2. Logs are at `data/mallory/dispatch/<host>/<phase>.log` on the
respective host.

The scheduler reads each case's config from `Mallory/cases/<ID>.json` and
checks its cluster test, source hashes, compiled artifact, agent jar, and
source provenance. Preliminary configs enter the **calibration** phase only:
the core runs healthy trial 0 into `data/mallory/calibration/<ID>` and must
stop before fault trial 1. `campaign_queue.py` replays the healthy trace with
the pinned fixed core, checks the exact loaded-class catalog, named target,
eligible door, and a hash-bound positive passing JUnit result, then writes an
immutable promoted config. Once a config records this runtime attestation and
its expected loaded-class SHA-256, the **campaign** phase runs the fault budget
into `data/mallory/cases/<ID>`. The core independently checks the loaded site
catalog and node identity on its own healthy seed before mutation.

`source_reference.json` pins all tracked files of the four clean source trees
at the inventory commits. This permits full content verification on the
remote nodes, whose copied worktrees have broken `.git` links. A declared
patched overlay uses a receipt with the patch SHA-256, modified-file hashes,
and compiled-artifact hashes. A byte-identical isolated worktree can instead
use `source_equivalent_root`; the scheduler checks its full tracked-file
fingerprint against the pinned source tree.

After an intentional inventory change, regenerate the source reference and
stage again:

```sh
python3 Mallory/dispatch/verify_sources.py \
  --inventory Mallory/cases/inventory.json \
  --make-reference Mallory/dispatch/source_reference.json
python3 Mallory/dispatch/stage.py --apply
```

Independent runtime adapters may keep pristine source and pin their JARs, site
files, and runner artifacts in config `runtime_artifacts` entries with absolute
paths and SHA-256 hashes. This is checked before dispatch and again at launch.
Changed calibration configs use `--cohort v2`, which writes to
`data/mallory/calibration_v2/<ID>` and separate dispatch state. The first
calibration and its archive remain available.

A second JVM lane must use a separately verified source/build root and its own
`--lane-id`. The worker holds the host-local lane lock for the entire case
attempt, including after a coordinator restart. An external campaign that does
not use this lock must never share the same source/build root. A clean Solr
lane is available at `~/.mallory-worktrees/solr-lane2` on node2; its configs
must explicitly pass that path as `--source` to the direct JUnit runner.
When another campaign is using a runner or JAR path, stage only immutable
versioned files with `stage.py --selected PATH ... --apply`. The selected
stager verifies each staged file's SHA-256 and leaves unselected live files
untouched. `prepare_solr_lane.py` can generate immutable lane-specific configs
from adapter-owned configs; use a new cohort directory after any input change.
After selected staging, launch with `--skip-stage` so `launch.py` performs its
source/config/runtime preflight without copying the entire Mallory tree over a
live campaign.

Fault campaigns require an immutable core release. Build one only after the
core is validated, stage the release directory on owner hosts, and use the
same manifest for preflight and the worker. The release contains its own
`Mallory` package path, so `PYTHONPATH` selects the pinned core even from the
repository directory. The worker rechecks all release file hashes immediately
before launching a case.

```sh
python3 -m Mallory.dispatch.core_release --out-root Mallory/dispatch/releases
python3 -m Mallory.dispatch.stage --hosts node1 node2 \
  --selected Mallory/dispatch/releases/<ID> --apply
PYTHONPATH="$PWD/Mallory/dispatch/releases/<ID>:$PWD" \
  python3 -m Mallory.dispatch.campaign_queue --host node0 \
  --core-release-manifest Mallory/dispatch/releases/<ID>/manifest.json
```

Remote admission reserves 5 GiB and estimates 4 GiB per concurrent case.
For a measured smaller case, `lane_handoff --case-estimate-gib N` changes only
that case estimate; the 5 GiB reserve remains in force. Record the measured
case sizes and override in the versioned handoff manifest.
Each isolated lane runs one JVM at a time; separate source/build/test-data roots
and port allocation are required before a second lane is enabled. Every attempt has a unique
scratch/build root. A worker owns a per-case lock and writes an atomic exit
receipt. A restarted scheduler skips a live worker, recovers its receipt, and
accepts terminal scientific results only when the case ID and
`last_dispatch_attempt_id` match. Process exit alone is not a scientific
result. The collector pulls only terminal case summaries, the exact worker
specification and exit receipt, and a lossless compressed evidence archive
from their owner host. It checks SHA-256, attempt identity, and the pinned
core release, restores the archived trial evidence, runs the offline causal audit, then
regenerates `data/mallory/checklist102.{json,md}` from Mallory data. Historical
CrashFuzz outcomes are not Mallory outcomes.

`watch_collect.py` can sync completed remote calibrations during a long shard.
`finalize_local.py` archives, audits, and reports a terminal node0 campaign;
both accept a tmux wrapper so a disconnected coordinator does not lose the
terminal evidence step. An audit exit code of 2 records a scientific quality
failure while retaining the raw archive.

`lane_handoff.py` can run in a host-local tmux session to select one audited,
runtime-attested original case at a time from a pinned `campaign_ready.json`.
It requires a healthy named observed path door, verifies the promoted config
and 80-trial/1-hour cap, waits for any named predecessor's terminal audit,
then runs the case through the ordinary scheduler. After each terminal case,
it archives, audits, updates the checklist, and moves to the next ready case.
A coordinator restart reads the same queue and per-case checkpoint; it does
not repeat finalized cases. If no eligible case exists, it waits for a refreshed
queue and reports that state in its log. Use `--dry-run` to inspect selection.

For a predecessor run by an adapter outside the lane scheduler,
`external_predecessor.py` verifies copied terminal result and audit bytes against
a SHA receipt and the selected immutable core release before the successor
starts. A cross-host case offload pins an `ownership_revision_path` and SHA in
the ready manifest. The revision lists only the moved cases, the original
ownership SHA, inventory and source-reference SHAs, and a full effective
ownership map used by the collector. The original 102-case owner file stays
unchanged. `watch_collect_lanes.py --ownership <effective-map>` then collects
the offloaded cases from the assigned host.

The handoff coordinator retains the complete compressed archive. After the
terminal audit and report, it verifies each large expanded MiniCluster scratch
file against its archive member before reclaiming that duplicate disk space.
`Mallory.dispatch.collect.materialize_campaign_evidence` restores the exact
files for later replay. `--retain-expanded-scratch` disables this compaction.
Admission leaves at least 5 GiB free; a low-disk condition stops the handoff
before the next case.

`admission_index.py` builds a read-only 102-row ledger grouped by system. It
recognizes a completed case only when its terminal result, final core audit,
and archive or external SHA receipt agree. Healthy seeds require a named
observed path door, and a promoted config must pin that seed's audit SHA.
Cases with an alternate JUnit selector remain held until a versioned inventory
and source-reference pair is admitted. The ledger records each terminal case's
`duration_seconds`; it never starts trials or treats calibration as completion.
An existing-test search that finds no suitable cluster workload can write a
`data/mallory/source_gaps/<ID>/receipt.json` bound to its source-review manifest
and zero-door healthy result. This marks `no_suitable_cluster_test` until a
later healthy run proves an observed path to the target.

```sh
python3 -m Mallory.dispatch.admission_index \
  --core-release-manifest Mallory/dispatch/releases/<ID>/manifest.json
```

Read-only checks:

```sh
python3 Mallory/dispatch/scheduler.py --manifest Mallory/dispatch/shards/node0.json \
  --hosts-file Mallory/dispatch/shards/node0-hosts.json \
  --inventory Mallory/cases/inventory.json --phase calibration --dry-run
python3 -m unittest Mallory.dispatch.test_scheduler
```
