# ZOOKEEPER-05 node0 full campaign

This package pins the original `QuorumRestartTest#testRollingRestart` workload,
the `Follower.followLeader()` guard at bytecode branch 99, and the
`IOException` throw at bytecode 104. The fresh campaign budget is 80 fault
trials, 3600 seconds, and at most 6 faults per trial. The earlier six fault
trials and healthy probes are SHA-pinned historical evidence; they are not
counted toward this fresh budget.

`pins.json` contains the exact SHA-256 input manifest. `run.py
--source-preflight` is a no-JVM check of the restored source overlay and
compiled artifacts. The original source worktree was absent at staging time;
it was restored from the recorded base commit and overlay patch. All 15
modified source files and seven test source files match the recorded receipt.
Nineteen of 21 recorded compiled artifacts were recovered by exact SHA-256.
After the ZOOKEEPER-06 lane release, `LearnerHandler.class` and
`MalloryZkHooks.class` were rebuilt with an offline Maven compile. All 21
class hashes then matched the receipt before the full campaign started.

The runner requires `MALLORY_ZK05_NODE0_GO=1`, the completed ZOOKEEPER-06
result and successful driver exit, and the node0 source lock. It admits a
run only above a 6.0 GB free disk floor plus 300 MiB reserve and stops the
build or campaign if free disk falls below the floor plus 150 MiB. A stopped
campaign resumes with `run.py --resume` after checking its pinned config.

The runner writes the fresh output to
`data/mallory/campaigns/ZOOKEEPER-05-5820-node0-full-v1`. Its terminal
result is accepted only at `budget_exhausted` or `queue_exhausted`; the
offline causal audit and trace hashes are collected. An exception or
target reach alone is not a graph path finding. Assess any target claim from
the observed, time-respecting fault-to-check graph in the raw trial evidence.
