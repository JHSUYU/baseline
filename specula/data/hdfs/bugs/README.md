# HDFS bugs found by Specula: TLC files

One folder per finding Specula reproduced in the real system, holding only its TLC files:
- the specification modules (`*.tla`);
- the config that produced the counterexample;
- the counterexample log;
- `RERUN.md` with the command (TLC jars pinned in `../../../tlc/`).

Every folder was rerun from this copy; each reports its target invariant violated.

Code-review findings (no TLC counterexample) are listed in `../CLASSIFICATION.md`, not here: 06/CR-3, 09/CR-3, 09/CR-5, 11/CR-3, 11/CR-4, 20/CR-2.

**Status of "new":**
- Each candidate new bug below was reproduced on the unmodified base commit (apache/hadoop `734dd8a67cd`).
- Specula's own post-verdict search of JIRA, GitHub PRs, the web and git history found no report.
- The code is unchanged on trunk (fetched 2026-10-26).
- Novelty has **not** been independently confirmed, and nothing has been filed.

| folder | target? | class | defect |
| --- | --- | --- | --- |
| `hdfs-adhoc-07/MC-1` | target | candidate new (critical) | `FileJournalManager.purgeLogsOlderThan` marks a restarted JournalNode's live in-progress segment `.stale`; after failover an acknowledged edit is lost |
| `hdfs-adhoc-07/MC-4` | | candidate new | a queued `acceptRecovery` binds the next segment's committed txid (fault-free failover with a slow JN) |
| `hdfs-adhoc-08/MC-1` | target | candidate new | epoch selection reads only a quorum; an orphan higher promise on a minority JN fences the newest writer for its term |
| `hdfs-adhoc-08/MC-2` | | candidate new | `Journal.doRollback` keeps the cached `lastPromisedEpoch` |
| `hdfs-adhoc-09/MC-1` | target | candidate new (critical) | `JournalSet.selectInputStreams` swallows a read failure of the required QJM; the new active NN starts below the committed txid and terminates |
| `hdfs-adhoc-09/MC-3` | | candidate new | `Journal.discardSegments` (rolling-upgrade rollback) is not epoch-fenced |
| `hdfs-adhoc-10/MC-1` | target | known (HDFS-17563; HDFS-3726's designed handling) | a lost `startLogSegment` leaves the writer's channel in sync; the epoch's first `journal()` fails |
| `hdfs-adhoc-10/MC-2` | | known (HDFS-17563) | the same, triggered by a JN restart |
| `hdfs-adhoc-10/MC-3` | | candidate new | `Journal.startLogSegment` rejects a header-only (0-txn) in-progress file |
| `hdfs-adhoc-10/MC-4` | | by design | a timed-out start runs late on the JN |
| `hdfs-adhoc-10/MC-5` | | variant of HDFS-17563 | a disk fault while persisting the writer epoch |
| `hdfs-adhoc-11/MC-1` | target | candidate new | in safe mode the NN stops pushing block keys but keeps rolling them |
| `hdfs-adhoc-11/MC-2` | | known (HDFS-13441) | a lost heartbeat reply drops the key push |
| `hdfs-adhoc-11/MC-3` | | candidate new | DN registration exports keys before joining the heartbeat set; a concurrent roll misses it |
| `hdfs-adhoc-11/MC-4` | | candidate new (wrong result) | after NN+DN restarts, snapshot-path / explicit-length `getFileChecksum` returns a wrong checksum |
| `hdfs-adhoc-11/MC-5` | | same defect as 11/MC-1 | the standby/observer case |
| `hdfs-adhoc-11/MC-6` | | candidate new | a restarted NN issues DEKs from new keys before DNs re-register |
| `hdfs-adhoc-11/MC-7` | | known (HDFS-16136) | DN-to-DN transfer after an NN restart |
| `hdfs-adhoc-14/MC-1` | target | candidate new (non-default config) | with `dfs.encrypt.data.overwrite.downstream.derived.qop=true`, a DN re-signs a forwarded block token with its own key but keeps the keyId |
| `hdfs-adhoc-14/MC-2..MC-4` | | same defect as 14/MC-1 | replication, HA failover, NN restart cases |
| `hdfs-adhoc-20/MC-1` | target | candidate new | NN heartbeats advertise the assigned (not yet durable) txid; after a crash DNs reject the real active (assert with -ea; dropped commands in production, see 20/CR-2) |
| `hdfs-adhoc-20/MC-2` | | same defect as 20/MC-1 | the HA re-activation case |
| `hdfs-adhoc-20/MC-3` | | candidate new (lower severity) | the DN handshake installs a reported-ACTIVE NN without a txid check |
