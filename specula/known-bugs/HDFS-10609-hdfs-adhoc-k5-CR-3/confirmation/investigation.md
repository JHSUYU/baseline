# CR-3 investigation (Phase 1 — evidence only)

Source tree: worktree pinned at base_commit 68a2058 (+ Specula trace instrumentation, no-op unless -Dspecula.trace.file; line numbers unchanged).

## Step 1 — code audit
- `DataStreamer.addDatanode2ExistingPipeline` (hadoop-hdfs-client/.../DataStreamer.java:1200-1269): loop `tried < 3`; each try asks NN `getAdditionalDatanode(..., exclude, ...)`, then `transfer(src=original[tried%len], target=nodes[d], ...)`. `catch (IOException ioe)` at 1254-1264: logs "Error transferring data from", `exclude.add(nodes[d])` (the NEW target), resets pipeline, `tried++`. No `instanceof InvalidEncryptionKeyException` check, no `dfsClient.clearDataEncryptionKey()`.
- `transfer` (1271-1314): opens socket to **src** (an existing pipeline DN), `dfsClient.saslClient.socketSend(..., dfsClient, blockToken, src)` → uses `DFSClient.newDataEncryptionKey()` (DFSClient.java:1709-1722) which returns the cached `encryptionKey` unless null/expired. So a stale cached DEK is rejected by the **source** DN's `BlockTokenSecretManager.retrieveDataEncryptionKey` → `allKeys.get(keyId)==null` → throws IEK at BTSM.java:420; SaslDataTransferServer.java:415-425 sends ERROR_UNKNOWN_KEY, client DataTransferSaslUtil throws InvalidEncryptionKeyException.
- Note: the finding says "from the target DN"; precisely it is the transfer *source* DN (the DN the client connects to) that rejects. The excluded node is the healthy newly-allocated target, which never saw the client's DEK.
- Caller: `handleDatanodeReplacement` (DataStreamer.java:1435-1450) rethrows unless best-effort (default false) → `setupPipelineInternal` throws → streamer closed, user's write/close fails.
- Contrast: `createBlockOutputStream` (DataStreamer.java:1624-1634) and `DFSInputStream.blockSeekTo` (584-590) clear the DEK and retry on IEK.
- Reachability / trigger: long-lived client holds DEK from NN key set K1; NN restarts (new keys K2) and DNs restart (in-memory DN keys now K2 only) — same as existing test `testLongLivedWriteClientAfterRestart`. Client appends to a file whose last block needs a pipeline with replacement (repl 3, a pipeline DN dies) — the workload `testEncryptedAppendRequiringBlockTransfer`. The stale DEK reaches `transfer` only if no prior SASL connection refreshed it: if pipeline[0] is alive, the first `createBlockOutputStream` gets IEK and refetches (safeguard). So the trigger needs pipeline[0] to be the failed DN (connection refused, not IEK) — then bad-node removal → replacement → transfer with stale DEK.
- Safeguards recorded: (a) createBlockOutputStream refetch fires only when its first contact reaches SASL; (b) best-effort replace policy (non-default) would swallow the failure and the following createBlockOutputStream would refetch; (c) DEK expiry (tokenLifetime, default 10h) eventually refreshes.

## Step 2 — developer knowledge (code/tests only; tracker search deferred until after verdict per adhoc Shared Rule 2)
- SaslDataTransferServer.java:418-421 comment: "This could just be because the client is long-lived and hasn't gotten a new encryption key from the NN in a while. Upon receiving this error, the client will get a new encryption key from the NN and retry connecting to this DN." → developers intend clients to refetch and retry on IEK.
- DataStreamer.java:1626-1633: "The encryption key used is invalid ... Don't close the socket/exclude this node just yet. Try again with a new encryption key."
- Tests: TestEncryptedTransfer#testLongLivedWriteClientAfterRestart / testLongLivedReadClientAfterRestart assert a long-lived client survives NN+DN restart; #testEncryptedAppendRequiringBlockTransfer asserts the transfer path works with a fresh key. No test combines them.

## Step 3 — known status
Deferred to after verdict (adhoc Shared Rule 2: Phase-4 novelty search only after the reproduction verdict is settled; it sets Novelty only). Queries recorded below.

## Phase 2 result (settled before the novelty search)
REPRODUCED at Level 0/1 (public API + MiniDFSCluster restart/shutdown). See repro/test_bugCR-3_appendTransferStaleDek.sh, repro/CR-3.runner.out, repro/CR-3.evidence.log. Control (DEK refreshed by a read first) succeeds.

## Novelty search (run after the verdict; sets Novelty only)
Queries:
1. WebSearch: "HDFS InvalidEncryptionKeyException pipeline recovery addDatanode2ExistingPipeline transfer refetch encryption key JIRA"
2. WebSearch: "HDFS-10609 Uncaught InvalidEncryptionKeyException during pipeline recovery"
3. Fetched https://issues.apache.org/jira/browse/HDFS-10609 and https://issues.apache.org/jira/browse/HDFS-16136
4. specula findings lookup (addDatanode2ExistingPipeline / InvalidEncryptionKeyException / retrieveDataEncryptionKey) -> []
Result: HDFS-10609 "Uncaught InvalidEncryptionKeyException during pipeline recovery may abort downstream applications". Resolved/Fixed 2016-10-05, Fix Versions 2.8.0, 2.7.4, 3.0.0-alpha2. Stack trace shows transfer/addDatanode2ExistingPipeline. Same mechanism and site. The pinned tree (3.0.0-alpha2-SNAPSHOT, 68a2058) predates the fix: transfer() has no refetch. -> Novelty KNOWN (fix-status: fixed upstream; unfixed in the pinned tree). HDFS-16136 (open) covers other socketSend sites, not this one.
Per adhoc Shared Rule 2 the search does not change the verdict, so the bug-confirmation code-review x known DROPPED pre-filter is not applied.
