# zk-adhoc-11 MC-3 (tier B): stop during sync skips the epoch write; the peer can never restart

System: zookeeper. Found by Specula's ad hoc run `zk-adhoc-11`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator). Same defect as b5/MC-2.

## Explanation (verified)

- **case/finding:** zk-adhoc-11/MC-3
- **defect:** a stop during sync ends `Learner.syncWithLeader`'s loop (`while (self.isRunning())`, L651) the same way UPTODATE does, so the only epoch write (L813) is skipped while the ACK and proposal logging still run; `QuorumPeer.loadDataBase` then throws at L1236 on every restart
- **why tier B:** in-process stops only (embedded or controller)

**Specula's finding MC-3:** A stop that ends the follower sync loop before NEWLEADER logs new-epoch txns with no epoch write, so every restart throws at QuorumPeer:1236

- **Cause:** Learner.syncWithLeader treats running=false at its loop check like a finished sync: the post-loop code ACKs, starts zk and logs packetsNotLogged, while setCurrentEpoch only runs under NEWLEADER or UPTODATE.
- **Trigger:** QuorumPeer.shutdown sets running=false while a follower with an older currentEpoch is reading proposals queued ahead of NEWLEADER, and the post-loop ACK reaches the socket before shutdown closes it.
- **Consequence:** The log holds epoch-E txns with currentEpoch below E and no currentEpoch.tmp, so QuorumPeer.loadDataBase throws IOException on every later start and the server stays down until an operator repairs its data directory.
- **Premises:** The stop comes through in-process QuorumPeer.shutdown (QuorumPeerMain.close, ZooKeeperServerEmbedded.close, tests); no production caller exists for a plain QuorumPeerMain process signal. The follower's currentEpoch is below the leader's epoch and at least one proposal is queued ahead of NEWLEADER, which needs client writes during the sync. No check of running or of sync completion exists between the loop and the post-loop logging.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_shutdown_race.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `zk-adhoc-11` (all phases) | 4h56m | 110.2M | $96.99 |
| of which: confirming this finding | | 3.0M | $3.61 |

Time is active time; quota sleeps are excluded.
