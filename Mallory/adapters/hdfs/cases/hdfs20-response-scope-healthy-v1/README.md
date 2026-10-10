# HDFS-20 heartbeat response-scope healthy validation

This package is staged only. It runs the original
`TestStandbyIsHot#testStandbyIsHot` MiniDFSCluster JUnit once without injected
faults, using adapter commit `9d3ca265cf5eeaaf788385efdd69671df0804fff`.
The adapter JAR, agent JAR, event-time core, source files, compiled target
class, test class, and site file are SHA-pinned in the config and manifest.

Dispatch order on node2: HDFS-20 v4 natural seal/import, HDFS-29 v4 full,
HDFS-30 v4 full, HDFS-34 healthy-only, then this validation. The run script
requires `MALLORY_DISPATCH_ADMITTED=1`, `node2`, the shared
`hdfs-identity-v8-node2.lock`, and a fresh output path
`/tmp/mallory-hdfs20-heartbeat-response-scope-v1-node2-healthy`. Neither the
current campaigns nor their outputs are modified.

Run `python3 preflight.py --static` on node0 for the read-only local checks.
Once admitted on node2, dispatch invokes `run_healthy.sh`; it runs the node2
preflight, the one-trial campaign, and `validate_healthy.py`. The latter writes
`healthy-response-path-gate.json` in the new output directory.

The gate requires one passing JUnit, the exact nonthrowing named DataNode
`BPOfferService.updateActorStatesFromHeartbeat` check, and a concrete heartbeat
call-site door on the same DataNode thread. A uniquely matched request token
must connect that DataNode's request SEND to a NameNode request RECV; the same
token must connect the NameNode response SEND to the DataNode response RECV.
The response RECV must precede the target on the same node, epoch, and numeric
JVM thread ID. The pinned occurrence graph must prove an observed,
time-respecting RECV-to-target path.

The exact response RECV is allowed as the sole **scoped, tokenized root
endpoint**, because `Client#getRpcResponse` occurs outside a named region.
The path must enter the target's named region through the exact handoff token;
no coarse root, legacy root, or root intermediary can satisfy the gate. This
boundary does not claim that every response in the cluster is a heartbeat;
the same-thread heartbeat call-site door and request token establish the
selected response's role. A passing healthy gate admits a future fault-run
design; it is not a bug report or a reinterpretation of HDFS-20 v4 traces.
