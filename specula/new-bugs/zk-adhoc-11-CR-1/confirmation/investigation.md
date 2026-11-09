# CR-1 investigation (evidence only)

Source pinned at eab16599. The worktree carries trace-only Specula instrumentation that moves no line in QuorumPeer.java; SPECULA_TRACE_FILE is unset in every run here.

## Step 1: code audit
Cited sites read in context:
- `Learner.java:816` is the only `setSyncMode(NONE)` in main code (grep: Learner:588, 597, 620, 816). It runs right after `self.setCurrentEpoch(newEpoch)` in the NEWLEADER branch, so a throw there skips it.
- `Learner.java:924` `zk.shutdown(self.getSyncMode().equals(SNAP))`.
- `ZooKeeperServer.shutdown(boolean)`: `zkDb.clear()` runs when `fullyShutDown`, even when `canShutdown()` is false, so a server that never started still clears the shared db.
- `ZKDatabase.clear()` sets `initialized = false` (ZKDatabase.java:191).
- `QuorumPeer.java:1387-1388` `getLastLoggedZxid` reloads when `!zkDb.isInitialized()`.
- `FastLeaderElection.java:864-868`: a non-participant returns Long.MIN_VALUE, so no reload during an observer's election.
- `QuorumPeer.java:1592-1610` OBSERVING: catches Exception, `observer.shutdown()` in finally, loops.
- `Observer.java:107-135` observeLeader: `registerWithLeader` is inside `catch (Exception e)`, which includes the RuntimeException wrapping QP:1236.
- `QuorumPeer.java:1236` guard `epochOfZxid > currentEpoch && !currentTmp.exists()`.

Call chain: QuorumPeer.run:1596 -> Observer.observeLeader -> Learner.registerWithLeader:490 -> QuorumPeer.getLastLoggedZxid:1388 -> loadDataBase:1236.

Hypothesised trigger: a fresh observer joins (currentEpoch=0 on disk) -> SNAP -> takeSnapshot at NEWLEADER persists a snapshot in the leader's epoch -> setCurrentEpoch write fails before the rename (no currentEpoch.tmp remains, AtomicFileOutputStream deletes or never creates it) -> syncMode stays SNAP -> shutdown clears -> re-election -> reload -> QP:1236.

Safeguards noted, for Phase 2 to prove or refute:
- the tmp-file fallback (QP:1232-1234), which applies only if the tmp survives;
- a restart;
- a leader change;
- a sync after one failed attempt: without the stale SNAP, shutdown(false) would not clear, and the db stays initialized after loadDataBase threw, so the next attempt would skip the reload.

## Step 2: developer knowledge (code and tests only until the verdict, per adhoc Shared Rule 2)
- `Learner.java:921-922` comment: "If we haven't finished SNAP sync, force fully shutdown to avoid potential inconsistency". Clearing after an incomplete SNAP is deliberate. Whether it was meant to persist across attempts is not stated.
- `ZooKeeperServer.shutdown` javadoc: "true when no other server will use the same database to replace this one".
- `CurrentEpochWriteFailureTest` (ZOOKEEPER-4269 comment): names epoch write failure "either because of exception or power-off" as a failure to tolerate; covers only the tmp-survives restart.
- `EpochWriteFailureTest` (ZOOKEEPER-2307): existing fault pattern, a `writeLongToFile` override throwing IOException("Input/output error"), and its expected outcome for acceptedEpoch "keeps on trying to join the quorum".
- No existing test covers observers with a currentEpoch write failure.

## Step 3: known-status
Tracker search runs only after the verdict is settled (adhoc Shared Rule 2); see below.
Persistent-findings registry lookup was not run: the task's Do-NOT list forbids reading other findings, and the registry returns summaries of other records.

## Step 3 results (run after the reproduction verdict was settled; may set Novelty only)
Full queries and output: `novelty-search.log`. Date 2026-11-05.

Jira JQL (project=ZOOKEEPER):
- text ~ "is older than the last zxid"
- text ~ "current epoch" AND text ~ "observer"
- text ~ "syncMode"
- text ~ "SyncMode.SNAP"
- text ~ "setCurrentEpoch"
- text ~ "Unable to load database on disk"
- text ~ "fullyShutDown" OR "fully shutdown"
- summary ~ observer AND summary ~ snapshot (last 3 years)

GitHub PRs (repo:apache/zookeeper is:pr):
- "older than the last zxid"
- syncMode
- setSyncMode
- currentEpoch observer
- SNAP sync clear zkDb shutdown
- loadDataBase currentEpoch
- merged:>=2025-11-01 observer OR epoch OR snapshot OR learner

Git: log --grep and -S on Learner, QuorumPeer and ZooKeeperServer.

Closest reports, none with this mechanism:
- ZOOKEEPER-4283 (Open), ZOOKEEPER-1653, ZOOKEEPER-2354, ZOOKEEPER-2653: same guard, but a crash or disk mismatch followed by a failed process start. No observer, no stale syncMode, no retry loop. ZOOKEEPER-4283 overlaps only the restart symptom.
- ZOOKEEPER-3642 (commit efbd660e): introduced the clear on incomplete SNAP, for leader loss before NEWLEADER. It does not discuss a failed epoch write.
- ZOOKEEPER-5094 / PR #2459 (open): extends the clear to TRUNC at the same Learner.shutdown line; does not reset syncMode.
- ZOOKEEPER-2005: failed setCurrentEpoch on a leader.

Novelty result: NEW. The search did not change the verdict.
