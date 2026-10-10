# HDFS-19 Mallory node2 full stage

This package is **staged, not run**. It uses the existing
`TestDFSFinalize#testFinalize` MiniDFSCluster JUnit and the pinned
`BPServiceActor.blockReport` `IOException` door. The budget is 80 fault trials,
3600 seconds, and at most three faults per trial. The full config starts its own
healthy seed and promotes only if Mallory's runtime attestation accepts it.

Run `python3 preflight_hdfs19_node2_full.py --static` from node0 to verify the
package, frozen artifacts, and equivalent source tree without starting Java.
Only dispatch may run `run_hdfs19_node2_full.sh` on node2 after granting
`MALLORY_DISPATCH_ADMITTED=1`. That script shares the node2 Hadoop lane lock
with other HDFS work and checks the node2 source and compiled class hashes
before launching Mallory. Its output path is unique and may be resumed with
the same config.

The prior v2 healthy trial reached the exact assertion on named DataNodes, but
its root-free offline audit found zero target-path I/O doors. The new explicit
block-report door and heartbeat/command bridge remain untested together on
this JUnit. A full run can finish with that causal gap recorded as its outcome;
the gap is not a reason to classify the run as incomplete.

## v2 completion rule

This immutable v2 config keeps the exact named target, passing JUnit and at least one pretarget injectable I/O door as the controller's healthy admission requirements. Graph path quality and offline causal audit are recorded outcomes, not a second admission or completion gate. Report the natural controller terminal and actual completed fault-trial count. The v1 package and output remain untouched.
