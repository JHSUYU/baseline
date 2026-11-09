# HDFS-14075: detected by Specula (yes), finding MC-1

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `hdfs-adhoc-k6`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

`FSEditLog.rollEditLog` first runs `endCurrentLogSegment` (finalizes the segment, `editLogStream = null`, `state = BETWEEN_LOG_SEGMENTS`), then `startLogSegment`. If too many journals fail in `journalSet.startLogSegment` (e.g. required/QJM journals unavailable), the buggy code only throws `IOException("Unable to start log segment N: too few journals successfully started.")` to the RPC caller (rollEditLog from the standby/checkpointer). The NameNode keeps running with the edit log open for write but with no segment and a null stream. The next edit then hits `editLogStream.write(op)` in `doEditTransaction` -> `NullPointerException` (the JIRA's FATAL in `FSEditLogAsync.run`, NN exits with an NPE instead of a clean, logged terminate); with sync edit logging the NPE goes to the client instead. The fix terminates the NN in `startLogSegment` (closing the journal set).

## What counted as detecting it (written before the run)

Same root cause: a failed `startLogSegment` (journal failure) during a roll is not fatal, leaving the edit log in `BETWEEN_LOG_SEGMENTS` with `editLogStream == null` while the NN keeps serving; the finding must show the target check at line 1409 failing on a later roll (an NPE in `doEditTransaction`/`logSync` on the same state also identifies the same bug, but the count is for the target check).

## What Specula found

**Specula's finding MC-1:** Failed startLogSegment during rollEditLog leaves the edit log in BETWEEN_LOG_SEGMENTS; the next roll fails checkState at FSEditLog.java:1409

- **Cause:** rollEditLog runs endCurrentLogSegment (state := BETWEEN_LOG_SEGMENTS unconditionally) and then startLogSegment. When the only non-required journal fails, JournalSet disables it and throws IOException without terminate, so IN_SEGMENT is never restored and the NN stays Active.
- **Trigger:** Single local edits dir. A roll runs while the dir becomes unwritable: finalize fails (swallowed) and start fails (IOException to the caller). Then another rollEditLog arrives before any client edit.
- **Consequence:** The next rollEditLog RPC throws IllegalStateException('Bad state: BETWEEN_LOG_SEGMENTS') from FSEditLog.endCurrentLogSegment:1409 on every retry, even after the disk is repaired (attemptRestoreRemovedStorage is never reached). The NN stays up with no working journal.
- **Premises:** All configured edits dirs are non-required (default single local dfs.namenode.edits.dir), so JournalSet throws IOException instead of terminate(1). The base tree (3.3.0-SNAPSHOT, c37cda11) predates HDFS-14075 (commit 042c8ef593ce), which makes startLogSegment failure terminate the NN. No client edit reaches logSync between the failed roll and the next roll; a client edit would instead terminate the NN via logSync.

**Operator's judgement:** yes. failed startLogSegment during roll leaves BETWEEN_LOG_SEGMENTS; next roll fails FSEditLog:1409

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_s1_start_failure.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-08: Invariant TargetSafe is violated.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 1h05m | 36.3M | $25.76 |

Time is active time; quota sleeps are excluded.
