# zk-adhoc-b6 MC-3 (tier B): ObserverMaster eviction empties the queue and skips the gap check; observer silently misses a commit

System: zookeeper. Found by Specula's ad hoc run `zk-adhoc-b6`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** zk-adhoc-b6/MC-3
- **defect:** `ObserverMaster.cacheCommittedPacket` eviction can empty `committedPkts` (L377-398), and `startForwarding` checks for a gap only if the queue has a head (L294-305); an observer silently misses a commit and later hits `ZKDatabase` L341
- **why tier B:** weakest: stacked non-default settings, observer master only

**Specula's finding MC-3:** ObserverMaster eviction drops a commit F has not applied; the observer misses it, hits the ZKDatabase:341 check and keeps a permanent hole

- **Cause:** ObserverMaster.cacheCommittedPacket can poll committedPkts empty, including the packet just added, although F forwards commits before applying them. syncFollower positions a syncing observer from F's applied state and startForwarding skips its gap check on an empty queue, so the evicted commit is never sent.
- **Trigger:** A packet over 0.8 * the size limit (lowered zookeeper.observerMaster.sizeLimit or JMX setObserverMasterPacketSizeLimit, or jute.maxbuffer above about 26.8 MB with a large znode) empties the queue while that commit is unapplied at F, and an observer syncs through F in that window. Routes: TRUNC when the restarted observer is ahead of F, DIFF otherwise.
- **Consequence:** The next INFORM throws IllegalStateException at ZKDatabase.java:341. The observer resyncs with an empty DIFF and permanently lacks the committed txn, then fires again per txn and its QuorumPeer thread dies. Restart either fails in loadDataBase or succeeds and serves NoNode for a committed znode after sync().
- **Premises:** Requires a non-default setting: a lowered zookeeper.observerMaster.sizeLimit (or JMX equivalent), or jute.maxbuffer above about 26.8 MB with a znode that large. It cannot happen at defaults. Requires an observer syncing through a follower's ObserverMaster while that follower has a forwarded, evicted, unapplied commit. Level 0 fired in 4 of 5 runs, about 1 per 300 observer restarts under about 50 writes per second in one JVM, always by the DIFF route. The counterexample's TRUNC route needed Level 1 holds on F's apply. Process exit after the QuorumPeer thread dies is read from QuorumPeerMain.java:118-119; the shared test JVM only shows the run thread ending. Recovery by wiping the observer's data directory was not tested.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_S3.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `zk-adhoc-b6` (all phases) | 3h21m | 55.3M | $60.40 |
| of which: confirming this finding | | 5.9M | $8.24 |

Time is active time; quota sleeps are excluded.
