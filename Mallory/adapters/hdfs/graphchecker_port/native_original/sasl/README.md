# HDFS SASL transport adapter for original GraphChecker

This optional HDFS 3.4.3 overlay instruments the common
`DataTransferSaslUtil` protobuf send and parse methods, both SASL handshake
implementations, and the two `Dispatcher` executor handoffs. It does not
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
dependency classpath used by the static planner.

`protocol-smoke-receipt.json` records original JUnit proof using combined
engine SHA `0059dfd3`. `TestSaslDataTransfer#testAuthentication` and
`TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` passed. The latter
recorded 150 exact request and 150 exact response SASL send/receive pairs,
with every send preceding its receive and no blocking gap. The original
`TestLeaseRecovery#testBlockSynchronization` also passed with this overlay.
These are protocol gates. The HDFS key-ID WIRE_FLOW still requires a mapped
static scope and runtime producer/consumer observation; HDFS-30 additionally
requires a target-anchored graph and fault-induced target throw.
