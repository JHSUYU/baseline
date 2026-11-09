# CR-4 investigation record

Finding: in DFSInputStream's pread path, after an InvalidEncryptionKeyException (IEK) the DEK is cleared but the DN is still added to deadNodes.
Source: Code Review (no MC counterexample). Tree is pinned at base 8172fc2a10a. DFSInputStream.java there is unmodified by the harness instrumentation: it is byte-identical to the sources jar installed in the case Maven repo.

## Step 1: Code audit

- `DFSInputStream.fetchBlockByteRange` (DFSInputStream.java:916-991). The IEK branch is at :965-971: `refetchEncryptionKey--; dfsClient.clearDataEncryptionKey();`, with no `continue`. The token branch at :972-975 does have a `continue`. The final else and the IEK branch both reach `addToDeadNodes(chosenNode)` at :989.
- Contrast `blockSeekTo` (stateful read), :588-602. There the IEK branch is part of an if/else-if/else chain, and `addToDeadNodes` sits only in the final `else` (:602). So the stateful read retries the same DN with a fresh DEK.
- Call chain: `FSDataInputStream.readFully(long, byte[])` / `read(long,...)` → `DFSInputStream.read(long,byte[],int,int)` (:1220; resets `failures = 0` at :1227) → `fetchBlockByteRange` → `getBlockReader` → DataTransferEncryptor SASL handshake. On the DN side: `DataXceiver.run:168` → `DataTransferEncryptor.getEncryptedStreams:145` → `BlockPoolTokenSecretManager.retrieveDataEncryptionKey:129` → `BlockTokenSecretManager.retrieveDataEncryptionKey:424`. That is the target check; the throw statement spans :424-426, and javac reports frame :426.
- Reachability: normal operation. A client caches a DEK (`DFSClient.getDataEncryptionKey`, DFSClient.java:1795-1814), then the NN and DN restart. The DN then only knows the new NN's keys, so the cached keyId is missing. This is the same sequence as the existing test `TestEncryptedTransfer#testLongLivedReadClientAfterRestart`.
- Safeguard noted: `chooseDataNode` (:865-913). When every location is in deadNodes and `failures < dfs.client.max.block.acquire.failures` (default 3, DFSConfigKeys:313-314), it sleeps `timeWindow*failures + timeWindow*(failures+1)*rand`, clears deadNodes, re-fetches locations (`openInfo`), increments `failures`, and retries. That retry would reach the same DN with the refreshed DEK.

## Step 2: Developer knowledge (queries run AFTER the reproduction verdict was settled, per adhoc Shared Rule 2)

- Local git history: the worktree has a single squashed commit ("base"), so no blame or history is available.
- Comments: none near :965-971 about the missing `continue`.
- Tests: `TestEncryptedTransfer#testLongLivedReadClientAfterRestart` exercises only stateful reads (DFSTestUtil.readFile). No existing test covers pread with a stale DEK.
- Web query 1: `HDFS JIRA fetchBlockByteRange InvalidEncryptionKeyException clearDataEncryptionKey continue addToDeadNodes pread`
- Web query 2: `HDFS pread encryption key invalid datanode added to dead nodes retry "encryption key" DFSInputStream JIRA`
- Result: **HDFS-5766**, "In DFSInputStream, do not add datanode to deadNodes after InvalidEncryptionKeyException in fetchBlockByteRange" (https://issues.apache.org/jira/browse/HDFS-5766). It reports the same mechanism at the same site and is fixed in 2.3.0 / 3.0.0-alpha1 (branch-2 r1558535). The pinned base predates it: the pom is dated Jan 15 2014.
- Related but different sites: HDFS-10609 (write pipeline recovery), HDFS-16136 (umbrella for IEK handling), HDFS-17897 (striped checksum path).

## Step 3: Known status

KNOWN (HDFS-5766, fixed upstream). The generic bug-confirmation pre-filter (code-review × known → DROPPED) would apply. However, adhoc-coordination Shared Rule 2 governs this run: the novelty search runs only after the verdict and "may set the Novelty field only; it must not change the reproduction or the verdict". So the verdict stays as settled by Phase 2 (MASKED), and Novelty = KNOWN.

## Phase 2 summary (see repro/test_bugCR-4_pread_dek_deadnode.java, run/repro-run{1,2}*.txt)

Level 0 (public API + MiniDFSCluster restarts only), run against pristine installed hadoop-hdfs jars. Results were identical on two runs.

- (A) Pread, 1 replica, default config: the DN is marked dead (`Could not obtain ... from any node`, `chooseDataNode: got # 1 IOException, will wait for ~1–2 s`). The read then succeeds, because the chooseDataNode all-dead recovery masks the failure. Elapsed 1948 / 949 ms.
- (B) Control: stateful read, same scenario. DEK refetched, DN not marked dead, 6 / 7 ms.
- (C) `dfs.client.max.block.acquire.failures=0`: pread throws BlockMissingException. (C') The stateful read under the same config succeeds.
- (D) 3 replicas: pread succeeds on the next DN, but the healthy first DN stays in the stream's deadNodes across later preads.

Verdict: MASKED. The mask is the chooseDataNode all-dead recovery (DFSInputStream.java:879-912). The finding's claimed consequence (the pread fails) appears only when that mask is disabled (max acquire failures = 0). With the default config the cost is a random 0–3 s backoff, one consumed acquire-failure slot, an extra NN `getBlockLocations`, and a healthy replica excluded for the stream's lifetime.
