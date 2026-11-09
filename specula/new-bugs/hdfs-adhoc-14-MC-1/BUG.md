# hdfs-adhoc-14 MC-1 (tier B): derived-QOP re-signs the forwarded token with the DN's key and keeps the keyId

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-14`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hdfs-adhoc-14/MC-1
- **defect:** with `dfs.encrypt.data.overwrite.downstream.derived.qop=true`, `DataXceiver.writeBlock` (L823-832) re-signs the forwarded token with the DN's own key and keeps the keyId (`SaslDataTransferClient.updateToken` L450-460)
- **why tier B:** non-default flag; rejections in 1-3 s windows after each key rotation or failover

**Specula's finding MC-1:** Mirror DataNode re-signs a forwarded write token with its own currentKey but keeps the token keyId; next DN fails BTSM.checkAccess:418 after key rotation

- **Cause:** With dfs.encrypt.data.overwrite.downstream.derived.qop=true, DataXceiver.writeBlock (DataXceiver.java:824-832) passes the mirroring DataNode's own currentKey to SaslDataTransferClient.updateToken (SaslDataTransferClient.java:450-460). updateToken recomputes the block-token password with that key but keeps the identifier's NameNode-assigned keyId. The next DataNode recomputes HMAC(allKeys[keyId]) in BlockTokenSecretManager.checkAccess and rejects the token whenever the mirror's currentKey differs from the key that keyId names. That happens after every NameNode block-key rotation (HeartbeatManager.java:552-557), until the mirror processes its KeyUpdateCommand from a later heartbeat (BlockManager.java:1671-1677, BPOfferService.java:787-793).
- **Trigger:** Block tokens on, dfs.encrypt.data.transfer=true with the algorithm unset (negotiable), dfs.encrypt.data.overwrite.downstream.derived.qop=true, replication >= 2. The NameNode's HeartbeatManager.Monitor rotates the block key, and a client allocates a block (token signed with the new key) before the pipeline's head DataNode has applied the KeyUpdateCommand. That window is about one heartbeat interval; 1.2-1.5 s was measured in a MiniDFSCluster.
- **Consequence:** The downstream DataNode throws SecretManager.InvalidToken at BlockTokenSecretManager.java:418 (via DataXceiver.checkAccess:1454 from writeBlock:731) and rejects an authorized WRITE_BLOCK with ERROR_ACCESS_TOKEN. The client gets InvalidBlockTokenException, abandons the block and excludes a healthy DataNode. Writes then complete on shorter pipelines (fewer replicas), or fail with 'java.io.IOException: Unable to create new block.' when all dfs.client.block.write.retries attempts fall inside the window. Measured in two independent runs each: with 3 DNs, 80 and 108 firings and 40 and 54 one-replica writes; with 6 DNs, 2018 and 1977 firings and 502 and 492 failed application writes; with the flag off, 0.
- **Premises:** Block access tokens and dfs.encrypt.data.transfer are enabled, the data-transfer encryption algorithm is unset (negotiable), dfs.encrypt.data.overwrite.downstream.derived.qop=true, and write pipelines have at least 2 DataNodes. The NameNode signs new block tokens with its new currentKey as soon as it rotates. A DataNode's currentKey changes only when it processes the KeyUpdateCommand delivered in a later heartbeat response. SaslDataTransferClient.updateToken changes the handshake message and password but not the identifier keyId, and the mutated token is the one forwarded downstream in Sender.writeBlock. With an explicitly empty encryption algorithm, every DN-to-DN encrypted handshake fails for an unrelated reason (DNConf/DataNode DEK algorithm), so the defect is only observable with the algorithm unset or set to a valid cipher. The client's setupPipelineForCreate retry masks the failure only when a later attempt lands on a single-node pipeline or a head DataNode that has already applied the key update.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_s1_rotation_skew_w1_steady.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-14` (all phases) | 4h11m | 314.4M | $152.01 |
| of which: confirming this finding | | 4.9M | $23.42 |

Time is active time; quota sleeps are excluded.
