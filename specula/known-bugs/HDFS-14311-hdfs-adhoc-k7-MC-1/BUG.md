# HDFS-14311: detected by Specula (yes), finding MC-1

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `hdfs-adhoc-k7`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

`DataStorage.loadBlockPoolSliceStorage` uses one shared `BlockPoolSliceStorage` instance for all data dirs. For each dir it calls `bpStorage.recoverTransitionRead -> doTransition`, which `readProperties(sd)` into the shared fields (`layoutVersion`, `cTime`) and compares them with `DATANODE_LAYOUT_VERSION`/`nsInfo.cTime`; if an upgrade is needed, `doUpgrade` returns a callable that the buggy code submits **immediately** to the executor. That callable's `doUpgrade(...)` sets `this.layoutVersion = DATANODE_LAYOUT_VERSION` and `this.cTime = nsInfo.cTime` while the loop is already running `doTransition` for the next dir. If the write lands between the next dir's "regular startup" test and its "needs upgrade" test, neither branch is taken and `doTransition` falls through to `throw new IOException("Datanode state: LV = ... is newer than the namespace state ...")`; that dir is dropped for the block pool and the DN upgrade fails (JIRA: 2.7.3 -> 2.9.2 upgrade, LV -56 -> -57). The fix collects the callables and submits them after all dirs' transitions were analysed.

## What counted as detecting it (written before the run)

The target throw at line 422 fires for a second (or later) data dir during a block-pool upgrade with two or more dirs, because the upgrade task of an earlier dir concurrently overwrote the shared `layoutVersion`/`cTime` of the one `BlockPoolSliceStorage` instance between the checks; root cause = shared instance state + upgrade tasks submitted while later dirs are still being analysed. A real "DN newer than NN" storage is not this bug.

## What Specula found

**Specula's finding MC-1:** Startup parallel upgrade callable of one volume writes shared BlockPoolSliceStorage LV/cTime, tripping BPSS:422 IOException for a later volume

- **Cause:** DataStorage.loadBlockPoolSliceStorage submits volume i's upgrade callable (DS:463-464) before running volume i+1's doTransition on the startup thread; the callable writes this.layoutVersion (BPSS:510) and this.cTime (BPSS:513) of the single shared per-block-pool BlockPoolSliceStorage, which the later volume's doTransition re-reads at BPSS:405-416.
- **Trigger:** NameNode started with -upgrade (namespace cTime C0 -> C1); a DataNode with two data dirs at (DNLV, C0) restarts; volume 1's callable writes cTime=C1 after volume 2 evaluated BPSS:405-406 with C0 and before BPSS:415-416.
- **Consequence:** Volume 2 throws 'Datanode state ... is newer than the namespace state' at BPSS:422; DataStorage.loadBlockPoolSliceStorage (DS:467-469) drops it from the block pool storage, so the volume is not upgraded (no previous/ snapshot) while FsDatasetImpl still serves it; the upgrade is partial on that DataNode.
- **Premises:** Pinned base commit b0c5a8f9 predates the upstream HDFS-14311 fix (commit 4cb22cd8), so callables are still submitted inside the per-volume loop. dfs.datanode.parallel.volumes.load.threads.num defaults to the number of data dirs, so the callable runs concurrently with the next volume's doTransition. Reproduced at escalation Level 1: JDWP breakpoints only order threads (BPSS:409/510/518); no source change, no value or on-disk state injection.

**Operator's judgement:** yes. parallel upgrade callable overwrites shared BlockPoolSliceStorage LV/cTime; later volume fails BPSS:422

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_s1a_workload_shape.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-08: Invariant TargetSafe is violated.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 1h17m | 41.9M | $29.96 |

Time is active time; quota sleeps are excluded.
