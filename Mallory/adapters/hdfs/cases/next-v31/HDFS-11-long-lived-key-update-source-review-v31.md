# HDFS-11 long-lived key-update candidate (source and bytecode review)

Status: healthy calibration pending. No JUnit or fault trial has been run with this v31 adapter. This is a separate candidate from the live v27 campaign and the v29 Balancer candidate.

## Exact target and key states

- The original HDFS-11 oracle is `BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])`: its `allKeys.get(keyId)` check at line 552 throws `InvalidEncryptionKeyException` at line 555 if the DN has no block key for the presented DEK key ID.
- The NN's `generateDataEncryptionKey` copies the current block-key ID into a successful `DataEncryptionKey`. The client caches that DEK only after `namenode.getDataEncryptionKey()` returns in `DFSClient.newDataEncryptionKey` (lines 1855-1865). An `IOException` at the NN method entry prevents that issuance and cache assignment on that call. The v27 NN fault/retry pilot therefore demonstrates a retry path, not a key-ID mismatch.
- `TestEncryptedTransfer#testLongLivedClient` is an existing Parameterized MiniDFSCluster test. Its compiled test class sets the NN block-key update interval and token lifetime to 2,000 ms, calls `clearAllKeysForTesting`, reads and checksums the file, sleeps 15,000 ms, then reads and checksums it again. The `#testLongLivedClient*` Surefire selector is staged for a fresh healthy-only calibration. Source and bytecode show a plausible encrypted DN handshake, but cannot prove that this exact target executes or remains nonthrowing; the runtime catalog and trace must establish that.

## Exact DN update path and bounded fault

- NN `BlockTokenSecretManager.updateKeys` rotates current/next keys and prunes expired keys (lines 254-274). `HeartbeatManager` marks DNs for an update after a rotation (lines 551-559). `BlockManager.addKeyUpdateCommand` exports keys into `DNA_ACCESSKEYUPDATE` and clears `needKeyUpdate` when it **sends** the command (lines 1660-1666).
- The DN's `BPServiceActor` receives the heartbeat and queues the command. `BPOfferService.processCommandFromActive` and `processCommandFromStandby` handle `DNA_ACCESSKEYUPDATE` by calling `BlockPoolTokenSecretManager.addKeys`; that call updates DN `currentKey` and `allKeys`. `BPServiceActor.processCommand` catches `IOException` for each command and continues, so a fault immediately before `addKeys` can skip one update without directly stopping the DN command loop.
- v31 adds `Probe.beforeDoor(site, "java.io.IOException")` at the exact `addKeys` call in both active and standby command handlers, inside an existing named DN receiver scope. Its two manual sites are `hdfs:dn-apply-access-key-update-active` and `hdfs:dn-apply-access-key-update-standby`. Offline transformation of the actual compiled `BPOfferService.class` found exactly one hook immediately before each handler's `addKeys` call; the initial registration `addKeys` remains untouched. ASM `CheckClassAdapter` passed on the transformed class using the pinned Hadoop distribution classpath. The transformed class has **not** been run in a JUnit JVM.
- One skipped update may not create a missing-key state because the previous export already contains the next key. A DN miss requires the client to hold a successfully issued DEK with key ID *k* while that DN's `allKeys` lacks *k*. Future evidence must record both values at the time of the target check, the matched `DNA_ACCESSKEYUPDATE` fault, and the causal request path. A target throw resulting from deliberately skipped updates alone is not a new-bug claim; recovery behavior and replay still require source review.

## Balancer alternative

`KeyManager.newDataEncryptionKey` caches a locally generated DEK, and its updater retries NN `getBlockKeys` after `IOException`. This is closer to a stale cached-key mechanism, but `TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` does not shorten key rotation in source and has a 60-second JUnit timeout. The existing v29 Balancer hook is only a healthy-path candidate until exact target reach and a realistic rotation window are shown. `TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey` deliberately waits for a missing DN key and expects recovery, so its selected exception would be an expected healthy observation; it is unsuitable as a no-throw seed.

## Admission gates

Run the v31 config only after the live v27 HDFS-11 full campaign releases lane1 and dispatch admits one healthy-only JVM. Require Surefire tests >0 and 0 failures/errors, exact target class and site catalog SHA, named DN `TARGET_CHECK`, zero selected healthy `TARGET_THROW`, a time-respecting root-free path with observed pretarget doors, and a real `DNA_ACCESSKEYUPDATE` door if this fault strategy is to be used. Do not promote to a fault campaign from source/bytecode evidence alone.
