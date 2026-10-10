# HDFS-18 full-v5a: exact PROVIDED heartbeat path

The SHA-sealed v4 healthy MiniDFSCluster JUnit passed 1/0/0 and reached
`DatanodeDescriptor.injectStorage@537` on `hdfs-cluster-1/nn0`. The second
`BPServiceActor.sendHeartBeat@563` typed `IOException` door was named
`hdfs-cluster-1/dn0` and belonged to the observed target closure. Its exact
event chain was door 133, request SEND 134, matching NameNode RECV 135,
`injectStorage` REGION_ENTER 137, and target checks 138/139. The request RPC
and region parent edges were both recorded with `certainty=observed`.
`prior-healthy.tar.gz` and `prior-healthy.receipt.json` preserve that evidence
with SHA-256 pins in `package-manifest.json`. This is a healthy path, not a
fault result or bug claim.

The full-v5a config reuses the compiled adapted Hadoop JUnit and v4 adapter.
It selects only the typed heartbeat site (`auto.io.doors=false`), disallows
outside-closure and local-timeline candidates, and requires event-time paths
with coarse roots rejected. The budget is **80 fault trials, 3600 seconds,
maximum 3 faults per sequence**, with a 600-second trial timeout. The fault
type is `EXCEPTION`, and the configured typed site supplies `IOException`.
The exact `DatanodeDescriptor` target class SHA remains pinned.

On node2, dispatch grants `MALLORY_HDFS18_V5A_NODE2_GRANT=full-v5a` and starts
`run_full_node2.sh` under its normal lane supervision. The runner first runs
a **fresh** healthy `r0000` in calibration-only mode. `healthy_gate.py`
checks the passing JUnit, named actor identities, loaded target class, trace
hash, typed door, matching RPC request token, observed RPC and region edges,
and target checks in the same region occurrence. It verifies that every
initial queued fault is the matched typed `dn0` door, then SHA-pins the fresh
node/occurrence/token path in `healthy-gate.json` and promotes that checkpoint.
Only then does the controller execute fault trials. The runner verifies the
promotion before and after resuming. A failed gate leaves the healthy output
for diagnosis with zero fault trials started. If the process stops after
writing `healthy-gate.json` but before promoting `checkpoint.json`, the next
launch rechecks the sealed `r0000` evidence and queue, reuses the byte-identical
gate, and completes the checkpoint promotion. A changed gate fails closed.
The runner also resumes an interrupted calibration and accepts an already
promoted checkpoint without rerunning `r0000`.

Offline checks: `python3 -B preflight.py --static` and
`python3 -B -m unittest discover -s . -p 'test_*.py' -v`. Both avoid a Hadoop
JUnit run. This package is isolated from the running full-v5 output and has
not launched a JUnit or fault trial.
