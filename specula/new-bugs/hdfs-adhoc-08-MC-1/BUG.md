# hdfs-adhoc-08 MC-1 (tier A): epoch selection reads only a quorum's promises; a JN fences the new writer for its whole term

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-08`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hdfs-adhoc-08/MC-1
- **defect (root cause):** `QuorumJournalManager.createNewUniqueEpoch` takes `maxPromised` from a write quorum of `getJournalState` replies only and never re-proposes
- **consequence:** a JN outside that quorum that holds a higher orphan promise (left by failed epoch attempts) rejects every request of the new writer for its whole term, at the target (`Journal.checkRequest`:487-489): **no JN fault tolerance until the next failover**; one more JN failure stops the NameNode (reproduced)
- **trigger:** two failed or interrupted epoch attempts during failovers, then a late `getJournalState` reply

**Specula's finding MC-1:** QJM: an orphan newEpoch promise left on a minority JN by failed writer attempts fences the next established writer at Journal.checkRequest for its whole term

- **Cause:** QuorumJournalManager.createNewUniqueEpoch picks myEpoch = 1 + max(lastPromisedEpoch) over the first majority of getJournalState replies and, after any majority of newEpoch successes, calls AsyncLoggerSet.setEpoch(myEpoch) on every logger (QJM:232-247, ALS:61-68). A JN persists a newEpoch promise before the proposer knows whether a quorum accepted (Journal.java:347-352), so failed attempts can leave a minority JN with a promise above the epoch the next writer establishes; that JN then rejects every RequestInfo RPC of the new writer at Journal.checkRequest (Journal.java:486-489).
- **Trigger:** Two writer epoch attempts each get newEpoch accepted only by JN0 and then fail (newEpoch to JN1/JN2 lost or the NameNode stops first), leaving JN0 at promise P while JN1/JN2 stay lower; the next writer does not hear JN0's getJournalState (request lost, JN0 briefly down, or its reply arrives after the majority), establishes epoch E < P on JN1/JN2, and its first RPC to JN0 (startLogSegment, or prepareRecovery when a segment exists) fails with 'IPC's epoch E is less than the last promised epoch P'.
- **Consequence:** The newest, legitimately established writer is fenced on JN0 for its whole term: every startLogSegment/journal/heartbeat/prepareRecovery/acceptRecovery/finalizeLogSegment to JN0 throws the target IOException, JN0 receives none of its edits, the promise survives a JN0 restart and the per-roll rejoin always fails. The writer runs on 2 of 3 JNs with no fault margin: one more JN failure makes the NameNode's JournalSet terminate the NameNode (reproduced; controls survive the same failure).
- **Premises:** Journal.newEpoch persists the promise (updateLastPromisedEpoch) before the proposer learns whether a quorum accepted; nothing retracts it when the attempt fails. createNewUniqueEpoch derives myEpoch only from the majority of getJournalState replies that QuorumCall.waitFor returns, and calls setEpoch on all loggers after any newEpoch majority without reacting to a minority's higher promise or rejection. No writer-side mechanism raises the epoch during a writer's term (createNewUniqueEpoch runs once per writer); IPCLoggerChannel's rejoin at the next roll resends the same epoch; JournalNodeSyncer has no epoch logic and its backfill is gated on committedTxnId, which the fenced writer cannot advance on JN0. The triggering faults are in the HDFS fault model: lost RPCs or a JN outage, a NameNode that stops/terminates after a failed newEpoch quorum, and a JN reply slower than the majority; two failed attempts are needed so the orphan promise strictly exceeds the new writer's epoch (with one, the epochs tie and checkRequest passes). The shared QJM edits dir is a required journal (FSNamesystem.getRequiredNamespaceEditsDirs), so JournalSet terminates the NameNode on its failure (JournalSet.java:394-408).

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_orphan_promise.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-08` (all phases) | 5h53m | 253.0M | $148.60 |
| of which: confirming this finding | | 23.7M | $11.60 |

Time is active time; quota sleeps are excluded.
