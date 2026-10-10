# HDFS-18: bind the heartbeat door to its concrete DataNode

The v3 healthy JUnit passed and reached `DatanodeDescriptor.injectStorage@537`
on `hdfs-cluster-1/nn0`. The intended typed RPC door also executed twice:
`BPServiceActor.sendHeartBeat@563` at event sequences 92 and 143. Both door
events had `node=unknown`, so the runtime feedback rejected them as fault
points. The site rule, bytecode call owner and descriptor, and loaded site
catalog all matched. This is an actor identity gap, not an absent heartbeat.

The pinned v3 adapter wraps `BPServiceActor.run` once. Its first event is an
`unregistered_receiver` identity gap because the actor thread starts before
`MiniDFSCluster` finishes registering the DataNode. The same thread later sends
RPCs as `dn0` through separate registered connection hooks, yet the heartbeat
door remains in the actor's original unknown scope. This v4 adapter wraps the
specific `sendHeartBeat(boolean)` method with the existing
`HdfsHooks.serviceActorEnter` hook. Each call resolves the actor's actual `dn`
field and its registered logical node, then restores the prior scope on normal
and exceptional exit. No node is inferred from a thread name or timing.

`named-actor-adapter.patch` applies to adapter base commit `597689a8` and
includes the earlier PROVIDED map NameNode owner patch. The isolated adapter
build used the pinned agent SHA in `package-manifest.json`; all four adapter
unit tests passed. The new tests cover late registration and bytecode scope
insertion. The v4 healthy package reuses the immutable v3 Hadoop source and
compiled classes on node2; only the adapter JAR and healthy output directory
change. Static preflight passes without starting a JVM.

Node2 dispatch can run one healthy JUnit with
`MALLORY_HDFS18_V4_NODE2_GRANT=healthy-only ./run_healthy.sh` after acquiring
the HDFS lane. Run `review_healthy.py` on that trial's `result.json`. A full
fault campaign remains on HOLD unless it reports `GO`: one passing JUnit, a
named exact target, and a named typed heartbeat door in that target's observed
closure. The reviewer does not infer a fault effect or a bug from this healthy
run. The v3 trial is preserved separately.
