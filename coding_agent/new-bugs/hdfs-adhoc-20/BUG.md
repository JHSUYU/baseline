# hdfs-adhoc-20: BPOfferService.verifyAndSetNamespaceInfo accepts an ACTIVE NN at handshake without the txid split-brain check, so a stale ex-active NN can become the DN's active NN (assertion kills the actor; with assertions off the split-brain protection is bypassed).

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BPOfferService.java:615`, `BPOfferService.updateActorStatesFromHeartbeat(BPServiceActor, NNHAStatusHeartbeat)`, throws `java.lang.AssertionError` when `if (bpServiceToActive == actor) { assert txid >= lastActiveClaimTxId; }`
- Starting test: `org.apache.hadoop.hdfs.TestClientProtocolForPipelineRecovery#testPipelineRecoveryOnOOB`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Stale-active split-brain in an HA mini cluster: nn0 still reports ACTIVE at txid 4 after nn1 became active at txid 10. nn1 then steps down to standby, and the DN gets a new actor for nn0 (refreshNamenodes adding nn0) whose handshake sees ACTIVE while bpServiceToActive is null.

**Why (root cause in the source):** The heartbeat path rejects an ACTIVE claim with txid <= lastActiveClaimTxId as split-brain (BPOfferService.java:588-598). The handshake path, verifyAndSetNamespaceInfo (BPOfferService.java:385-390), sets bpServiceToActive = actor for any ACTIVE nsInfo whenever bpServiceToActive is null. It does no txid comparison and does not update lastActiveClaimTxId. The stale NN's next heartbeat therefore reaches 'assert txid >= lastActiveClaimTxId' (L615) with 4 < 10. With assertions on, the AssertionError escapes the Exception-only retry loop in BPServiceActor.run (L931-941) and the actor thread exits for good. In production (assertions off), lastActiveClaimTxId is overwritten with the stale txid and the DN treats a fenced NN as active, running its commands (for example invalidations based on a stale namespace) until a higher-txid claim takes over or the stale NN aborts on its next edit write. The DN-visible state (an unfenced old active still claiming ACTIVE at a lower txid, as in the QJM fencing window) is exactly what the txid rule exists to handle. The test creates it by calling transitionToActive on both NNs without fencing, and it needs a rare chain: a second failover plus an actor (re)handshake inside the stale window. So the gap is real but narrow.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The DN's ad hoc protocol for picking the active NN uses the txid of each active claim to resolve split-brain: a heartbeat claim with txid <= lastActiveClaimTxId is rejected ('Split-brain scenario'). The handshake path (verifyAndSetNamespaceInfo, 'Acknowledging ACTIVE Namenode during handshake') bypasses that rule. It accepts any NN that reports ACTIVE whenever bpServiceToActive is null, without comparing its txid or recording it in lastActiveClaimTxId. So a stale ex-active NN, which a correct protocol would reject, becomes the DN's active NN, and the invariant the assert encodes (the active actor's txid never goes backwards) no longer holds. Each step can happen in a real deployment: a transient dual-active during failover (the old active only finds out it was fenced when it next writes to QJM), the new active stepping down, and an actor (re)starting its handshake (refreshNamenodes, or a handshake retried after a failed or slow versionRequest/registration). Consequences: with assertions enabled, the BPServiceActor thread dies on an AssertionError, so the DN permanently stops heartbeating, block-reporting and registering with that NN until it restarts. With assertions disabled (production), the check is skipped and lastActiveClaimTxId is overwritten with the stale txid. The DN then treats the fenced/stale NN as active and runs its commands (e.g. block deletions or invalidations), and it can later reject the real active NN's claims, which is exactly the split-brain damage the txid comparison is meant to prevent.

**Execution (agent):** HA MiniDFSCluster with two NNs (nn0='nn1', nn1='nn2') sharing an edits dir, 1 DN, heartbeat interval 1s. (1) nn0 is made active and writes edits (txid 4). (2) Split-brain: nn1 is also transitioned to active (as happens when nn0 is paused or loses its ZK session and nn1 gets elected), catches up and writes more edits (txid 10). nn0 has not noticed yet and keeps reporting ACTIVE at txid 4. (3) A DN configured only with nn1 starts. Its actor handshakes with nn1 and its heartbeats record lastActiveClaimTxId=10. (4) nn1 steps down to standby. The DN's heartbeat sees 'relinquishing ACTIVE', so bpServiceToActive=null while lastActiveClaimTxId stays 10. (5) The operator adds nn0 to the DN's NN list and runs refreshNamenodes (DataNode.refreshNamenodes(conf)). BPOfferService.refreshNNList starts a new BPServiceActor for nn0. In connectToNNAndHandshake, versionRequest returns state ACTIVE, and BPOfferService.verifyAndSetNamespaceInfo sets bpServiceToActive=actor0 because bpServiceToActive==null. This handshake path does no txid check and does not update lastActiveClaimTxId. (6) actor0's first heartbeat to nn0 returns ACTIVE with txid=4. In updateActorStatesFromHeartbeat, nnClaimsActive && bposThinksActive, so the 'more recent claim' check is skipped and the code reaches 'assert txid >= lastActiveClaimTxId' (4 >= 10), which throws java.lang.AssertionError at BPOfferService.java:615. The error is not an Exception, so it escapes the offerService retry loop. BPServiceActor.run logs 'Unexpected exception in block pool' and the actor thread exits (FAILED).

**Stack frame (agent):** at org.apache.hadoop.hdfs.server.datanode.BPOfferService.updateActorStatesFromHeartbeat(BPOfferService.java:615)

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.datanode.TestBPOfferServiceStaleActiveHandshake#testStaleActiveAcceptedDuringHandshake`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.datanode.TestBPOfferServiceStaleActiveHandshake#testStaleActiveAcceptedDuringHandshake' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestBPOfferServiceStaleActiveHandshake.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.lang.AssertionError`, frame `at org.apache.hadoop.hdfs.server.datanode.BPOfferService.updateActorStatesFromHeartbeat(BPOfferService.java:615)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h09m | 1 | 1,015,087 | 44 | 37,819 | 63,695 | 913,529 | $1.45 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
