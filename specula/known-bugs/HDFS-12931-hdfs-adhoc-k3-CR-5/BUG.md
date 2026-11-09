# HDFS-12931: detected by Specula (yes), finding CR-5

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `hdfs-adhoc-k3`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

`DFSClient` caches one DataEncryptionKey. When it has gone stale (its block key expired and was removed on the DataNodes, or the NN/DN restarted with new keys) the DataNode's `retrieveDataEncryptionKey` throws and the client receives `InvalidEncryptionKeyException`. The read and write paths catch it, call `clearDataEncryptionKey()` and retry. `FileChecksumHelper.ReplicatedFileChecksumComputer.checksumBlock` (OP_BLOCK_CHECKSUM to each DataNode) does not: it treats it as a generic IOException, tries the next DataNode with the same stale key, and finally `getFileChecksum` fails ("Fail to get block MD5 checksum"; Hive table creation failed in the report). Fix: catch InvalidEncryptionKeyException in checksumBlock, clear the key and retry the block once.

## What counted as detecting it (written before the run)

A finding counts only if it shows: a long-lived DFSClient whose cached DataEncryptionKey has become invalid (block-key expiry / NN-DN key change) calls getFileChecksum first (no prior read/write refreshed the key); every DataNode rejects it at line 490, and FileChecksumHelper never clears/refetches the key, so getFileChecksum fails to the caller. Read/write paths and the balancer are different bugs.

## What Specula found

**Specula's finding CR-5:** getFileChecksum never clears a stale cached DEK on InvalidEncryptionKeyException, so every DN rejects it and the checksum fails

- **Cause:** FileChecksumHelper's per-DN loops (ReplicatedFileChecksumComputer.checksumBlock, StripedFileNonStripedChecksumComputer.checksumBlockGroup) catch InvalidEncryptionKeyException as a generic IOException and try the next DN without calling DFSClient.clearDataEncryptionKey(), so DFSClient.newDataEncryptionKey() keeps returning the same stale cached DEK until it expires.
- **Trigger:** An encrypted-transfer client caches a DEK. The NN restarts (new block keys) and the DNs restart (they register and receive only the new keys). The client then calls getFileChecksum before doing any read or write.
- **Consequence:** On every DN, BlockTokenSecretManager.retrieveDataEncryptionKey throws InvalidEncryptionKeyException (BlockTokenSecretManager.java:490-492), and DistributedFileSystem.getFileChecksum throws IOException 'Fail to get block MD5'. This repeats on every call until the DEK expires (dfs.block.access.token.lifetime, 600 min default) or an unrelated read or write clears the cache.
- **Premises:** dfs.encrypt.data.transfer=true and block access tokens are enabled, and no TrustedChannelResolver exempts the client. An NN restart followed by a DN restart is a normal operational event. It leaves a long-lived client's cached DEK naming a block key absent from every DN. Between the restart and the getFileChecksum call, the client does no read or write that would clear the DEK as a side effect (DFSInputStream.java:584-590, DataStreamer.java:139). Only the replicated path was executed. The striped path (checksumBlockGroup) has the same catch structure but was not run. Upstream: HDFS-12931 (Fix Version 3.1.0) reports and fixes this for the replicated path. HDFS-17897 (apache/hadoop PR #8364, merged 2026-03-25) does so for the striped path. The pinned tree e19e80cc0dd (3.1.0-SNAPSHOT) predates both.

**Operator's judgement:** yes. code-review finding, reproduced by test (no TLC); also k4 CR-2

## Evidence

- TLC: none (code-review finding); the evidence is the reproduction.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 2h08m | 82.8M | $54.64 |

Time is active time; quota sleeps are excluded.
