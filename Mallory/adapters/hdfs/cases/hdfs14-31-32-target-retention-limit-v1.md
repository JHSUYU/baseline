# HDFS-14/31/32 target-retaining I/O door limit

Continuation of `hdfs14-31-32-node2-healthy-audit-v1.md`. This review asks
whether a typed physical I/O exception before the selected check can alter
that check's predicate while the existing JUnit still reaches the same
physical target. It covers the currently staged Hadoop 3.4.3 source and
Mallory exception injector. It does not exclude a different test, a new
fault primitive, or a source change. No JVM or fault run was started.

The source trees on node0 (`hdfs-lane2`) and node2 (`hdfs-identity-v8`) have
the pinned digest
`825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7`
for commit `9d50c6884666e794e45102260a4017bb31802e1b`. Relevant file
SHA-256 pins, checked on node0's equivalent tree:

| File relative to Hadoop root | SHA-256 |
| --- | --- |
| `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java` | `60db822a82908b520df08ebb6d2e7b8a37ddd7337b9a06ef0eb97dcd496b8de4` |
| `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolManager.java` | `1d3bae5753526ca1bfc9dec3a5e63820564db49c9dedd32b4b7fd5f1f8ad423a` |
| `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BPOfferService.java` | `21c5c65c5c023cc004aee8ca4814037de86de811db0e7960cb17c2909ccb8294` |
| `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java` | `fbcb03b86822e71e451242142752706b61c3f3f096d0219f5d90344bc59bb833` |
| `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java` | `d6f2dd33b2cb82484ab52262a05bf4445113e168de08479af00ad93969911957` |
| `hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/org/apache/hadoop/hdfs/DFSInputStream.java` | `e61685e14fcda7c598fc76299cbdbd1677e2ef5c52c75a20d8cc4fa0f914d151` |
| `hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/ipc/RemoteException.java` | `02722c5b18093192baebeb7be11956d7566befbc52855710ee6911bd008c1418` |
| `hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/io/IOUtils.java` | `c504d7e96e44861784df631939e8fce88553a8f9b36e307b538b30bef9151842` |
| `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDiskError.java` | `122183dc0da270317d8bbf2744b6dbdbfe578e720566eee37d23fbe6fd79f3ed` |
| `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDeleteBlockPool.java` | `31467bca1249b93cae7ed984bac01d405cde8ec1409a9ef78fa0a0c469a3bb3a` |
| `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestEncryptedTransfer.java` | `8272862b11d4a645ffa6029c3f1462a14dcfce7b873815fcccc949d74a4bc0a5` |

Mallory `Probe.java` is SHA-256
`8f6ac5f38f10ba05cf20e3455adfe9d06bcc008ebce3d8436a92c9ff471b10f0`.
`Probe.exceptionFor` at 500-516 constructs only an exception with a single
`String` argument or a no-argument constructor; it cannot directly construct
Hadoop's `RemoteException(String className, String msg)`.

## HDFS-31: closest structural path, outside the current I/O model

`TestDiskError.java:241-283` writes and corrupts block metadata, starts a
second DataNode, then directly calls `dn0.transferBlock` with an existing
`ExtendedBlock`. `DataNode.transferBlock` calls `getBPOSForBlock` first at
2834. The selected branch at 1833 is true only if
`BlockPoolManager.bpByBlockPoolId` lacks the block's pool ID. The metadata
`RandomAccessFile.writeByte` and `writeInt` doors at 259-260 are uncaught
`IOException` operations before the transfer call, so a fault there loses
the target. A plain heartbeat RPC `IOException` at
`BPServiceActor.sendHeartBeat:563` is caught at `offerService:786-788`,
slept, and retried; it does not call `BlockPoolManager.remove`.

There is a structurally target-retaining **server rejection** path:
`offerService:772-780` treats a `RemoteException` whose embedded class name
is `UnregisteredNodeException`, `DisallowedDatanodeException`, or
`IncorrectVersionException` as fatal. `BPServiceActor.run:910-927` then
enters `cleanUp:640-646`; `BPOfferService.shutdownActor:467-479` calls
`DataNode.shutdownBlockPool:2147-2168` for the last actor, and that calls
`BlockPoolManager.remove:89-95`. If this completes on the same physical
`dn0` after the file exists but before its direct transfer call, the selected
null guard remains reachable. This is a conditional source path, not a
verified trial. It requires a specific NameNode rejection response; a
transport `IOException` does not take it. The staged catalog requests
`java.io.IOException`, and the frozen Mallory injector cannot instantiate
the needed two-argument `RemoteException` or set its embedded class name.
Therefore the path does **not** admit a physical I/O exception pilot under
the current package.

## HDFS-32: removal precedes the two delete requests

`TestDeleteBlockPool.java:142-187` calls `dn1.refreshNamenodes`, asserts one
remaining BPOfferService, then sends `DFSAdmin.deleteBlockPool` first with
`force=false` and then with `force=true`. `BlockPoolManager.doRefreshNamenodes`
at 194-251 stops and joins the removed nameservice before refresh returns.
`BPServiceActor.run:920-927` always enters `cleanUp:640-646`, which calls
`BPOfferService.shutdownActor`; `DataNode.shutdownBlockPool:2147-2168`
removes the map entry **before** dataset and storage cleanup. A physical
I/O exception while closing the RPC proxy or lifeline sender is swallowed
by `IOUtils.cleanupWithLogger:255-269`, before `shutdownActor`. An exception
during the later dataset or storage cleanup likewise cannot retain the
`blockPoolId` map entry. A refresh exception before the call returns aborts
the uncaught test statement, so no later delete check is reached. A plain
heartbeat RPC `IOException` retries, without retaining the stopped service.

The client `DFSAdmin.java:2702` RPC door does not update the DataNode map.
`DFSAdmin.run:2614-2641` converts its exception to a nonzero return: a fault
on the first request can satisfy the test's expected failure **without a
server guard occurrence**, while a fault on the forced second request
breaks its expected success. The first request's ordinary failure comes
after the selected running-pool guard from nonempty block-pool storage.
Neither request is a target-retaining way to make the selected guard true.

## HDFS-14: retry can restore reach, but no mismatch mechanism

`TestEncryptedTransfer.java:80-85,98-100,210-212` enables block tokens in two
parameter instances. On a DataNode read, the selected six-argument
`BlockTokenSecretManager.checkAccess` deserializes the identifier and runs
the earlier identifier checks at 399-410. The selected comparison at 411
requires `retrievePassword(id)` and `token.getPassword()` to return two
available, unequal byte arrays. `retrievePassword:501-516` throws early
for an expired token or a missing key; neither reaches that comparison.
`addKeys:224-237` installs exported keys, while `updateKeys:254-274`
retains retiring keys under their existing IDs and assigns a new ID to the
next key. A heartbeat `IOException` may delay an update, but the reviewed
code yields either a previously shared key or an absent key, not a different
secret under the same ID.

The adapter's client `hdfs:sasl-first-response-read` door is after the
first SASL request, but before the later DataXceiver block-token check.
`DFSInputStream.blockSeekTo:648-674` catches an `IOException` and can retry
with a refreshed encryption key, token, or another DataNode. A later retry
may reach the selected guard, yet the read fault supplies no mutation of
either password byte array. It may also end the first server request before
`DataXceiver.readBlock` reaches the six-argument check. This is a recovery
route to healthy reach, not a source-backed way to trigger the selected
password mismatch.

## Decision and next admission evidence

No reviewed typed physical I/O fault door both changes the exact predicate
and retains the same target occurrence in these three unchanged tests.
Keep the staged packages healthy-only. HDFS-31 is the strongest target
retention *structure* if the study later admits a semantically modeled
fatal NameNode response, but that would be a different fault type and
requires its own adapter, provenance, and healthy actor binding.

For any proposed future door, require a source-backed state transition to
the predicate, proof the exception is caught or retried before the same
test's selected call, and runtime identity for the DataNode, block pool,
epoch, and target occurrence. HDFS-32 also needs the delete request's
`force` flag; HDFS-14 needs the six-argument overload and concrete read
operation. A successful JUnit or a contemporaneous heartbeat is not that
evidence.
