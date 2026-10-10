# HDFS-14 named healthy admission

This package stages one no-fault run of the existing parameterized
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite` JUnit.
The Maven selector ends in `*` so both parameter instances run; an exact
method selector previously collected zero tests. The selected Hadoop 3.4.3
check is the six-argument `BlockTokenSecretManager.checkAccess` password
comparison at line 411, followed by the `InvalidToken` throw at line 412.
`DataXceiver.readBlock` calls into this access path on a DataNode worker.

The typed site catalog pins `BPServiceActor.sendHeartBeat` line 563, whose
RPC may raise `java.io.IOException`. The immutable adapter also exposes the
`hdfs:sasl-first-response-read` I/O door during encrypted transfer. Both are
candidate pretarget I/O events; runtime must show one observed, injectable
door with named actor and epoch before the exact selected guard. The
no-fault result must pass JUnit 2/0/0, reach the exact guard without its
selected exception on a named DataNode, and validate the loaded target class
and site catalog. A path from either I/O fault to unequal password bytes is
not established; graph path quality and that causal gap are outcomes.

`HDFS-14-node2-healthy-v1.json` derives from the immutable full v1 config
and keeps the same source, target/test class, agent, adapter, site, and frozen
core hashes. Its budget is one healthy seed, 900 seconds overall, with a
600-second trial timeout. The full 80/3600/max3 package stays separate.

Run `python3 preflight.py --static` on node0 or node2 to verify source lines,
full source digest, SHA-pinned runtime artifacts and Mallory static config
without Java. The host-aware static preflight uses node0's equivalent mirror
or node2's active `hdfs-identity-v8` source. After a separate dispatch GO,
`MALLORY_DISPATCH_ADMITTED=1 ./run_healthy.sh` holds the shared node2 HDFS
lock and starts a fresh output. No JVM was launched to prepare this package.
