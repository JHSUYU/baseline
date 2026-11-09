# HDFS-14075 (NameNode crashes with NPE): detected

Case `hdfs-adhoc-k6`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/FSEditLog.java:1409`, `FSEditLog.endCurrentLogSegment(boolean)`, throws `java.lang.IllegalStateException` when `Preconditions.checkState(isSegmentOpen(), "Bad state: %s", state)   (isSegmentOpen(): state == State.IN_SEGMENT)`
- Starting test: `org.apache.hadoop.hdfs.server.namenode.TestEditLogRace#testEditLogRolling[1]`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** yes

**What the agent found:** A rollEditLog whose startLogSegment fails on all (non-required) edits dirs leaves FSEditLog in BETWEEN_LOG_SEGMENTS while the NameNode keeps running; the next rollEditLog fails Preconditions.checkState(isSegmentOpen()) in endCurrentLogSegment with IllegalStateException 'Bad state: BETWEEN_LOG_SEGMENTS'.

**Same root cause as HDFS-14075?** Yes. In the buggy FSEditLog.rollEditLog (FSEditLog.java:1314-1322) endCurrentLogSegment(true) moves the state to BETWEEN_LOG_SEGMENTS, then startLogSegment (FSEditLog.java:~1382-1386) catches the JournalSet IOException and only rethrows 'Unable to start log segment 5: too few journals successfully started', leaving state unchanged and the NN alive. The next roll hits the check at FSEditLog.java:1409 (frame rollEditLog:1316 in validate-1.log). This is exactly the hunk the fix replaces: the catch block in startLogSegment now logs, closes the journalSet and calls terminate(1, msg) instead of rethrowing.

**Realistic?** Yes. MiniDFSCluster with default config (plus valid dfs.namenode.name.dir.restore=true); the fault is an I/O failure creating the new edits_inprogress file on every edits dir (simulated by placing a directory at that path, so RandomAccessFile open fails), which is a local disk I/O failure at an I/O boundary; the rolls are ordinary rollEditLog RPC-server calls as issued by the SecondaryNameNode/standby. No reflection, no fabricated state, no direct call into the check with made-up arguments.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **NOT_REPRODUCED**. On the buggy tree plus the fix, the IllegalStateException no longer occurs (NOT_REPRODUCED, 2 attempts); the test instead fails with 'Test resulted in an unexpected exit' at MiniDFSCluster.shutdown, i.e. the first failed startLogSegment now calls terminate(), which is the fix's intended behaviour (NameNode terminates instead of continuing with no open segment).

**Reason:** The agent's validated reproduction reaches the check through precisely the defect HDFS-14075 fixes: a failed startLogSegment during a log roll leaves the edit log with no open segment while the NameNode keeps running, so the next roll/endCurrentLogSegment fails. The trigger is a realistic disk I/O fault plus ordinary roll RPCs, and the consequence (the NN keeps running with a broken edit log and later rolls fail) matches the JIRA; the fixed version terminates the NN at the first failure instead.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** rollEditLog is not atomic. It closes the current segment before opening the new one and does not restore or reopen a segment when the open fails. A transient I/O error on the edits dirs (disk full, EIO, a briefly failed mount), which are local, non-required dirs by default, does not shut the NameNode down. The edit log is left with no open segment even though the NN is still active. With dfs.namenode.name.dir.restore the storage is meant to come back once the disk is healthy, but every later roll (each SecondaryNameNode checkpoint, each Standby log-roll request) now fails with IllegalStateException rather than starting a fresh segment. So the NN never recovers its edit log by itself: checkpoints keep failing and edits are not persisted to a segment, so client mutations fail or are at risk, and an operator has to restart the NameNode. The state is produced by the system's own fault handling, not by an invalid user request.

**Execution (agent):** 1) MiniDFSCluster, single active NameNode with its default two local (non-required) name/edits dirs, dfs.namenode.name.dir.restore=true, 1 DataNode. 2) A normal rollEditLog RPC succeeds (the edit log is IN_SEGMENT). 3) Disk fault injected: on both edits dirs the next in-progress file (edits_inprogress_<lastWritten+2>) cannot be created (the test puts a directory at that path, so RandomAccessFile fails with 'Is a directory'). 4) The rollEditLog RPC (the kind the SecondaryNameNode or Standby EditLogTailer sends) runs FSEditLog.rollEditLog: endCurrentLogSegment(true) finalizes the old segment and sets state=BETWEEN_LOG_SEGMENTS. Then startLogSegment -> JournalSet.startLogSegment fails on both non-required journals, which are disabled (the NN is not terminated because they are not required), and throws IOException 'Unable to start log segment 5: too few journals successfully started'. The state stays BETWEEN_LOG_SEGMENTS, and the NameNode keeps running and serving RPCs. 5) The disk recovers (the obstruction is removed). 6) The next rollEditLog RPC (the next periodic checkpoint or tailer roll) calls endCurrentLogSegment(true) with state BETWEEN_LOG_SEGMENTS, so Preconditions.checkState(isSegmentOpen()) throws java.lang.IllegalStateException: Bad state: BETWEEN_LOG_SEGMENTS at FSEditLog.java:1409 (via FSEditLog.rollEditLog:1316 <- FSImage.rollEditLog <- FSNamesystem.rollEditLog <- NameNodeRpcServer.rollEditLog).

**Stack frame (agent):** at org.apache.hadoop.hdfs.server.namenode.FSEditLog.endCurrentLogSegment(FSEditLog.java:1409)

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.namenode.TestEditLogRollAfterFailedStart#testRollAfterFailedSegmentStart`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.namenode.TestEditLogRollAfterFailedStart#testRollAfterFailedSegmentStart' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/TestEditLogRollAfterFailedStart.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.lang.IllegalStateException: Bad state: BETWEEN_LOG_SEGMENTS`, frame `at org.apache.hadoop.hdfs.server.namenode.FSEditLog.endCurrentLogSegment(FSEditLog.java:1409)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h02m | 1 | 340,542 | 22 | 9,555 | 33,700 | 297,265 | $0.52 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
