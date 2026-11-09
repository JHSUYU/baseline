# hdfs-adhoc-11 MC-4 (tier A): FileChecksumHelper retry does not restore `remaining`; getFileChecksum silently returns a wrong checksum

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-11`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hdfs-adhoc-11/MC-4
- **defect (root cause):** `FileChecksumHelper.checksumBlock` subtracts the block from `remaining` before contacting a DataNode (L508-511). The retry paths for `InvalidBlockTokenException`/`InvalidEncryptionKeyException` (L520-546) redo the block (`blockIdx--`) without restoring `remaining`
- **consequence:** `getFileChecksum` with an explicit length, or on a `/.snapshot/` path (`remaining` bounded, L119-123), **silently returns a wrong checksum** (MD5 over zero CRCs), e.g. to DistCp
- **trigger:** any one-time DEK or block-token rejection during the checksum; reproduced with only an NN restart and a DN restart (target `InvalidEncryptionKeyException` at BTSM:559)

**Specula's finding MC-4:** After an NN restart and a DN restart the DN rejects a long-lived client's cached DEK (BTSM:559); the checksum retry returns a wrong bounded-length checksum

- **Cause:** Block keys live only in memory. A restarted NN issues keys from a fresh random serial (BlockTokenSecretManager.java:140-157); a restarted DN builds a new worker that learns only the current NN incarnation's keys (DataNode.java:2115-2144); a DFSClient keeps its DEK until it expires (DFSClient.java:1855-1868). The restarted DN rejects the cached DEK at BlockTokenSecretManager.java:559-561. FileChecksumHelper.checksumBlock retries the block after this rejection (FileChecksumHelper.java:536-546) but has already subtracted the block from `remaining` (508-511), so with a bounded length the retry requests numBytes = remaining (0 for a one-block file).
- **Trigger:** Encrypted data transfer on. A long-lived client caches a DEK, the NN restarts, the DN holding the replica restarts and re-registers, then the client calls getFileChecksum on a /.snapshot/ path or getFileChecksum(path, length).
- **Consequence:** The DN throws InvalidEncryptionKeyException at BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:561). Reads, preads, whole-file getFileChecksum and append recover by refetching the DEK, but the snapshot-path and explicit-length getFileChecksum calls silently return a wrong checksum (MD5 over zero CRCs), e.g. to DistCp's checksumsAreEqual (DistCpUtils.java:583).
- **Premises:** dfs.encrypt.data.transfer=true with block access tokens; the client is not on a trusted channel. NN block keys are not persisted; a restarted NN issues keys from a new random serial (non-HA NN in the repro). A long-lived DFSClient keeps an unexpired DEK across the NN restart (DEK lifetime = block token lifetime, default 600 min). The DN holding the replica restarts after the NN restart and re-registers before the client contacts it; a DN that only re-registered keeps the old keys and does not fire the check. The harm needs a bounded checksum length: a /.snapshot/ path or getFileChecksum(Path, long). Whole-file getFileChecksum(Path) passes Long.MAX_VALUE and is correct; reads, preads and append recover correctly. Reproduced with the default MD5MD5CRC combine mode on a replicated one-block file; COMPOSITE_CRC and the striped checksumBlockGroup retry use the same bookkeeping but were not exercised. Reproduction ran on the pinned tree 734dd8a67cd with the harness instrumentation reverted.

## Evidence

- TLC: `tlc/RERUN.md` (config `G_S4a_backward.cfg`, expect `Invariant TargetSafeBackward is violated`); rerun 2026-11-07: Invariant TargetSafeBackward is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-11` (all phases) | 6h18m | 470.5M | $259.50 |
| of which: confirming this finding | | 17.7M | $10.17 |

Time is active time; quota sleeps are excluded.
