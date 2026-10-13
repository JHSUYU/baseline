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

`payload-smoke-receipt.json` records a second unchanged-JUnit diagnostic
using a pinned original-engine JAR with only `MessageDoors.class` replaced.
It passes 1/1, pairs all 152 SEND/RECEIVE identities, and has no payload API
gap. The same block-recovery Daemon parent gap remains. The seven-argument
compatibility door preserves WIRE_FLOW values already staged by GraphChecker;
a focused runtime test carries a staged handle across the outbound/inbound
pair. This does not prove the HDFS key-ID source-to-sink mapping, since the
JUnit has not yet run the accepted static target/port weave. The vendored
engine does not yet implement the later CODEC_PORT walker: when a transport
declares that codec, the compatibility door emits a blocking gap instead of
claiming its payload leaves were propagated.

`combined-engine-smoke-receipt.json` records a further unchanged-JUnit run
against the combined original engine pin `0059dfd3`. Its 152 Hadoop IPC sends
and 152 receives pair by exact transport identity, with each send before its
receive. The one block-recovery Daemon gap is now source-specific: the caller
still stands in the JUnit client root while the recovery worker belongs to
`dn3#epoch0`. The adapter leaves that parent edge unproved. This remains a
protocol smoke, without target weave or a fault-induced target exception.

The HDFS key-ID mappings also have a separate transport boundary. In Hadoop
3.4.3, `SaslDataTransferClient.getUserNameFromEncryptionKey` appends the
`DataEncryptionKey.keyId` integer to the SASL username; on the server,
`SaslDataTransferServer.getEncryptionKeyFromUserName` parses that integer and
passes it to `BlockTokenSecretManager.retrieveDataEncryptionKey`. The current
native adapter records `HADOOP_IPC` only. Its exact IPC pairs do not prove an
`HDFS_SASL` message edge or the key-ID WIRE_FLOW mapping. The separate
`sasl/` overlay now provides a source-backed same-JVM SASL handoff; its
original-JUnit protocol proof is recorded in `sasl/protocol-smoke-receipt.json`.
A mapped static scope and observed producer/consumer ports are still needed
before the key-ID mapping can be used in a claimed causal closure.
