# HDFS-32 request identity audit

The existing `hdfs32-heartbeat-node2-full-v2` package is ready for a bounded
node2 campaign. Its healthy MiniDFSCluster JUnit passed and reached the exact
`DataNode.deleteBlockPool` guard twice on `hdfs-cluster-1/dn0`. The fault is a
typed `BPServiceActor.sendHeartBeat` `IOException`; Hadoop catches and retries
it. Source review does **not** establish that this fault changes the
`BlockPoolManager.bpByBlockPoolId` entry read by the guard. This remains a
target-retention exploration, with graph paths and target exceptions measured
as outcomes.

`audit_trial.py` reads a trial's trace and JUnit receipt. It pairs each
DFSAdmin door with an IPC request SEND, DataNode RECV, exact guard, and client
response using the transport correlation and the physical actor. It labels
the first request `force=false` and second `force=true` only when the pinned
Hadoop `TestDeleteBlockPool#testDfsAdminDeleteBlockPool` source, both complete
request paths, and a passing JUnit receipt support that source-order binding.
The trace itself does not carry the force argument. An exact target throw
still needs source review before a bug claim.

Verified healthy observation:

```sh
python3 Mallory/adapters/hdfs/cases/hdfs32-request-identity-audit-v1/audit_trial.py \
  --trial data/mallory/healthy_observations/HDFS-32-node2-healthy-v1/trials/r0000 \
  --healthy
```

The checked receipt is `healthy-receipt.json`: two distinct correlated
requests, exact checks at events 165 and 174 on `dn0` epoch 0, first error
response and second success response, no injected fault and no target throw.
The v2 campaign's static preflight passed on node0 with config SHA-256
`58e2aef2ed97201eed67495ae9749d38e9eef82bc264e72aef487022228dc11b`.
Runtime admission and the checklist row remain dispatch responsibilities.
