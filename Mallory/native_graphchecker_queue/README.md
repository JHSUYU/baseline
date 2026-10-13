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
`native_tested_complete: true` is a completed fuzz check. A native-blocked
case remains distinct. This queue does not overwrite the old 102-row TSV;
the native dispatcher `status` command can build the audited native table.

The isolation contract requires a real system-specific port setting or a
reviewed dynamic-port receipt. An unprepared case remains pending; no case is
made runnable merely by this queue.

Tests that do not launch a distributed JUnit:

```bash
python3 -m unittest Mallory.native_graphchecker_queue.test_queue -v
```
