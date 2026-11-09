# hdfs-adhoc-07 MC-1 (tier A): JN purge marks a restarted JN's live segment .stale; an acknowledged edit is lost after failover

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-07`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hdfs-adhoc-07/MC-1
- **defect (root cause):** `FileJournalManager.purgeLogsOlderThan`/`isStaleInProgressLog` (L199-224) mark `.stale` every in-progress segment at or after `minTxIdToKeep` except `currentInProgress`. That field is in memory only, set by `startLogSegment` (L124), and so null after a JournalNode restart
- **consequence:** a restarted JN's copy of the writer's open segment, including edits it acknowledged, is hidden by the next checkpoint purge. A later failover finalizes a shorter segment; **an acknowledged edit is lost** (the target `AssertionError` at `Journal.acceptRecovery`:926, an explicit throw)
- **trigger:** one JN restart inside a segment, a checkpoint purge, and a failover while the JN holding the edit is slow; QJM tolerates this

**Specula's finding MC-1:** Purge after a JournalNode restart stale-marks its open edit segment; QJM recovery then discards a committed txn (Journal.acceptRecovery AssertionError)

- **Cause:** FileJournalManager.purgeLogsOlderThan marks stale every in-progress segment at or after minTxIdToKeep except the in-memory currentInProgress, which is null after a JournalNode restart until the next startLogSegment. A purge reaching a restarted JN therefore renames the writer's still-open segment, including acknowledged txns, to .stale. The purge's RequestInfo committedTxId is bound when the IPCLoggerChannel task starts, so it can carry a pre-commit value, and QJM's recovery sanity check only looks at prepare responders.
- **Trigger:** 3 JNs. j0 acks the last batch (txn 2) and crashes before the writer sees the quorum; a checkpoint purge issued meanwhile binds committedTxId=1 and is delivered to j0 after its restart through IPC connect retries (default 10 x 1 s); j1 acks txn 2 (committed) and learns committedTxId=2; j2 missed txn 2; the old writer stops; the new writer's prepare quorum is {j0: no segment, j2: [1,1]} while j1 answers late.
- **Consequence:** acceptRecovery([1,1]) on j1 throws java.lang.AssertionError from Journal.acceptRecovery (throw statement at Journal.java:926, frame line 932), but accept and finalize succeed on the majority {j0,j2}: with assertions off, as Hadoop daemons run, the new writer finalizes segment 1 as [1,1] and readers get txids [1], so the acknowledged txn 2 is permanently lost. With -ea the test-only QuorumCall.checkAssertionErrors aborts the failover instead.
- **Premises:** A JournalNode restart leaves FileJournalManager.currentInProgress null until that JN receives the next startLogSegment. Any NameNode purge has minTxIdToKeep <= the open segment's first txid (FSEditLog.purgeLogsOlderThan precondition), so only currentInProgress protects the open segment. IPCLoggerChannel.purgeLogsOlderThan has no out-of-sync check and binds committedTxId when its task starts; the IPC client retries refused connections (ipc.client.connect.max.retries default 10). The old writer sends no further batch to the restarted JN before failover, and the JN that holds the committed txn is outside the new writer's prepare quorum. Production JVMs run without -ea, so QuorumCall.checkAssertionErrors does not stop the new writer after a minority AssertionError.

## Evidence

- TLC: `tlc/RERUN.md` (config `purge_guided_b.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-07` (all phases) | 5h48m | 303.2M | $159.65 |
| of which: confirming this finding | | 27.6M | $13.15 |

Time is active time; quota sleeps are excluded.
