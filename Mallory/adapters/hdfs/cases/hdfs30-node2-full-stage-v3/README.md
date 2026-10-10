# HDFS-30 Mallory node2 full stage

This package is staged and **has not been run**. It uses the checklist's original `TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization` three-DataNode HA MiniDFSCluster JUnit. Its immutable full config budgets 80 fault trials, 3600 seconds, and at most three faults per trial. The controller starts with its own healthy seed, and its strict runtime attestation decides whether it can promote to fault trials. A natural terminal with an unadmitted healthy seed or missing causal path remains a completed run with that gap as its outcome.

Checklist status before this run: `healthy_node_identity_missing` (`pending_seed`): the original-selector healthy JUnit passed and executed the line-582 check with an unknown DataNode actor. No named HDFS-30 target admission exists.

The target is the exact `BlockRecoveryWorker.getActiveNamenodeForBP` guard at line 582; the `IOException` throw follows at line 583. The site catalog selects one typed upstream `IOException` door. The line-563 `sendHeartbeat` I/O door is caught by `offerService`. A failed reply skips that reply's actor-state update and commands; it does not itself clear the active actor. A target-retaining fault needs an observed heartbeat/status to recovery-worker schedule.

The scoped heartbeat/recovery adapter assigns `hdfs-cluster-1/nn0` through `nn2` and `dn0` through `dn2` to this one-cluster JUnit, then binds the concrete recovery-worker DataNode and records task handoffs. These actor names remain expected until verified in the new trace. The healthy trace must establish an eligible candidate I/O door; actor-path relation and offline audit quality are reported outcomes. Generic local timelines and coarse roots are excluded by the config. No fault-retention or target-exception claim is made from source review alone.

Run `python3 preflight_hdfs30_node2_full.py --static` on node0 to verify package SHA-256 pins, the frozen core and agent/adapter, class images, and the equivalent Hadoop source fingerprint without Java. Only dispatch may run `run_hdfs30_node2_full.sh` on node2 with `MALLORY_DISPATCH_ADMITTED=1`. The runner shares the node2 Hadoop lock with HDFS-19/20, checks the node2 source and compiled class hashes, and writes to its unique resumable output directory. Do not treat a controller process exit alone as a terminal; inspect `result.json` and `checkpoint.json` for Mallory's natural status.

## v3 preflight correction

On node0, `--static` validates against the `hdfs-lane2` source mirror. On node2, the same `--static` option validates against the active `hdfs-identity-v8` source tree. The v2 config already used the correct node2 runtime cwd; v3 changes only its package revision pin and uses a distinct output path. The full trial budget, named target, eligible I/O door, and graph outcome rule are unchanged. No JVM was started to prepare this revision.

## Completion rule

This immutable v2 config keeps the exact named target, passing JUnit and at least one pretarget injectable I/O door as the controller's healthy admission requirements. Graph path quality and offline causal audit are recorded outcomes, not a second admission or completion gate. Report the natural controller terminal and actual completed fault-trial count. The v1 and v2 packages and outputs remain untouched.
