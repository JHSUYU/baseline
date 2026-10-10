# ZOOKEEPER-11 epoch full stage

This case-local package runs a **fresh** healthy seed for the existing
three-peer `CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile`
JUnit and, only if Mallory attests its exact target, continues to a full
**80 fault trial / 3600 second / at most 3 faults per trial** campaign. The
selected check is `QuorumPeer.loadDataBase()@1169:branch:2`; the selected
`IOException` throw is `@1175:throw:1`. The unchanged test creates stale
`currentEpoch` and valid `currentEpoch.tmp` on its first peer, so a passing
healthy run takes the nonthrowing temp-file recovery path on `zk0`.

The old `zookeeper-zk11-clean-v2-lane2` source directory is absent. This
stage uses the currently pinned baseline overlay at
`/users/ZhenyuLi/.mallory-worktrees/zookeeper`. Its `QuorumPeer.java`,
unmodified JUnit source, compiled `QuorumPeer.class`, and compiled JUnit class
have the same SHA-256 values as the prior scoped healthy source. The overlay
and all inputs are pinned in `pins.json`; a fresh runtime loaded-class and
target check is mandatory before faults. No worktree or build was created.

The prior healthy JUnit passed 1/1 and observed the exact nonthrowing guard on
`zk0`, epoch 2. Its only qualified pretarget door is a same-occurrence
`readLongFromFile` at event 793, immediately before guard event 794. That is
`observed_local_timeline` evidence, **not an observed graph path**. A later
one-fault pilot applied `IOException` at the same door and lost the guard:
zero target-retaining trials. Source shows the general file-read exception
exits `loadDataBase` before the epoch comparison. The source and raw hashes
are recorded in
`data/mallory/admissions/ZOOKEEPER-11-fa5f-fault-model-target-lost.json`.
This stage does not claim a target-retaining fault model or a new bug.

The config keeps `reject_coarse_roots` and `require_event_time_paths`, while
allowing the opt-in local timeline door. The offline audit will distinguish
observed graph paths, local timeline only selections, exact injection,
postfault target retention, and selected throws. Those are outcomes of the
run, not assumptions made by this stage. The runner has the same node0
ZooKeeper lane lock as ZK05/ZK10/ZK13. It checks a 6 GB disk floor plus
300 MiB reserve before dispatch and stops a running process below the floor
plus 150 MiB headroom.

Read-only preflight, safe while another ZooKeeper JVM lane runs:

```sh
python3 Mallory/adapters/zookeeper/cases/ZOOKEEPER-11-epoch-full-v1/run.py --preflight
```

After dispatch releases the node0 ZooKeeper lane and confirms free disk:

```sh
MALLORY_ZK11_NODE0_GO=1 python3 Mallory/adapters/zookeeper/cases/ZOOKEEPER-11-epoch-full-v1/run.py --run
```

The runner never starts on its own. A running checkpoint resumes with the
same command; a terminal checkpoint is preserved. Output goes to
`data/mallory/campaigns/ZOOKEEPER-11-epoch-full-v1/` with raw trial receipts,
JUnit reports, driver exit, offline causal audit, and a collection receipt.
No ZooKeeper JVM or fault trial has been started by this package.
