# HDFS SASL transport adapter for original GraphChecker

This optional HDFS 3.4.3 overlay instruments the common
`DataTransferSaslUtil` protobuf send and parse methods, both SASL handshake
implementations, `DataStreamer.run`, and the two `Dispatcher` executor handoffs. It does not
select a target, exception, or fault site. The original JUnit methods remain
unchanged.

The sender adds a unique receipt token as protobuf unknown field 50000,
writes and flushes the complete delimited message, then calls original
GraphChecker `MessageDoors.outbound`. The receiver parses that token and waits
for the exact successful send receipt before `MessageDoors.inbound`. The
correlation and attempt identify each handshake leg; request and response
roles come from the instrumented client/server handshake scopes. No send is
recorded for a failed write or flush. Unmatched, missing, or ambiguous
receipts are blocking gaps. The rendezvous is in process, so a separate JVM
peer is an unmatched gap; this adapter only claims same-JVM MiniClusters.

The HDFS bridge aliases each DataNode's `saslClient` and `saslServer` to its
registered node identity. `Dispatcher.dispatchBlockMoves` and
`executePendingMove` carry the submitting scope through their executor
queues. These hooks are system-level boundaries used by Balancer moves;
without them the original `TestBalancerWithEncryptedTransfer` emitted 30
unattributed SASL sends. The adapter refuses to install symbolic values from
a send whose GraphChecker trace context is empty.

`DataStreamer.run` opens the client source before its NameNode RPC and first
SASL send, and closes it on normal or exceptional exit. For an external
streamer, its replayable source ID is `streamer-` plus the first 32 hex digits
of SHA-256 of the original `DataStreamer.src` and a per-path run ordinal.
HDFS allows one writer lease per path at a time; the ordinal distinguishes a
later reopen or append in the same JVM. If an existing source already owns
the thread, the streamer and handshake anchors inherit that exact source.
The adapter records a blocking gap if `src` is unavailable and does not
invent a source. This source attribution bridge lives in the original engine's
`MalloryOriginalHdfsSourceRoots`, outside its upstream vendor tree.

Build a fresh overlay after the native IPC overlay:

```bash
python3 Mallory/adapters/hdfs/graphchecker_port/native_original/sasl/build_sasl_overlay.py \
  --native-overlay /path/to/native-ipc-overlay \
  --hdfs-client-classes /path/to/hadoop-hdfs-client/target/classes \
  --engine-jar /path/to/immutable-original-engine.jar \
  --classpath-file /path/to/exact-ordered-classpath.txt \
  --out /path/to/new-sasl-overlay
```

Put the new overlay first on the original JUnit classpath. The builder
requires exact patch counts, refuses to overwrite output, and hashes every
patched class and input. Static `process_dirs` and the concolic `-i` roots
must then use the **same patched class bytes**, with the exact ordered
dependency classpath used by the static planner. Build and pin a fresh
original GraphChecker engine JAR containing
`MalloryOriginalHdfsSourceRoots` before building this overlay. Existing
engine JARs do not contain that helper.

For HDFS-11, the formal healthy gate uses the unchanged HDFS 3.4.3 JUnit
`org.apache.hadoop.hdfs.TestEncryptedTransfer#testLongLivedClientPipelineRecovery[0]`.
It must be rerun with fresh source, engine, overlay, static selection and
weave pins. Verify the target check and exact target-throw baseline, then
verify source-backed client `HADOOP_IPC` and first-leg `HDFS_SASL` edges in
the target closure. Only generic statically selected fault and coverage
units enter the campaign; the adapter declares no manual door or fault site.
The separate Mallory runtime-port v11 healthy receipt is an exploratory
protocol gate, not evidence that this original-engine configuration passed.

`protocol-smoke-receipt.json` records original JUnit proof using combined
engine SHA `0059dfd3`. `TestSaslDataTransfer#testAuthentication` and
`TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` passed. The latter
recorded 150 exact request and 150 exact response SASL send/receive pairs,
with every send preceding its receive and no blocking gap. The original
`TestLeaseRecovery#testBlockSynchronization` also passed with this overlay.
These are protocol gates. The HDFS key-ID WIRE_FLOW still requires a mapped
static scope and runtime producer/consumer observation; HDFS-30 additionally
requires a target-anchored graph and fault-induced target throw.

## Key-ID target gate

The unchanged `TestBalancerWithEncryptedTransfer#testEncryptedBalancer0`
enables encrypted data transfer and block tokens in its `@Before` method,
then runs `TestBalancer.testBalancer0Internal(conf)`. This is a suitable
original-JUnit workload for the SASL transport gate. It is not the HDFS-30
check: that check is `BlockRecoveryWorker.getActiveNamenodeForBP` at the
`activeNN == null` guard (line 582) and `IOException` throw (line 583).

The separate HDFS-11 check is
`BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])`. It reads
`allKeys.get(keyId)` on line 551, tests `key == null` on line 552, and throws
`InvalidEncryptionKeyException` on line 555. The mapped producer is
`SaslDataTransferClient.getUserNameFromEncryptionKey`: its compiled code
passes `DataEncryptionKey.keyId` to `StringBuilder.append(int)` before
encoding the SASL username. On the server,
`SaslDataTransferServer.getEncryptionKeyFromUserName` parses the first
username component and passes it through
`BlockPoolTokenSecretManager.retrieveDataEncryptionKey` to the HDFS-11
method. The generic `data-encryption-key-id` WIRE_FLOW row in
`communication-mappings.jsonl` declares these producer and consumer ports.

Native fault trials can start once the unchanged JUnit passes under the
mapped weave, reaches the line-552 target check, and records exact
SEND/RECEIVE identity for the relevant SASL request. Any unresolved symbolic
key-ID port is recorded as a gap in the approximate graph. A strong key-ID
causal claim additionally needs both declared ports observed under that same
request identity. A detected HDFS-11 bug requires a generic selected fault
and the line-555 target THROW in the fault's target occurrence. A successful
SASL exchange or a normal key lookup alone does not establish that result.
Do not alter the JUnit or add a dedicated key-ID fault site to meet this gate.
