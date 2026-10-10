# HDFS-14/31/32 alternate cluster JUnit audit

This is a source-only reassessment of three pending original-102 checks. The
Hadoop 3.4.3 tree is commit `9d50c6884666e794e45102260a4017bb31802e1b`,
source digest `825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7`.
No JVM or fault trial ran for this audit. These are **not** no-cluster-test
skips: existing MiniDFSCluster JUnits and staged healthy-only packages remain
available.

| Case | Selected production check | Alternate unmodified cluster JUnit reviewed | Finding |
| --- | --- | --- | --- |
| HDFS-14 | `BlockTokenSecretManager.checkAccess(Token, String, ExtendedBlock, AccessMode, StorageType[], String[])`, password comparison at `BlockTokenSecretManager.java:411`, selected `InvalidToken` at 412 | `TestFailoverWithBlockTokensEnabled#ensureInvalidBlockTokensAreRejected` (`:119-159`) | It creates a 3-NameNode, 1-DataNode MiniDFSCluster and first reads a file successfully. Its Mockito `getLocatedBlocks` answer then **deliberately changes the token identifier expiry while retaining the original password** (`:130-146`) and expects the read to fail (`:150-159`). A selected password mismatch is possible if the modified expiry remains valid until the guard; an earlier expiry check may also reject the token. Either failure is expected and cannot be reported as a fault-discovered bug. Its token edit is not a Mallory I/O exception door. `TestEncryptedTransfer#testEncryptedReadAfterNameNodeRestart` (`:160-228`) adds an NN restart and later read but does not change the token password or a same-ID secret. The existing encrypted-read healthy seed remains the cleaner fault-free workload. |
| HDFS-31 | `DataNode.getBPOSForBlock`, absent BPOS branch at `DataNode.java:1833`, selected `IOException` at 1835 | `TestDataNodeTcpNoDelay#testTcpNoDelayEnabled` and `#testTcpNoDelayDisabled` use `transferBlock` helper (`:142-154`); `TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` remains the sole reviewed direct `dn0.transferBlock` caller (`:241-283`) | The TCP tests trigger re-replication with `dfs.setReplication`, so the NameNode may command a DataNode transfer, but the tests have no explicit `ExtendedBlock`/physical sender binding. They also supply no fault that removes the corresponding block-pool mapping while the same transfer proceeds. The original test has an explicit direct call and is the stronger named healthy candidate. The reviewed direct-call metadata writes (`TestDiskError.java:259-260`) are uncaught; an injected write `IOException` aborts before target. A heartbeat `IOException` is retried (`BPServiceActor.java:786-788`) without invoking `BlockPoolManager.remove`. The fatal server `RemoteException` route in the prior target-retention audit would need a semantically classified NN rejection response, beyond the current plain `IOException` injector. |
| HDFS-32 | `DataNode.deleteBlockPool`, running BPOS guard at `DataNode.java:3819`, selected `IOException` at 3822 | `TestDeleteBlockPool#testDeleteBlockPool` (`:44-136`) | The test starts a 2-NameNode, 2-DataNode MiniDFSCluster and **intentionally calls delete while the pool is running**, catching the selected `IOException` at `:70-74` and `:108-112`. That is an expected safeguard, not a new bug. Its later `refreshNamenodes` calls remove the service before subsequent deletes. The staged `testDfsAdminDeleteBlockPool` (`:140-187`) is a better nonthrowing target seed: the two client requests occur after `refreshNamenodes`, and must be distinguished by `force=false/true`. Neither test has a source-supported physical I/O exception that retains the map entry after refresh and still reaches the same delete request. |

The alternates do not improve fault admission. For HDFS-14, a delayed key
update can leave a key missing, but `retrievePassword` throws before the
selected password comparison (`BlockTokenSecretManager.java:501-516`). For
HDFS-31 and HDFS-32, a transport `IOException` on the DataNode heartbeat is
retried and does not mutate `BlockPoolManager.bpByBlockPoolId`. A direct test
I/O failure or client RPC failure can instead lose the selected target.

The three already staged healthy-only packages passed their no-JVM static
preflights in this audit:

| Case | Package | Pinned config SHA-256 | Result |
| --- | --- | --- | --- |
| HDFS-14 | `hdfs14-node2-healthy-stage-v1` | `f521a5e3fefa44be6920c2864b5d5e89c65513fd00cd9e8adcfd43dc3d008c30` | `static_preflight_pass`, JVM not started |
| HDFS-31 | `hdfs31-32-node2-healthy-stage-v1` | `04544f739cda7fe97974bbeccf2df578b42870c3649b5d153aa3305da5a2bd71` | `static_preflight_pass`, JVM not started |
| HDFS-32 | `hdfs31-32-node2-healthy-stage-v1` | `de2e10671adbb42ab24e94f8571625f83ff0722694751804f5bc662e9ecc26cf` | `static_preflight_pass`, JVM not started |

Run those existing packages one at a time only when the node2 HDFS lane is
free. Admit a fault pilot only if the healthy trace proves exact target reach,
named DataNode and epoch, and an observed typed I/O door with a source-backed
state path to the **same** target occurrence. HDFS-32 additionally needs
block-pool ID and delete `force` phase identity. No current source evidence
grants a full campaign for these three cases.

Relevant alternate test file SHA-256 pins: `TestFailoverWithBlockTokensEnabled.java`
`425c6d71d05f696c48ecd898cd8ac7ead76fd1a77cfa739e491fb09373b4b85e`,
`TestDataNodeTcpNoDelay.java`
`454e04887a2a96a5afbd01aab8a486be9cc250366b311c9746b7ca02ef20367e`,
and `TestDeleteBlockPool.java`
`31467bca1249b93cae7ed984bac01d405cde8ec1409a9ef78fa0a0c469a3bb3a`.
