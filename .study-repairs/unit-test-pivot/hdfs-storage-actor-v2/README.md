# HDFS storage actor identity V2

This independent overlay repairs the runtime identity gap in the archived
HDFS-22/23/25/34/35 startup campaigns. It runs the unchanged Hadoop 3.4.3
MiniDFSCluster JUnit methods. It uses neither GraphChecker nor its graph/runtime
JAR. The archived case checkpoints remain historical evidence; this directory
owns new traces and a separate resumable campaign checkpoint.

## Source and bytecode hook audit

| Hook | Hadoop 3.4.3 source path | Purpose |
| --- | --- | --- |
| Deepest `MiniDFSCluster.startDataNodes(...)` entry | `hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/MiniDFSCluster.java:1666` | Increment logical startup episode once per DataNode startup call. |
| `DataNode` constructor, just before `startDataNode(...)` | `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java:593` | Bind the DataNode object to its startup episode, within-call slot, and configured data directories before any BPServiceActor starts. The later `instantiateDataNode` return hook checks the same object and does not register it twice. |
| `BPServiceActor.run()` entry | `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java:881` | Adopt that DataNode in the actual heartbeat/startup thread, with its NameNode address. |
| `Client.getRpcResponse(Call, Connection, long, TimeUnit)` entry | `hadoop-common/src/main/java/org/apache/hadoop/ipc/Client.java:1566` | Obtain `Connection.getRemoteAddress()`; classify only an exact match to the current actor's NameNode address as `NN0`. |
| Storage `doTransition`, `doRollback`, and `doUpgrade` entries | `BlockPoolSliceStorage.java`, `DataStorage.java` | Attach exact `StorageDirectory` and volume to each check. An async upgrade callable rejoins its actor through the **same StorageDirectory object**, not a thread name. |
| Original exact branch and I/O hooks | `PatchHdfsStorage.java` | Preserve the existing check sites, exception sites, version reads, previous-version reads, and Jacoco production coverage. |

`actorKey = startup episode + DataNode slot + normalized configured data dirs`.
The trace also carries the in-run DataNode object identity, raw configured data
dirs, raw storage file path, actual RPC endpoint, and actor NameNode endpoint.
The file `sourceKey` includes actor and exact normalized storage path. The RPC
`sourceKey` includes actor and `peer=NN0`; its dynamic port is retained in raw
evidence but never stripped and silently merged across actors. A missing actor,
storage, or peer mapping is logged as `unbound` and cannot inject. Each plan
step is matched atomically and in order.

The source relationship used for selecting file I/O is the same DataNode
**volume** (`dfs/dataN` or `dfs/datanodeMaster`) as a later target. This permits a DataStorage VERSION
read at `dfs/data1` to precede a block-pool check under
`dfs/data1/current/BP-ID`; it excludes `data2`. RPC I/O requires the same actor
and verified `NN0` endpoint. A trial counts for a case only after every planned
fault matches in order and the same actor reaches that case's check after the
last fault. When the last fault is file I/O, its volume must also match the
later target. Target exceptions are recorded as candidates pending replay and
source review, never automatically called new bugs.

## Offline gate

From this directory:

```sh
python3 offline_smoke.py
```

This compiles the shared overlay, checks all six rewritten classes with ASM
`CheckClassAdapter`, and tests actor/volume/peer/order/target matching using
synthetic traces. It does not start a cluster JVM.

The first V2 startup healthy seed used a return-time actor registration hook.
Its original JUnit passed, but the BPServiceActor threads had already entered,
so its target events were unbound. That failed calibration remains in
`evidence/startup`; the constructor-hook rerun uses a separate evidence
directory. Every JUnit launch enables `-Xverify:all`.

## Healthy calibration after a host slot is free

The `startup` group runs one original JUnit that checks five candidates,
including HDFS-22/23. HDFS-24/26/27/37 use the separately versioned
`hdfs-storage-actor-v2-later` work directory because HDFS-27 needs the bare
`dfs/data` actor-volume mapping. Its overlay has a different digest; neither
source nor evidence is mixed with this running startup campaign.

| Group | Original JUnit | Cases |
| --- | --- | --- |
| `startup` | `TestDFSStartupVersions#testVersions` | HDFS-22/23/25/34/35 |

```sh
python3 calibrate.py --group startup --output evidence/startup-constructor --max-seeds 1
python3 calibrate.py --group startup --output evidence/startup-constructor --max-seeds 2
```

The first command runs only seed `a`, so other node1 campaign owners can
inspect timing before seed `b`. The second reuses its manifest and runs only
seed `b`. Calibration writes `healthy-a`, `healthy-b`,
and `healthy_receipt.json`. The receipt fails if either JUnit fails, an exact
target is unbound, an actual RPC endpoint is not classified, a case has no
stable same-actor upstream I/O selector, or the two healthy seeds disagree on
target actor identities. It also requires the same overlay digest in both
manifests, plus nonempty JaCoCo execution and production branch coverage.
Commands for the remaining groups are in the later directory's
`audit/upgrade_rollback_calibration.md`.

The constructor-hook `startup` calibration on node1 passed on 2026-10-07:
the original JUnit passed in 37.944 s and 41.562 s, all five startup target
checks had bound DataNode and storage identities, and 91 exact upstream I/O
selectors were stable across seeds. The compact durable receipt is
`audit/startup_constructor_healthy_receipt.json`; full traces and JaCoCo files
remain under node1 `evidence/startup-constructor/`.

Archived healthy runs used about 8 MiB and 43–68 s each. Allow at least
2 GiB free for the first two-seed calibration and 8 GiB before a full campaign;
these are conservative planning limits, not measured V2 resource use. Run
one group at a time on a free host so timing-sensitive tests do not compete
with other cluster JVMs.

## Campaign, budget, and resumption

```sh
python3 campaign.py --group startup --output evidence/startup-constructor --max-attempts 600
```

The campaign starts only with a passing two-seed receipt. Its atomic
`campaign-state.json` lists the queue, completed sequence IDs, an in-flight
sequence, per-case effective counts, coverage, I/O families, and the actual
time of every JUnit attempt. Restart the same command to resume: a completed
sequence is not rerun, and a finished attempt manifest is reused if checkpoint
writing was interrupted. An incomplete trial may be retried.

If three strictly injected file VERSION-read faults remove every later target,
the selector prioritizes bound NameNode RPC points while no effective trial
has been observed. The discarded file trials remain in the checkpoint as
attempted, with zero effective count. `--pause-after-first-effective` can stop
after a strict fault followed by a same-actor target so that its trace can be
audited before more mutation trials. The first such startup trial is recorded
in `audit/startup_first_effective.json`: one actor-bound RPC `IOException`,
original JUnit pass, and HDFS-22/23/25/35 exact checks afterward on that
actor. HDFS-34 did not have a same-actor target after that fault.

Subsequent sequence selection adds a per-case progress term to its coverage and
fault-depth score, and penalizes file I/O families that have repeatedly
removed the target. This brings HDFS-34's own episode 3–8 RPC seeds forward
without attributing another actor's later check to it. Every tenth selection
samples the oldest queued bound RPC for exploration.

For HDFS-34, the two healthy seeds place its `DataStorage.doTransition`
namespace guard in startup episodes 3–8 on `dfs/data1`, each immediately
preceded by an actor-bound `NN0` RPC and a VERSION read on the same volume.
The first effective RPC sequences targeted episode 1, whose later checks are
different sites. The case-specific source family and both raw seed mappings
are recorded in `audit/hdfs34_upstream_family.json`.

Each case has a base goal of **80 effective same-actor post-target trials**,
with up to **8 faults** per sequence. If any of its last eight effective trials
adds a production coverage branch or a new eligible I/O family, that case
extends to **128 effective trials** and **10 faults**. A queue that exhausts
early is reported with its actual count. `--max-attempts` is a safety bound on
distinct sequences, not a substitute for the effective goal; it can only be
raised when resuming. This V2 state does not promote any case status by itself.
