# zk-adhoc-04 MC-2 (tier B): read-only server serves never-committed txns (run incomplete)

System: zookeeper. Found by Specula's ad hoc run `zk-adhoc-04`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** zk-adhoc-04/MC-2
- **defect:** a read-only server runs on the same `zkDb` after `fastForwardDataBase` replayed uncommitted txns, serves them, and a next-epoch follower then refuses that client at `ZooKeeperServer` L1516
- **why tier B:** read-only mode (non-default); the run is incomplete, so this rests on its confirmation entry alone

**Specula's finding MC-2:** Read-only server exposes a never-committed txn, and a next-epoch follower then refuses the client

- **Cause:** shutdown(false) and restart replay apply every logged txn to the data tree with no commit check, and ReadOnlyZooKeeperServer serves that tree, so reads return logged-only data and a zxid that was never committed.
- **Trigger:** With readonlymode.enabled=true, a leader logs a write after its last follower stops and before its next quorum check, then loses quorum and starts a read-only server over the fast-forwarded tree. A client reads there, then reconnects to a server lacking the txn.
- **Consequence:** The client reads znodes that were never committed and later become NoNode, and servers lacking the txn refuse it at ZooKeeperServer.java:1516 until a new-epoch write arrives or it reaches the new leader.
- **Premises:** readonlymode.enabled=true and the client uses canBeReadOnly=true. The leader accepts writes between losing its last follower and its next quorum check, one tick at most in the test configuration. The dirty read needs the old leader to stay LOOKING for the read-only grace period; the never-committed outcome needs the next epoch to form without the old leader, which the reproduction achieves by stopping it. The refusal lasts until a new-epoch write arrives or the client reaches the new leader.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_S2_uncommitted_ro.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `zk-adhoc-04` (all phases) | 5h38m | 128.8M | $96.51 |
| of which: confirming this finding | | 4.1M | $7.48 |

Time is active time; quota sleeps are excluded.
