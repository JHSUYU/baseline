# HDFS-11741: detected by Specula (yes), finding MC-1

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `hdfs-adhoc-k1`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

The balancer's `KeyManager` keeps its block keys in sync with the NameNode (the BlockKeyUpdater thread), but `newDataEncryptionKey()` generates the `DataEncryptionKey` once (`if (encryptionKey == null)`) and reuses it forever. The DEK carries the keyId of the block key current at creation time. After that block key expires and is removed from every DataNode's `BlockTokenSecretManager.allKeys` (roughly tokenLifetime + 2-3 keyUpdateInterval later; 20-30 h in the report), every balancer move's SASL handshake presents the stale keyId; the target DataNode's `retrieveDataEncryptionKey` finds no key and throws; the error is relayed to the balancer (DataTransferSaslUtil.readSaslMessageAndNegotiatedCipherOption rethrows it) and each `Dispatcher.PendingMove.dispatch` fails ("Failed to move blk_..."). The balancer has no refresh path, so it cannot move any block any more. Fix: regenerate the DEK when `encryptionKey.expiryDate < now` (plus a Timer for testing).

## What counted as detecting it (written before the run)

A finding counts as this bug only if it shows: a long-lived balancer (KeyManager) keeps using a DataEncryptionKey whose block key has expired and been removed on the DataNodes (KeyManager never regenerates the DEK after creation; block keys keep rolling), so the DataNode's `retrieveDataEncryptionKey` hits `key == null` at line 482 for balancer moves. Only the passage of time / key rolling is needed (no crash). Other routes to line 482 (NN restart, client key staleness in DFSClient paths) are different bugs.

## What Specula found

**Specula's finding MC-1:** Balancer/Mover KeyManager never refreshes its DataEncryptionKey; after DNs drop its block key every move fails at BlockTokenSecretManager:482

- **Cause:** KeyManager.newDataEncryptionKey mints the DEK once from the worker currentKey and caches it for the whole Balancer/Mover run: it never checks expiryDate and nothing clears it on InvalidEncryptionKeyException (Dispatcher.PendingMove.dispatch only logs and delays).
- **Trigger:** Encrypted data transfer + block tokens; a Balancer run that lasts beyond the DN-side expiry of the key current at its first move (about 2I+L, ~3 min at I=L=1 min, ~20-35 h at defaults). The NN retires the key with final expiry R+I+L and every DN removes it at its next addKeys.
- **Consequence:** Every later Balancer/Mover move fails at the target DN with InvalidEncryptionKeyException thrown from BlockTokenSecretManager.retrieveDataEncryptionKey (line 482 statement); the Balancer exits NO_MOVE_PROGRESS with the cluster unbalanced.
- **Premises:** dfs.encrypt.data.transfer=true and dfs.block.access.token.enable=true. A single Balancer/Mover run (one NameNodeConnector/KeyManager) keeps issuing moves past the DN-side removal of the block key its DEK was minted from. No trusted-channel resolver bypasses SASL for the Balancer->DN connection. Known upstream as HDFS-11741 (fixed upstream); the pinned base 595e4680154 lacks the fix.

**Operator's judgement:** yes. balancer KeyManager never refreshes DEK; also found by k4 MC-5, k5 MC-2

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_stale_balancer_dek.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-08: Invariant TargetSafe is violated.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 1h55m | 56.9M | $35.95 |

Time is active time; quota sleeps are excluded.
