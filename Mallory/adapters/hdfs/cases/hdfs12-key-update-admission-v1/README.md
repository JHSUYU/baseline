# HDFS-12 / HDFS-14 block-token source admission

Status: **HDFS-12 conditional healthy-only candidate; HDFS-14 source gap**. No new HDFS JVM, healthy run, fault trial, or full campaign was started.

## HDFS-12

The selected check is `BlockTokenSecretManager.retrievePassword(BlockTokenIdentifier)` at line 511; line 514 throws `InvalidToken` when `allKeys.get(identifier.getKeyId())` is null. `TestEncryptedTransfer#testLongLivedClient` starts an encrypted MiniDFSCluster, shortens the block-key update interval and token lifetime to two seconds, then reads again after 15 seconds. The server-side SASL handshake calls `BlockPoolTokenSecretManager.retrievePassword`, which delegates to the selected check. This is a source call path, not an observed exact target hit. The archived exact method selector ran **zero JUnit tests** because the class is parameterized.

The diagnostic config selects `TestEncryptedTransfer#testLongLivedClient*` with one no-fault run, a pinned instrumentation agent, and the immutable heartbeat bridge. The wildcard may also match `testLongLivedClientPipelineRecovery`; the Surefire XML method names and selected target occurrence must be checked before accepting a seed. The two parameter sets include a trusted-channel resolver, so the target must be shown on a concrete DataNode and epoch in a run that actually traverses token validation. Admission requires passing JUnit results, exact nonthrowing target reach, and a strict root-free observed graph path. Automatic promotion is disabled.

The candidate door is the typed `DatanodeProtocolClientSideTranslatorPB.sendHeartbeat` call in `BPServiceActor.sendHeartBeat` at line 563. `BPServiceActor.offerService` catches `IOException`, sleeps up to one second, and retries. NameNode heartbeat processing can add `DNA_ACCESSKEYUPDATE`, and `BlockManager.addKeyUpdateCommand` clears `needKeyUpdate` when it places the command in a response. `BPOfferService` applies that command to the DataNode's block-token key map. A before-call injected exception does **not** cause the NameNode to clear the flag or permanently lose that update. It can delay the next attempt; during the test's short key-rotation window this could change whether a newly issued token's key is present at the selected lookup. The needed overlap, same DataNode binding, and exact event-time path are unverified. This is a diagnostic healthy candidate, not fault/full admission.

## HDFS-14

The selected check compares `retrievePassword(id)` with `token.getPassword()` in the six-argument `checkAccess` overload at line 411. Its original parameterized selector also ran zero JUnit tests. An encrypted balancer MiniDFSCluster is a source-level alternate, but exact branch reach remains unobserved. A token-identifier deserialization `IOException` throws before the comparison. A missing key throws from `retrievePassword` at HDFS-12 before HDFS-14 compares passwords. The reviewed I/O paths do not produce two available, unequal password byte arrays while retaining this check. No HDFS-14 runtime config is staged.

Run `python3 -B check_offline.py` to verify pinned sources, compiled call sites, release artifacts, configs, and archived zero-test evidence without starting a JVM.
