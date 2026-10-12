# HBASE-27 static102 candidate review

Verdict for completed candidate trials 3, 4, and 9: `rejected_expected_shutdown_after_injection`. The current campaign remains active. The review covers exactly these three candidates; any later candidate needs a separate review.

The original JUnit `TestClusterBootOrder.testBootRegionServerFirst` starts one RegionServer before one Master and waits for initialization (`/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6/hbase-server/src/test/java/org/apache/hadoop/hbase/TestClusterBootOrder.java:103`). Its healthy run exits 0, reaches `HRegionServer.blockAndCheckIfStopped` twice, and records no target throw (`node1:/users/ZhenyuLi/static-rerun/results/HBASE-27/healthy/manifest.json`).

The target is the explicit check in `HRegionServer.java:1051-1053`: while a znode is unavailable, `if (this.stopped)` throws `IOException("Received the shutdown message while waiting.")`. `HRegionServer.stop` writes `this.stopped = true` at line 2602. `HMaster` inherits this lifecycle behavior; its active-master startup catches failures and aborts at `HMaster.java:2514-2525`. The source paths are in `/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6/hbase-server/src/main/java/org/apache/hadoop/hbase/`.

| Trial | Applied fault | Master failure / stop in JUnit log | RegionServer stop / target throw in JUnit log |
| --- | --- | --- | --- |
| 3 | `tryMigrateMetaLocationsFromZooKeeper#u8`, `ResultScanner.next()` | lines 672-697 | lines 721-725 |
| 4 | `#u8` and `#u38`, `ResultScanner.next()` and `close()` | lines 669-704 | lines 728-732 |
| 9 | `#u30`, `ResultScanner.close()` | lines 667-692 | lines 716-720 |

Each row refers to `node1:/users/ZhenyuLi/static-rerun/results/HBASE-27/campaign/HBASE-27/trials/000N-*/attempt-01/trace/junit.log`; the corresponding `result.json` records strict application, target reach after the fault, two target fatal exceptions, and exit 1. The logs show `CrashFuzz injected` in `HMaster.tryMigrateMetaLocationsFromZooKeeper`, followed by `Failed to become active master`, `ABORTING`, and `STOPPED`. The RegionServer then logs `STOPPED: Shutdown requested` and the exact target exception. The fault precedes the target throws in each runtime trace. The target's own source says to throw when stopped; the observed stop write explains its outcome.

An earlier independent original-JUnit run and a fresh clean replay of a RegionServer ZooKeeper `ConnectionLossException` reached this same target with `stopped=true`, after `ZKNodeTracker` aborted that RegionServer. Its bounded evidence and source review are in `crashfuzz/cases/HBASE-27/independent/README.md` and `hbase27-source-review.md`. That replay confirms the local stop-to-throw mechanism; it is a different fault selector from trials 3/4/9. The current three runs independently reproduce the master-startup failure sequence. This review does not claim that every possible fault point or recovery behavior was tested.
