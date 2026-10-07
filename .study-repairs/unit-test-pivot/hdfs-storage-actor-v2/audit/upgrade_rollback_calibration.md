# Remaining HDFS storage groups: offline launch plan

The shared overlay and `calibrate.py` already contain the original Hadoop 3.4.3
JUnit mapping. The following commands are prepared for a separately released
host slot. No extra cluster JVM should be started alongside the node1 startup
campaign without a resource lease.

`TestDFSUpgrade` and `TestDFSRollback` loop over one and two configured
DataNode directories and deliberately create valid and invalid storage states.
Their expected-failure subtests can throw at a target site even in a healthy
run. A postfault target exception is therefore recorded as a replay/source
review candidate; its presence alone cannot establish a new bug. The
`TestDatanodeLayoutUpgrade` workload covers the HDFS-27 asynchronous upgrade
path directly; its legacy healthy trace reached that guard on a pool thread.
The legacy original healthy traces already contain three target throws at
HDFS-24 and three at HDFS-37; HDFS-26 and HDFS-27 contain none. V2 records
the healthy actor, storage-volume, and exception-class signatures from two
new seeds and annotates later matching throws. A matching signature still
requires exact-plan replay and source review; it is never silently discarded.

| Group | Original JUnit method | Exact target checks |
| --- | --- | --- |
| upgrade | `TestDFSUpgrade#testUpgrade` | HDFS-24 `BlockPoolSliceStorage.doTransition` layout/ctime guard |
| layout_upgrade | `TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout` | HDFS-27 `BlockPoolSliceStorage.doUpgradeNamespace` namespace guard in its async callable |
| rollback | `TestDFSRollback#testRollback` | HDFS-26 `BlockPoolSliceStorage.doRollback` layout/ctime guard; HDFS-37 `DataStorage.doRollback` layout/ctime guard |

From the V2 directory, in an isolated tmux session per group:

```sh
python3 offline_smoke.py
python3 calibrate.py --group upgrade --output evidence/upgrade-constructor --max-seeds 1
python3 calibrate.py --group upgrade --output evidence/upgrade-constructor --max-seeds 2
python3 calibrate.py --group layout_upgrade --output evidence/layout-upgrade-constructor --max-seeds 1
python3 calibrate.py --group layout_upgrade --output evidence/layout-upgrade-constructor --max-seeds 2
python3 calibrate.py --group rollback --output evidence/rollback-constructor --max-seeds 1
python3 calibrate.py --group rollback --output evidence/rollback-constructor --max-seeds 2
```

Run the second seed only if the first original JUnit passes and its target,
actor, storage, and I/O receipt is clean. Each group must pass two original
JUnit runs with `-Xverify:all`; JaCoCo production coverage and branch entries
must exist; every exact check must have a DataNode startup episode, slot, and
storage identity. A preceding I/O must have the same actor, plus the same
storage volume for a file point or the actor's exact `NN0` endpoint for RPC.
Each case needs at least one stable exact I/O selector across the two seeds,
matching target actor sets, and identical overlay digests. In HDFS-27, an
asynchronous storage task must rejoin through its `StorageDirectory` object;
thread-name or bare path matching is insufficient. Any missing binding fails
closed and triggers source/bytecode hook repair before fuzzing.

After a passing receipt, launch one resumable group campaign at a time:

```sh
python3 campaign.py --group upgrade --output evidence/upgrade-constructor --max-attempts 600 --timeout 360
python3 campaign.py --group layout_upgrade --output evidence/layout-upgrade-constructor --max-attempts 600 --timeout 360
python3 campaign.py --group rollback --output evidence/rollback-constructor --max-attempts 600 --timeout 360
```

The per-case base budget is 80 effective same-actor postfault checks with up to
8 faults per sequence; coverage or eligible I/O novelty in the last eight
effective trials conditionally extends to 128 effective checks and 10 faults.
No legacy case checkpoint is imported into these V2 counts.

## Host, ports, and scratch before the first seed

The runner starts one Java 8 process per seed or fault attempt with `-Xmx3g`
and a 360-second external timeout. Each `--output` creates separate
`scratch/data`, `scratch/tmp`, and `scratch/logs`; `test.build.data`,
`java.io.tmpdir`, and `hadoop.log.dir` point there. Trace, JaCoCo data,
coverage lists, JUnit output, and the manifest stay alongside that scratch.
The Hadoop test resources are read from the node-local
`hdfs32/worktrees/hadoop/hadoop-hdfs-project/hadoop-hdfs/src/test/resources`;
check that directory exists on the selected host before launching. The
working source on node0 uses a different path, so node0 is not an implicit
fallback. On 2026-10-07 node0 had only 2.7 GiB free disk.

| Group | Seed directories under V2 `evidence/` | Original healthy duration in legacy run | Port behavior in the original test |
| --- | --- | ---: | --- |
| upgrade | `upgrade-constructor/healthy-a`, `healthy-b` | 43.449 s | `MiniDFSCluster.Builder` default NameNode port 0; DataNode transfer, HTTP, IPC listeners use `127.0.0.1:0` unless a test supplies a port. |
| layout_upgrade | `layout-upgrade-constructor/healthy-a`, `healthy-b` | 17.572 s | Same port-0 builder and DataNode path; one configured DataNode. |
| rollback | `rollback-constructor/healthy-a`, `healthy-b` | 49.158/48.824 s for the same original JUnit in old HDFS-26/37 runs | Same port-0 builder and DataNode path. |

For every fault plan the scratch is under
`<group>/runs/<sequence-id>/attempt-1/scratch` (or `attempt-2` when the
first ordered injection did not match). `TestDFSUpgrade#testUpgrade` has its
own JUnit `@Test(timeout = 60000)` and was 43.449 s in the old unbound run;
run its two healthy seeds in a free slot and treat a timing failure as a
calibration failure. The V2 campaign retains every raw attempt. Startup V2
currently uses about 8 MiB per single-attempt run (295 MiB for 30 plans), so
reserve several GiB for a 600-attempt campaign plus retry and fixture data.
