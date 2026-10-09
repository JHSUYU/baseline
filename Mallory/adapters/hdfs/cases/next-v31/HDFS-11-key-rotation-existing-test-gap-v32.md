# HDFS-11: existing MiniCluster key-rotation workload gap

Source review scope: Hadoop 3.4.3 test sources at commit `9d50c6884666e794e45102260a4017bb31802e1b`. The original target remains `BlockTokenSecretManager.retrieveDataEncryptionKey(int,byte[])` `allKeys.get(keyId)` at line 552 and `InvalidEncryptionKeyException` at line 555. The oracle requires zero selected target throws in a fault-free healthy seed.

The v31 healthy-only run used the existing `TestEncryptedTransfer#testLongLivedClient*` with 2-second NN key update interval, 2-second token lifetime, and a 15-second wait. It passed four JUnit parameter instances but was correctly rejected as `healthy_target_exception`: exact `TARGET_CHECK` event 277 and exact `TARGET_THROW` event 278 share the named `hdfs-cluster-1/dn0` occurrence, without any injection. Fourteen named active-DN `DNA_ACCESSKEYUPDATE` doors were observed. The raw calibration and frozen audit are SHA archived in `data/mallory/calibration_v31_node2/HDFS-11`; archive manifest SHA-256 is `e241983c287d414309addfd6ac78621e5d01f6274b55ef8857df57d94b0f0cac`.

The HDFS test-source search for `setKeyUpdateIntervalForTesting`, `setTokenLifetime`, and `clearAllKeysForTesting` found these nearby possibilities:

| Existing JUnit | Encryption and update path | Suitability under zero-throw oracle |
| --- | --- | --- |
| `TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite*` | Encrypted MiniDFSCluster and named DN target are proven by v27 healthy calibration; default key interval gives no demonstrated pretarget `DNA_ACCESSKEYUPDATE` door. | Valid HDFS-11 path seed, but does not yet cover the rotation mismatch mechanism. |
| `TestEncryptedTransfer#testLongLivedClient*` | 2-second rotation, 15-second wait, named target and 14 update doors observed in v31. | Invalid: selected exact target throw already occurs in the fault-free run. |
| `TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey` and `#testLongLivedClientPipelineRecovery` | Both deliberately wait until each DN lacks the cached DEK key ID, then verify invalid-key recovery. | Expected selected throw makes them unsuitable as no-throw seeds. |
| `TestFailoverWithBlockTokensEnabled#TestFailoverAfterAccessKeyUpdate` | Sets 2-second key interval and waits 10 seconds for heartbeat command, but enables block access tokens only. | Does not enable encrypted data transfer, so `retrieveDataEncryptionKey` is not source-supported on its normal path. |
| `TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` | Enables encryption and MiniDFSCluster; v29 handoff is staged. | No shortened rotation or wait in this JUnit; exact target and update-door runtime proof pending. |
| `TestKeyManager#testNewDataEncryptionKey` | Simulates expiry with a fake timer. | No MiniDFSCluster or DN target. |

Conclusion: no existing MiniCluster JUnit has yet demonstrated all of (1) 2-second key rotation, (2) a named DN `DNA_ACCESSKEYUPDATE` before target, (3) exact target reach, and (4) zero selected throws in the healthy run. Keep HDFS-11 v31 as negative calibration. Do not suppress or redefine the expected exception. The existing v27 seed remains the validated nonthrowing path for its own campaign; the stale-key mechanism needs a separate suitable existing test or a clearly labeled workload revision before fuzzing.
