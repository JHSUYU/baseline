# HDFS-20 Mallory node2 full stage

This package is **staged, not run**. It uses the existing
`TestStandbyIsHot#testStandbyIsHot` MiniDFSCluster JUnit and the pinned
`BPServiceActor.sendHeartBeat` `IOException` door. The budget is 80 fault
trials, 3600 seconds, and at most three faults per trial. The full config
starts its own healthy seed and promotes only if Mallory's runtime attestation
accepts it.

Run `python3 preflight_hdfs20_node2_full.py --static` from node0 to verify the
package, frozen artifacts, and equivalent source tree without starting Java.
Only dispatch may run `run_hdfs20_node2_full.sh` on node2 after granting
`MALLORY_DISPATCH_ADMITTED=1`. That script shares the node2 Hadoop lane lock
with other HDFS work and checks the node2 source and compiled class hashes
before launching Mallory. Its output path is unique and may be resumed with
the same config.

The previous healthy heartbeat pilot reached the exact check 60 times on named
DataNodes with a passing JUnit, but all 66 explicit heartbeat doors had
`node=unknown`, leaving zero observed target-path I/O doors. The pinned node2
bridge has not run with this JUnit. This causal gap is an outcome to record
after a full run, rather than a separate completion gate.

## v3 preflight correction

On node0, `--static` validates against the `hdfs-lane2` source mirror. On node2, the same `--static` option validates against the active `hdfs-identity-v8` source tree. The v2 config already used the correct node2 runtime cwd; v3 changes only its package revision pin and uses a distinct output path. The full trial budget, named target, eligible I/O door, and graph outcome rule are unchanged. No JVM was started to prepare this revision.

## Completion rule

This immutable v2 config keeps the exact named target, passing JUnit and at least one pretarget injectable I/O door as the controller's healthy admission requirements. Graph path quality and offline causal audit are recorded outcomes, not a second admission or completion gate. Report the natural controller terminal and actual completed fault-trial count. The v1 and v2 packages and outputs remain untouched.
