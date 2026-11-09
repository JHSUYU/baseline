# zk-adhoc-11 CR-1 (tier B): one failed epoch write leaves SNAP sync mode; an observer is wedged for good

System: zookeeper. Found by Specula's ad hoc run `zk-adhoc-11`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** zk-adhoc-11/CR-1
- **defect:** `setCurrentEpoch` (L813) fails before `setSyncMode(NONE)` (L816), so a stale SNAP mode survives; one failed epoch write wedges an observer permanently, even after the disk recovers
- **why tier B:** needs a failed disk write; observers only

**Specula's finding CR-1:** One failed SNAP-sync currentEpoch write leaves an observer's syncMode at SNAP, so QuorumPeer:1236 re-fires on every registerWithLeader and it never re-syncs

- **Cause:** Learner.syncWithLeader resets syncMode only after setCurrentEpoch succeeds, so a failed write leaves it at SNAP. Every later Learner.shutdown then clears zkDb, and an observer reloads it in registerWithLeader, where the on-disk epoch is older than the persisted snapshot.
- **Trigger:** A fresh observer SNAP-syncs from a quorum with data; the snapshot persists at NEWLEADER, then one currentEpoch write fails before the rename, leaving no currentEpoch.tmp.
- **Consequence:** The observer never serves clients again: about 10 attempts per second each throw the target IOException and log stack traces, through leader changes, and a process restart fails at the same throw until an operator repairs the data directory.
- **Premises:** A currentEpoch write can fail with an I/O error before the rename, after the snapshot was persisted; the fault happens once and later writes succeed. The peer is an observer (peerType=observer), so FastLeaderElection does not reload the database and the reload happens in registerWithLeader. The JVM records the target throw at QuorumPeer.java:1237: the statement starts at 1236 and javac attributes the constructor call to the message argument line.

## Evidence

- TLC: none (code-review finding); the evidence is the reproduction.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `zk-adhoc-11` (all phases) | 4h56m | 110.2M | $96.99 |
| of which: confirming this finding | | 2.3M | $2.73 |

Time is active time; quota sleeps are excluded.
