# hdfs-adhoc-11 MC-1 (tier B): heartbeat returns early in safe mode before the key update; encrypted reads fail after ~10 h

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-11`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hdfs-adhoc-11/MC-1
- **defect:** `DatanodeManager.handleHeartbeat` returns early in safe mode (L1884-1886), before the key update (L1971), while keys keep rolling and DEKs are issued
- **why tier B:** encrypted reads fail only after about 10 h in one safe-mode period at the default key interval

**Specula's finding MC-1:** Safe mode suppresses block-key pushes while keys keep rolling, so fresh DEKs fail at DataNodes with InvalidEncryptionKeyException

- **Cause:** DatanodeManager.handleHeartbeat returns an empty command array while the NameNode is in safe mode (DatanodeManager.java:1884-1886), before the KeyUpdateCommand is added (DatanodeManager.java:1971). HeartbeatManager.Monitor keeps rolling block keys (HeartbeatManager.java:552), and getDataEncryptionKey issues DEKs under the newest current key with no safe-mode check (NameNodeRpcServer.java:1940-1942). After two rolls inside one safe-mode period, the NameNode's current key is one that no DataNode received.
- **Trigger:** A synced DataNode; the active NameNode enters manual (dfsadmin -safemode enter) or resource-low safe mode; two block-key roll events occur before safe mode ends; a client without a cached DEK fetches a DEK and reads.
- **Consequence:** The DataNode's SASL handshake throws InvalidEncryptionKeyException at BlockTokenSecretManager.retrieveDataEncryptionKey (throw statement at BlockTokenSecretManager.java:559-561). The client's single DEK refetch returns the same unknown key, so the read fails with BlockMissingException on healthy data. Reads with fresh DEKs keep failing at every DataNode until safe mode ends and a heartbeat delivers the key push.
- **Premises:** dfs.encrypt.data.transfer=true and dfs.block.access.token.enable=true; the client is not on a trusted channel. The active NameNode stays in manual or resource-low safe mode across two block-key roll events (default interval 600 minutes; reproduced with the public config dfs.block.access.key.update.interval=1 and with setKeyUpdateIntervalForTesting). DataNodes receive block keys only at registration and through DNA_ACCESSKEYUPDATE; no other path installs keys during safe mode. The reading client has no cached DEK issued before the second roll (new client, or cached DEK expired). Pinned source 734dd8a67cd; upstream trunk on 2026-10-29 still returns before addKeyUpdateCommand in safe mode.

## Evidence

- TLC: `tlc/RERUN.md` (config `G_S1_synced.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-11` (all phases) | 6h18m | 470.5M | $259.50 |
| of which: confirming this finding | | 19.7M | $9.55 |

Time is active time; quota sleeps are excluded.
