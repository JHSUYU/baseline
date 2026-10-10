# HDFS-48 unchanged-JUnit heartbeat response: healthy-only stage

This package selects the original Hadoop 3.4.3
`TestRenameWithSnapshots#testRenameUndo_1` without changing its source or
compiled test class. `HDFS-48-healthy-only.json` permits exactly one
fault-free calibration and disables automatic promotion. It uses pinned
Mallory core, agent, and HDFS heartbeat adapter releases.

The case-local site file preserves the selected
`INodeDirectory.replaceChild` identity check. Its one explicit typed door is
the synchronous `Client.call` invocation of `getRpcResponse` at
`Client.java:1529`. The call is after the request is queued and before its
response is consumed. The door throws `java.io.IOException` at the RPC
response operation boundary, matching the earlier case-local CrashFuzz hook
at `Client.getRpcResponse` entry. The socket read itself occurs on the IPC
connection thread; this is an exception at the response operation, not an
observed operating-system read error.

`BPServiceActor.run` carries the concrete DataNode scope through heartbeat
RPCs. `BPServiceActor.offerService` catches a local `IOException` from
`sendHeartBeat`, sleeps, and continues while service is running
(`BPServiceActor.java:684-805`). Archived CrashFuzz evidence for the unchanged
JUnit has 107 actor-joined BPServiceActor response faults that precede the
selected NameNode check; all 107 JUnits passed and the selected
`IllegalStateException` did not occur. That campaign was graph-free and
provides endpoint and target-retention evidence, not a Mallory event-time
causal path. The old Mallory NameNode `RpcCall.run` pilot used a different
door and lost the target after each of ten effective faults.

## Static preflight

Run `python3 preflight.py --receipt static-preflight.json` from this directory.
It checks the pinned Git commit, clean Hadoop source root, source and class
hashes, agent and adapter hashes, unchanged test selector, one-run budget,
target identity, and the exact typed response door. The archived
`static-preflight.json` passed. It starts no JVM or fault trial.

## Runtime admission after dispatch assigns an isolated lane

Run only the fault-free healthy configuration first. Require Surefire 1/0/0,
the direct setup `@356:branch:2` check on `hdfs-client`, and a separate
nonthrowing `@356:branch:2` occurrence on `hdfs-cluster-1/nn0` after the
rename RPC. The `@358` arm may short-circuit and need not appear. Require a
catalogued `Client.call@1529` `IOException` door on a named
`BPServiceActor` DataNode, and join its RPC endpoint to the same NameNode.
Record whether an event-time root-free path reaches the named target; a
background heartbeat may retain the target without that causal path. Do not
infer a strict path from matching ports or timestamps alone.

No fault plan or full campaign is staged. A later single-fault pilot needs a
separate decision after the healthy result: one effective response-operation
exception in a named heartbeat actor, `offerService` recovery, an original
JUnit pass, and the exact nn0 target after the fault. Track pending IPC calls
and shutdown behavior because the exception occurs after request queueing.

`provenance.json` pins every input and prior evidence. The earlier source
review is `../HDFS-48-target-retention-v1/PHYSICAL_RPC_DOOR_AUDIT_V3.md`.
