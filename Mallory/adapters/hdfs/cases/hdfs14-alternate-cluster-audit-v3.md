# HDFS-14 alternate MiniDFSCluster workload and fault admission

Source inspected: Hadoop 3.4.3 commit `9d50c6884666e794e45102260a4017bb31802e1b`,
full source digest `825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7`.
This audit did not run a JVM or inject a fault. It supplements the
`hdfs14-31-32-alternate-junit-audit-v2.md` and
`hdfs14-31-32-target-retention-limit-v1.md` reviews with two additional
MiniDFSCluster test classes.

## Exact selected check and available fault

The selected site is the **six-argument**
`BlockTokenSecretManager.checkAccess(Token, String, ExtendedBlock, AccessMode,
StorageType[], String[])` password comparison at `BlockTokenSecretManager.java:411`,
with the `InvalidToken` throw at `:412`. Deserialization failures return from
the `IOException` catch at `:405-408`, and identifier checks run before the
comparison at `:410`. `retrievePassword` throws for an expired identifier or
absent `allKeys[keyId]` at `:503-515`. To make this selected branch throw,
an experiment must leave the identifier valid and its key present, yet make
the DataNode-computed password differ from `token.getPassword()`.

The staged typed physical I/O door is `BPServiceActor.sendHeartBeat:563`
(`java.io.IOException`). `BPServiceActor.offerService:786-788` catches the
transport failure and retries. A missed heartbeat can delay an
`DNA_ACCESSKEYUPDATE` command (`BPOfferService.java:779-785`), but
`BlockTokenSecretManager.addKeys:224-237` installs keys by key ID and
`updateKeys:254-274` preserves the old key bytes under the old ID. From this
source path, the result is an existing key, a missing key, or expiration.
The latter two throw before the selected comparison; the reviewed exception
does not supply a different secret under the same key ID. The adapter's
`hdfs:sasl-first-response-read` client I/O exception is likewise before
`DataXceiver.readBlock` invokes `checkAccess` (`DataXceiver.java:592,1452-1457`):
it may cause a client retry, but it does not change either compared byte array.

## Additional existing cluster JUnits reviewed

| JUnit | Relevant source steps | Admission result |
| --- | --- | --- |
| `TestBlockTokenWithDFS#testRead` | `TestBlockTokenWithDFS.java:351-360` starts a two-DataNode MiniDFSCluster; `:388-414` performs ordinary reads and a valid direct `BlockReader` read. It then tries an expired token at `:420-434`, a fresh valid token at `:435-438`, wrong block ID at `:439-446`, and wrong access mode at `:447-450`. Later cached-token, NameNode, and DataNode restart reads at `:455-630` exercise recovery. | The successful reads are plausible healthy reach. The deliberately invalid phases fail the earlier identifier checks (`BlockTokenSecretManager.java:347-363`) rather than create two available unequal password byte arrays. Their failures are expected by `tryRead(..., false)` (`TestBlockTokenWithDFS.java:156-215`). No different typed pretarget I/O door with a source-backed path to the selected comparison was found in this test. It is longer and more phase-dependent than the staged encrypted-read seed. |
| `TestSaslDataTransferExpiredBlockToken#testBlockSeekToWithExpiredToken`, `#testFetchBlockByteRangeWithExpiredToken`, and `#testHedgedFetchBlockByteRangeWithExpiredToken` | `TestSaslDataTransferExpiredBlockToken.java:58-73` starts a three-DataNode MiniDFSCluster with secure transfer and a one-second token lifetime; `:146-175` waits until cached tokens expire before reading with retry. | The stale token is rejected by the earlier expiration check (`BlockTokenSecretManager.java:358-360`), or secure transfer can reject it before the DataNode read check. Retrying can reach a valid token, but the intended recovery does not produce a same-ID password mismatch. A client transport exception can also prevent the selected DataNode check on that attempt. |
| `TestFailoverWithBlockTokensEnabled#ensureInvalidBlockTokensAreRejected` | `TestFailoverWithBlockTokensEnabled.java:64-73` starts an HA MiniDFSCluster. At `:130-146`, a Mockito answer modifies a token identifier expiry while retaining the original password, and the test expects the subsequent read to fail at `:152-156`. | This test can intentionally create the exact password mismatch if the modified expiry remains valid until the check. It is an explicit test mutation, not a Mallory typed I/O fault; the resulting exception is an expected rejection, not a fault-discovered product bug. |

`TestBlockToken` calls the six-argument overload directly
(`TestBlockToken.java:224-267`), but constructs token managers in-process
instead of a MiniDFSCluster (`:269-294`), so it is not a replacement cluster
workload. The original parameterized `TestEncryptedTransfer` encrypted read
remains the least confounded healthy candidate: it enables block tokens
(`TestEncryptedTransfer.java:80-85`), starts a MiniDFSCluster (`:121-142`),
and reads a file (`:147-157,210-212`).

## Package and current classification

The existing isolated node2 package
`hdfs14-node2-healthy-stage-v1/HDFS-14-node2-healthy-v1.json` is pinned to
SHA-256 `f521a5e3fefa44be6920c2864b5d5e89c65513fd00cd9e8adcfd43dc3d008c30`.
Its wildcard Surefire selector runs the two parameter instances; the older
exact selector ran zero tests (`data/mallory/calibration/HDFS-14/trials/r0000/result.json`).
`preflight.py --static` passed on node0 and node2 against the pinned source,
compiled classes, agent, adapter, site catalog, and frozen core. The node2
preflight reported source root `hdfs-identity-v8`, source digest above,
`jvm_started=false`, and `healthy_admitted=false`.

**Classification:** existing cluster JUnit and runnable healthy-only package;
not a no-cluster-test skip and not a completed fuzz campaign. Admit a fault
campaign only after healthy runtime evidence shows the exact guard, named
DataNode and epoch, and a typed pretarget door with a source-backed path to
the same target occurrence. The reviewed alternatives do not establish that
path. A source-only lack of a current door is not evidence that the product
has no bug.

Source SHA-256 pins: `BlockTokenSecretManager.java`
`d6f2dd33b2cb82484ab52262a05bf4445113e168de08479af00ad93969911957`,
`TestBlockTokenWithDFS.java`
`6f1bcf553da3930d339885c2228f4f66c157dd75671ee7fcfe6a722f5815fd0a`,
`TestSaslDataTransferExpiredBlockToken.java`
`843c02826106a78226d7986af95f9060ea45d03c3a797d10f02cfe750d2b7d52`, and `TestFailoverWithBlockTokensEnabled.java`
`425c6d71d05f696c48ecd898cd8ac7ead76fd1a77cfa739e491fb09373b4b85e`.
