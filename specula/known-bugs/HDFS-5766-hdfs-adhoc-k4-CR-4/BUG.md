# HDFS-5766: detected by Specula (partial), finding CR-4

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `hdfs-adhoc-k4`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

Found by code reading. In `DFSInputStream.fetchBlockByteRange` (positional read), when the block reader fails with InvalidEncryptionKeyException (the DataNode's `retrieveDataEncryptionKey` rejected the client's stale DataEncryptionKey), the client decrements refetchEncryptionKey and clears the key but then falls through to `addToDeadNodes(chosenNode)` instead of `continue`. A healthy DataNode is thus marked dead for this stream because of a client-side stale key; the retry goes to another replica, or (if none) into chooseDataNode's back-off / refetch of locations, and can end in "Could not obtain block" (BlockMissingException) when replicas run out. The stateful-read path (blockSeekTo) already did `continue`. Fix: add `continue;`.

## What counted as detecting it (written before the run)

A finding counts only if it shows: a positional read (`read(long, byte[], int, int)` -> fetchBlockByteRange) with a stale client DataEncryptionKey hits line 424 on the DataNode, and the client then adds that (healthy) DataNode to deadNodes, leading to retrying elsewhere / failing the read although the DN is fine. A finding about stateful reads, writes or the balancer is a different bug.

## What Specula found

**Specula's finding CR-4:** DFSInputStream pread adds DN to deadNodes after InvalidEncryptionKeyException despite clearing the DEK (no continue)

- **Cause:** fetchBlockByteRange's InvalidEncryptionKeyException branch clears the DEK but has no continue, so control falls through to addToDeadNodes(chosenNode); blockSeekTo's equivalent branch retries the same DN.
- **Trigger:** Client caches a DEK, NN and DN restart (DN only knows new keys), client performs a positional read; DN throws InvalidEncryptionKeyException at BlockTokenSecretManager.retrieveDataEncryptionKey.
- **Consequence:** Default config: the only/first replica is marked dead, chooseDataNode all-dead recovery sleeps 0-3 s, refetches locations and retries (read succeeds); with dfs.client.max.block.acquire.failures=0 the pread throws BlockMissingException while a stateful read succeeds; with multiple replicas a healthy DN stays excluded for the stream lifetime.
- **Premises:** Masked by DFSInputStream.chooseDataNode all-dead recovery (deadNodes.clear + openInfo + retry) while failures < dfs.client.max.block.acquire.failures (default 3). Stale DEK reached via real NN+DN restart sequence (as in TestEncryptedTransfer#testLongLivedReadClientAfterRestart). Known upstream as HDFS-5766 (fixed in 2.3.0); pinned base predates the fix.

**Operator's judgement:** partial. exact defect (pread no continue -> healthy DN in deadNodes) but verdict MASKED: default config recovers via chooseDataNode back-off

## Evidence

- TLC: none (code-review finding); the evidence is the reproduction.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 2h19m | 101.3M | $70.29 |

Time is active time; quota sleeps are excluded.
