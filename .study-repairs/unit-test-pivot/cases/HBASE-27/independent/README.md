# HBASE-27 original-JUnit mapping under review

The selected production check is `HRegionServer.blockAndCheckIfStopped` at
line 1052 (`if (this.stopped)`), which throws the line-1053 `IOException`
"Received the shutdown message while waiting." on its true branch. The
previous `TestRegionServerNoMaster` mapping starts its server before stopping
the master, so it does not establish the startup wait/stop race.

The unchanged original `org.apache.hadoop.hbase.TestClusterBootOrder`
`testBootRegionServerFirst` is a stronger workload. It starts a RegionServer
four seconds before starting a Master in a `LocalHBaseCluster` backed by
MiniDFS and MiniZooKeeper. Production `initializeZooKeeper` then waits in
`blockAndCheckIfStopped(masterAddressTracker)` for the master znode. A null
return from `ZKNodeTracker.blockUntilAvailable` immediately evaluates the
selected `stopped` guard; JaCoCo line/branch coverage can corroborate this.
The `nodeCreated` callback's `ZKUtil.getDataAndWatch` for that znode is the
candidate observed I/O boundary for a later `KeeperException` fault. Whether
such a fault reaches the true branch and leaves the target meaningfully alive
still requires a separate runtime test and source review.

The case-local ByteBuddy probe records target method entry/exit, null tracker
returns preceding the guard, the exact IOException, and relevant ZooKeeper
reads. The `ZKWatcher` role (`REGIONSERVER` or `MASTER`) is part of the stable
I/O selector, so two callbacks on `/hbase/master` in the same event thread are
distinct. `run.sh` launches the unmodified original JUnit with JaCoCo. It
uses no GraphChecker JAR, skeleton, or prewoven class.

| Run | JUnit | Guard evaluations | Target throw | Wall time |
| --- | --- | ---: | ---: | ---: |
| `boot-first-healthy` | 1/1 passed | 2 false | 0 | 46.45 s |
| `boot-first-healthy2` (role-aware selector) | 1/1 passed | 2 false | 0 | 50.60 s |

The second healthy trace observes both
`ZK_RESPONSE~MASTER~/hbase/master~ZKNodeTracker.nodeCreated~1` and
`ZK_RESPONSE~REGIONSERVER~/hbase/master~ZKNodeTracker.nodeCreated~1`,
with no original I/O error. A small pilot injects a
`KeeperException.ConnectionLossException` on the latter successful response
only. Its raw log records `FAULT_MATCHED` and `FAULT_APPLIED` for that exact
selector; the RS then logs `ABORTING` and `STOPPED`, and the waiting RS's next
null tracker return logs `stoppedSnapshot=true` and the exact selected
`IOException("Received the shutdown message while waiting.")`.

Production source makes this a direct response to the injected fault:
`ZKNodeTracker.nodeCreated` catches `KeeperException` at lines 198–207 and
calls `abortable.abort`; `HRegionServer.abort` calls `stop` (line 2871), which
sets `stopped=true` (line 2602); `blockAndCheckIfStopped` then throws at line
1053. The original test starts only one RS. Once it is aborted, the master
logs that no server is available to place its unassigned region, so an
original-JUnit timeout would reflect the fault removing the sole RS, not a
demonstrated coordination bug. The pilot's final JUnit outcome and a clean
replay are pending. This check is currently `running`, not a high-quality
negative or a confirmed new bug.

HBASE-17's active campaign has its own directory, data, ports, and checkpoint.
