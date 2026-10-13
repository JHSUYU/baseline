# Original GraphChecker communication catalogs

The files in this directory are **system protocol** declarations for the
source-built original GraphChecker `WireFlowCatalog`. They are not lists of
fault doors or mappings chosen for one ad hoc check. A planner JVM loads one
file with `-Dcausynth.communication.mappings=<absolute JSONL path>`. Its
`WireFlowCatalog.fromConfiguration` resolves each named concrete method and
capture against the Soot Jimple of the analysed program, checks that both
capture types equal `javaType`, and refuses malformed applicable rows. An
unresolved row is skipped because the analysed program does not hold both
endpoints; a run claiming a particular protocol edge must inspect the emitted
`communicationCallSites` and `wire_handoff` rows rather than treating a
configuration file as evidence that the edge was selected.

## ZooKeeper 3.8.7 quorum handshake

`zookeeper-3.8.7.jsonl` contains two directed `long` values. They belong to
ZooKeeper's quorum protocol and can be reused for all checks using the same
compiled version:

| Packet | Producer capture | Consumer capture | Source evidence |
| --- | --- | --- | --- |
| FOLLOWERINFO/OBSERVERINFO zxid | `Learner.registerWithLeader`: argument of `QuorumPacket.setZxid(long)` | `LearnerHandler.run`: first `QuorumPacket.getZxid()` | `Learner.java:491-503` sets the accepted epoch into `qp.zxid` and sends `qp`; `LearnerHandler.java:471-523` reads the first packet and derives `lastAcceptedEpoch` from its zxid. |
| LEADERINFO zxid | `LearnerHandler.run`: `newLeaderZxid`, argument 1 of the first four-argument `QuorumPacket` constructor | `Learner.registerWithLeader`: first `QuorumPacket.getZxid()` after `readPacket` | `LearnerHandler.java:529-543` writes and flushes `LEADERINFO`; `Learner.java:503-515` reads it and compares its epoch with the learner's accepted epoch. |

The capture declarations refer to one value in each message. They do not
equate every packet with every other packet carrying a `long`. Distinct port
IDs separate the two directions. The generated `QuorumPacket` API has
`setZxid(long)`, `getZxid()` and
`QuorumPacket(int,long,byte[],java.util.List)`; it is generated from
`zookeeper-jute/src/main/resources/zookeeper.jute` in the unchanged source
build. The source hashes used for the ZK 3.8.7 check were:

```text
Learner.java        3827ccefc4a632b3f37ebe5258f4c97c142211675a5a22801aac1ae2122cb830
LearnerHandler.java ba5702c3fb346c3599fc38738c8a491faeda80394d47bbac51872be9e6b7a79d
```

The source-built original analyzer was run against the unchanged ZooKeeper
3.8.7 compiled classes and `QuorumRestartTest#testRollingRestart` scope with
this mapping property. It emitted **2** `communicationCallSites`, **2**
`wire_handoff` edges and **2** RPC port rows in the Mallory weave manifest.
The captures resolved to `Learner.registerWithLeader#u10` ->
`LearnerHandler.run#u108`, and `LearnerHandler.run#u129` ->
`Learner.registerWithLeader#u26`; these unit indices are specific to the
compiled build. The original region count was 1,317, compared with 1,316
without a mapping. `ZooKeeperWireFlowMapTest` separately executes the
original `WireFlowCatalog` parser on compiled matching methods and checks
the two typed, distinct ports:

```bash
mvn -q -f Mallory/static_scope_port/original_engine/pom.xml \
  -Dtest=ZooKeeperWireFlowMapTest test
```

**Runtime limit:** these static edges do not establish a matched cross-process
observation. Original GraphChecker must weave its `CommunicationHandoffSpec`
captures and bind the staged expression to the exact physical packet at both
ends. The current Mallory ZooKeeper transport bridge matches the `LEADERINFO`
send/read path, but the original native expression handoff and the
`FOLLOWERINFO` send/read path have not yet been proven end to end. Existing
frozen campaigns were not changed by adding this catalog.

## HDFS 3.4.3 key exchange

`hdfs-3.4.3.jsonl` has four typed ports that apply to HDFS's encryption-key
protocol regardless of the particular target check: `block-key-id`,
`block-key-expiry-date`, `data-encryption-key-id`, and
`namenode-data-encryption-key-id`. The first two map
`PBHelper.convert(BlockKey)`'s protobuf builder setters to the reverse
`PBHelper.convert(BlockKeyProto)` getters, with `ExportedBlockKeys` conversion
as the frame. The NameNode data-encryption-key port maps
`PBHelperClient.convert(DataEncryptionKey)`'s `setKeyId` to the reverse
protobuf getter. The SASL port maps the client's key ID, encoded as the first
component of the SASL username by
`SaslDataTransferClient.getUserNameFromEncryptionKey`, to
`BlockTokenSecretManager.retrieveDataEncryptionKey(int,byte[])` parameter 0.
`SaslDataTransferServer.getEncryptionKeyFromUserName` parses that component
and forwards it through `BlockPoolTokenSecretManager` to the block-pool key
lookup. This is the `allKeys.get(keyId)` lineage in the unmodified 3.4.3
source, not a selected fault door.

The HDFS file begins with GraphChecker revision
`c4a90033c654737206466ed36ce837c5b3c12457`'s system-wide Hadoop
catalog. One capture was corrected for the unchanged HDFS 3.4.3 build: the
original file used `Integer.toString(int)`, but this build's
`getUserNameFromEncryptionKey` directly concatenates `encryptionKey.keyId`
(`SaslDataTransferClient.java:345-352`), whose Java 8 bytecode/Jimple uses
the first `StringBuilder.append(int)`. The original parser refused the old
capture; it resolves the corrected capture at `#u4`. With the correction,
the standalone original `WireFlowCatalog` probe resolved **4 of 4** ports
against compiled HDFS 3.4.3 classes. The probe accepts any system map and a
single text file containing the target system's full classpath:

```bash
java -cp '<original-engine-jar>:<original-engine-dependencies>' \
  edu.uva.liftlab.graphchecker.causynth.MalloryWireMapProbe \
  Mallory/static_scope_port/communication/hdfs-3.4.3.jsonl \
  /path/to/hdfs-3.4.3-classpath.txt
```

The probe calls the **original** `WireFlowCatalog.fromConfiguration` and
fails if any row does not resolve to concrete, type-compatible compiled
captures. This validates declarations only. A full HDFS analysis must also
materialize **both** client and server classes in `analysis.process_dirs`;
placing `hadoop-hdfs-client` only on a dependency classpath allows its
bytecode to resolve but makes the original analyzer skip client-owned flows.
The run must assert its emitted `communicationCallSites` and `wire_handoff`
rows before claiming a cross-process slice. The HDFS catalog has not yet
been shown to produce native runtime expression handoffs for every selected
JUnit, and no old campaign was retroactively reclassified.
