# HDFS-10609: detected by Specula (yes), finding CR-3

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `hdfs-adhoc-k5`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

During write-pipeline recovery, `DataStreamer.setupPipelineForAppendOrRecovery -> addDatanode2ExistingPipeline -> transfer()` opens a SASL connection to an existing pipeline DataNode to copy the replica to the new node. If the client's cached DataEncryptionKey has become stale (block key expired and removed on the DNs, typical for long-lived writers such as Solr's HDFS tlog), the DataNode's `retrieveDataEncryptionKey` throws; unlike createBlockOutputStream, transfer() has no "clear key and retry" handling, so InvalidEncryptionKeyException escapes the streamer and fails the application's write/close. Fix: RefetchEncryptionKeyPolicy in transfer() (clear key, retry; throw after 2 failures).

## What counted as detecting it (written before the run)

A finding counts only if it shows: a long-lived writer whose DataEncryptionKey became invalid hits a pipeline recovery that adds a DataNode (replace-datanode-on-failure), the DataStreamer.transfer() handshake is rejected at line 420, and the exception is not handled by a key refresh, so the write/close fails to the application. Write-pipeline setup (createBlockOutputStream), reads, checksum and balancer are different bugs.

## What Specula found

**Specula's finding CR-3:** addDatanode2ExistingPipeline does not refetch the DEK on InvalidEncryptionKeyException; excludes healthy targets and fails append

- **Cause:** DataStreamer.addDatanode2ExistingPipeline catches every IOException from transfer() as a failure of the new target: it excludes that node and retries up to 3 times without calling dfsClient.clearDataEncryptionKey(), so a stale cached DEK rejected by the source DN at BlockTokenSecretManager.retrieveDataEncryptionKey (line 420) is reused on every try.
- **Trigger:** Encrypted transfer on; a long-lived client caches a DEK; the NN and DNs restart (new block keys); the client appends to a replication-3 file and the first DN of the append pipeline crashes before data is sent, so pipeline recovery adds a DN by block transfer before any other SASL connection refreshes the DEK.
- **Consequence:** The append fails for the application (out.close() throws InvalidEncryptionKeyException with 6 DNs, or 'Failed to replace a bad datanode ... no more good datanodes' with 4 DNs), and up to three healthy DNs are excluded. A control that refreshes the DEK first succeeds.
- **Premises:** dfs.encrypt.data.transfer=true and block access tokens enabled; no trusted-channel resolver. The client's cached DEK keyId is absent from the DN's BlockTokenSecretManager, reached via NN + DN restart while the client stays alive (as in TestEncryptedTransfer#testLongLivedWriteClientAfterRestart). Pipeline recovery reaches transfer() before any createBlockOutputStream/read SASL contact that would clear the DEK (here: pipeline[0] dead, so the first contact fails at connect). Default replace-datanode-on-failure policy (not best-effort), so the exception propagates to the writer. Pinned tree 68a2058 (3.0.0-alpha2-SNAPSHOT) predates the upstream fix HDFS-10609.

**Operator's judgement:** yes. code-review finding, reproduced by test (no TLC)

## Evidence

- TLC: none (code-review finding); the evidence is the reproduction.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 2h40m | 78.3M | $49.41 |

Time is active time; quota sleeps are excluded.
