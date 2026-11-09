# zk-adhoc-10: A malformed client request gets an error txn with an already used zxid (zks.getZxid() instead of getNextZxid()), so the leader proposes a duplicate zxid. Followers then fail commit matching and crash or drop out of the quorum.

Severity (reviewer): **outage**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ObserverMaster.java:371`, `ObserverMaster.removeProposedPacket(long)`, throws `java.lang.RuntimeException` when `pkt != null && !(pkt.getZxid() > zxid) && pkt.getZxid() != zxid   (pkt = proposedPkts.peek())`
- Starting test: `org.apache.zookeeper.test.ObserverMasterTest#testInOrderCommits[1]`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** A client on the leader pipelines a large create and right behind it a create request whose body cannot be deserialized (sent over the normal client wire protocol; no server code touched). Ordinary writes from a second client follow. Followers run ObserverMasters.

**Why (root cause in the source):** In PrepRequestProcessor.pRequestHelper, readRequestRecord throws before getNextZxid() is called (PrepRequestProcessor.java:781-783). The catch-all handler then stamps the MARSHALLINGERROR error txn with zks.getZxid(), the zxid already given to the previous write (PrepRequestProcessor.java:928-939). The leader proposes the same zxid twice and commits it once, so followers keep a duplicate proposal at the head of ObserverMaster.proposedPkts, and the next COMMIT fails at ObserverMaster.java:371. Zxid uniqueness is a Zab invariant, and any client can send such a packet. Line 371 is reached only under the LOG_ONLY exit handler that tests use. With the default handler the follower instead exits with UNMATCHED_TXN_COMMIT (FollowerZooKeeperServer.commit), which is worse. The agent also reports that the leader can stall all writes when the duplicated write was already committed.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Zab needs every proposal in an epoch to carry a unique, increasing zxid, and ObserverMaster's check relies on that: each COMMIT matches the head of proposedPkts. The coordination breaks on the leader: PrepRequestProcessor.pRequestHelper's catch(Exception) branch stamps the error txn for an unparseable request with zks.getZxid() (an already-used zxid) instead of a new one. The multi path already avoids this by calling getNextZxid() on IOException; the single-op paths do not. Any client (a buggy or incompatible client library, or a corrupted packet) can send such a request. Rejecting it with MARSHALLINGERROR is correct; giving the rejection a duplicate zxid is the bug. Consequences: the leader keeps only one of the two proposals, so the earlier write's slot gets the error txn (here the /big client received the malformed request's error, a 'Xid out of order' connection loss) and the leader's state and log no longer match the followers'. Followers that run an ObserverMaster then fail this check (or, with the default exit handler, exit with UNMATCHED_TXN_COMMIT) and drop out of the quorum, which can cost the cluster its availability. If the duplicated write was already committed, the leader instead stalls all writes indefinitely.

**Execution (agent):** Cluster from ObserverMasterTestBase with observerMasterPort set: participants 1 and 2 (each follower runs an ObserverMaster) and observer 3. 1) One client connects to the leader and does a few normal creates. 2) On the same connection it pipelines an async create of /big (900 KB data, zxid z) and right behind it a create request whose body cannot be deserialized (the path string length is 0x7fffffff), sent through the client's own packet queue, so no server code is touched. 3) The leader's PrepRequestProcessor fails with IOException in readRequestRecord before any zxid is assigned. The catch-all handler then builds an error txn header with zks.getZxid(), which is z, the zxid already given to /big. The leader proposes zxid z a second time while /big is still outstanding (the large proposal is slow to replicate and fsync). outstandingProposals.put(z, ...) replaces the /big proposal. 4) Every follower receives PROPOSAL(z) twice ('Got zxid 0x..07 expected 0x..08'). Both copies go into FollowerZooKeeperServer.pendingTxns and into ObserverMaster.proposedPkts. 5) The leader commits z only once. On the follower, COMMIT(z) removes the first copy from both queues. 6) A second client issues ordinary creates (z+1, ...). On COMMIT(z+1) the head of proposedPkts is still the duplicate with zxid z < z+1, so removeProposedPacket throws RuntimeException('Unexpected proposal packet on commit ack') at ObserverMaster.java:371. The follower drops out of the leader's quorum and has to re-sync. Reproduced in 4 of 4 runs with this setup. Caveat: in the same COMMIT(z+1), FollowerZooKeeperServer.commit runs first, detects the same mismatch ('Committing zxid 0x..08 but next pending txn 0x..07') and calls ServiceUtils.requestSystemExit(UNMATCHED_TXN_COMMIT). Line 371 is only reached because the exit procedure is LOG_ONLY, which ZKTestCase sets for all tests and which embedded deployments can choose (ZooKeeperServerEmbedded with ExitHandler.LOG_ONLY). With the default SYSTEM_EXIT the follower JVM exits before line 371. Earlier attempts in which the duplicated write had already been committed when the error txn was proposed did not reach the check. Instead the leader stalled for good: the duplicate stays in outstandingProposals because acks for an already-committed zxid are ignored, and tryToCommit then blocks every later zxid on containsKey(zxid-1).

**Stack frame (agent):** at org.apache.zookeeper.server.quorum.ObserverMaster.removeProposedPacket(ObserverMaster.java:371)

## Reproduction

- Test: `org.apache.zookeeper.test.ObserverMasterDuplicateZxidTest#testMalformedRequestDuplicatesZxidAndBreaksObserverMaster`
- Command: `mvn -B -o test -pl zookeeper-server -Dtest='org.apache.zookeeper.test.ObserverMasterDuplicateZxidTest' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-server/src/test/java/org/apache/zookeeper/test/ObserverMasterDuplicateZxidTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: java.lang.RuntimeException: Unexpected proposal packet on commit ack, expected zxid 0x4294967304 got zxid 0x4294967303`, frame `at org.apache.zookeeper.server.quorum.ObserverMaster.removeProposedPacket(ObserverMaster.java:371)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h16m | 2 | 3,877,698 | 92 | 59,983 | 204,989 | 3,612,634 | $5.99 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
