# HDFS original GraphChecker protocol adapter

This adapter keeps the generic MiniDFSCluster, MiniJournalCluster, DataNode,
block-recovery Daemon, and Hadoop IPC hooks installed by the adjacent
`graphchecker_port` patcher. It replaces the hook implementation with a bridge
to the **original** `edu.uva.liftlab.graphchecker.runtime` session. The
original HDFS JUnit source and selected method are unchanged.

`build_native_overlay.py` copies an immutable, already patched generic HDFS
overlay, compiles the bridge against an original GraphChecker engine JAR, and
puts the new classes ahead of that overlay on the trial classpath. The build
refuses to overwrite output and records hashes for the engine, ordered
classpath, source, and compiled classes. The generated bridge is derived from
the adjacent generic HDFS bridge with three checked transformations:

1. Route its source, asynchronous handoff, and IPC calls through
   `NativeHdfsDoors` and the original GraphChecker runtime.
2. Index a prepared request/response before the sender completes so an
   in-process receiver may wait for the exact transport handoff. `sent()`
   invokes the original `MessageDoors.outbound` only after Hadoop reports a
   successful `IpcStreams.sendRequest` or `Responder.doRespond`. A failed
   handoff does not emit SEND.
3. Pass the actual Hadoop response `rv` to the original payload API when
   available. Client requests use the exact `Client.Call.rpcRequest`.

The IPC rendezvous key is Hadoop's client ID, call ID, retry count, and
request/response half. Missing ownership or message context is a blocking
gap. Source epochs follow MiniDFSCluster and MiniJournalCluster restart hooks.
`HdfsRuntimeSource` resolves the original GraphChecker source of an IPC Call
without assigning a reused Connection to a later request root.

Build an isolated overlay from a previously validated generic one:

```bash
python3 Mallory/adapters/hdfs/graphchecker_port/native_original/build_native_overlay.py \
  --source-overlay /path/to/generic-overlay \
  --engine-jar /path/to/immutable-original-engine.jar \
  --classpath-file /path/to/exact-ordered-classpath.txt \
  --out /path/to/new-native-overlay
```

Run one original JUnit with `new-native-overlay:original-engine:<exact ordered
classpath>` and `CAUSYNTH_TRACE_OUTPUT_DIR` pointing to a fresh directory:

```text
edu.uva.liftlab.graphchecker.runtime.NativeHdfsJUnitRunner
  org.apache.hadoop.hdfs.TestLeaseRecovery testBlockSynchronization
```

`communication-mappings.jsonl` is the system-level HDFS 3.4.3 WIRE_FLOW map
(SHA-256 `7405076ba63dfbde94d720ca1bfd73a10d019e188888148e20fd029092074928`).
Pass its absolute path as `-Dcausynth.communication.mappings=...` to the
static planner. The map is for HDFS wire keys; it does not declare a fault
site for HDFS-30 or replace Soot's static scope.

The interim unchanged-JUnit protocol smoke in `smoke-receipt.json` used
original engine `73082d6c`: JUnit passed 1/1, and all 152 request/response
SEND events matched 152 RECEIVE events by exact transport identity. This
engine lacks the payload-aware seven-argument `MessageDoors.outbound`, so 76
messages have blocking `UNSTATED_VALUE` gaps. One block-recovery Daemon had
an unproven parent scope. This smoke proves protocol identity and original
JUnit execution only. It has no HDFS-30 target weave, target attribution, or
target closure. Rebuild and rerun with the final payload-aware engine and
matching exact classpath before accepting a static scope or fault campaign.
