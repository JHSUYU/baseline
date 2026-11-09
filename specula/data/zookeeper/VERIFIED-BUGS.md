# ZooKeeper: verified bugs (high quality, severe, make the ad hoc check fail)

Same bar as `hdfs/VERIFIED-BUGS.md`. An independent reviewer read each candidate against the source (`batches/VERIFY-batch1.md`); the operator then read the decisive code of each bug kept here. Citations are at apache/zookeeper `eab16599`. Reproductions are Specula's; no test was rerun during verification.

## Kept

| tier | case/finding | defect | consequence | trigger |
| --- | --- | --- | --- | --- |
| A (tier medium confidence) | zk-adhoc-b3/MC-1 | `ContainerManager.checkContainers` (L140-160) posts a path-only `deleteContainer`; `PrepRequestProcessor` (L326-338) checks only `childCount` and `EphemeralType == NORMAL`, not that the node is still a container | a client's PERSISTENT znode re-created at the path is silently and durably deleted; `getData` throws at the target (`FinalRequestProcessor`:674) | default configuration, no fault; a container replaced by a persistent node between scan and post. Reported losses are from a stress test; production frequency unknown |
| B | zk-adhoc-b3/CR-3 | `ContainerManager.zkDb` is final (L45), set once at `ZooKeeperServerMain`:170, and is not rebound after a live restore | the manager keeps scanning the old tree and deletes restored nodes | needs an admin restore without a restart |
| B | zk-adhoc-b2/MC-1 (=MC-3) | `LeaderElectionSupport.toLeaderOffers` (L300-315) has no NoNode handling for an offer that vanishes between list and read; the exception reaches `becomeFailed` (L138-139) | a participant goes FAILED with its offer still live and blocks the election | a peer stops or its session ends during a listing; recipe library, whose Javadoc leaves recovery to the application |

## Dropped

See `batches/VERIFY-batch1.md`: b3/CR-2 (duplicate of MC-1), CR-4 (by design), CR-5 (unrealistic), CR-6 (CVE-2026-79993), CR-7 (ZOOKEEPER-5112); b2/MC-2 (not severe); b1/MC-1, CR-3 (ZOOKEEPER-5117), MC-2 (unrealistic), CR-4, CR-5 (off-target); 02/MC-1, MC-3 (not severe).

- **01/MC-1, 3, 4:** lease semantics or a deadline that really passed; not severe. **01/MC-2, CR-2, 03/MC-1, 2:** masked downstream. **03/MC-3:** needs an injected sleep; not severe. Details: `../batches/VERIFY-batch2.md`.

## Added from batch 3 (tier B; details and citations: `../batches/VERIFY-batch3.md`)

The operator re-read the decisive code at `eab16599` for each of these. No test was rerun.

| case/finding | defect | why tier B |
| --- | --- | --- |
| zk-adhoc-11/MC-3 | a stop during sync ends `Learner.syncWithLeader`'s loop (`while (self.isRunning())`, L651) the same way UPTODATE does, so the only epoch write (L813) is skipped while the ACK and proposal logging still run; `QuorumPeer.loadDataBase` then throws at L1236 on every restart | in-process stops only (embedded or controller) |
| zk-adhoc-11/CR-1 | `setCurrentEpoch` (L813) fails before `setSyncMode(NONE)` (L816), so a stale SNAP mode survives; one failed epoch write wedges an observer permanently, even after the disk recovers | needs a failed disk write; observers only |
| zk-adhoc-04/MC-2 | a read-only server runs on the same `zkDb` after `fastForwardDataBase` replayed uncommitted txns, serves them, and a next-epoch follower then refuses that client at `ZooKeeperServer` L1516 | read-only mode (non-default); the run is incomplete, so this rests on its confirmation entry alone |
| zk-adhoc-b6/MC-3 | `ObserverMaster.cacheCommittedPacket` eviction can empty `committedPkts` (L377-398), and `startForwarding` checks for a gap only if the queue has a head (L294-305); an observer silently misses a commit and later hits `ZKDatabase` L341 | weakest: stacked non-default settings, observer master only |

**Dropped from batch 3:** the other 44 findings of 04, 06, 07, 10, 11, 12, 13, b4, b5, b6 (known, injected timing, off-target, masked, or not severe). See the report's table.

**Off-target, not counted:** side finding S1 from 10/MC-1: a write whose body fails to deserialize reuses the previous zxid. It misses the target at default settings, was read in code only, and may be security-sensitive, so any upstream report should go to the ASF security list. See the report.

**zk-adhoc-04 is final as incomplete (owner, 2026-11-05):** no verdict and no resume. CR-5's conversation was stopped by a model safeguard flag; CR-6, CR-7 and MC-3 stayed unfinished. Its reproduced findings and its usage (5h38m, 128.8M tokens, $96.51) are kept and counted.
