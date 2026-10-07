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

The prepared case-local ByteBuddy probe records target method entry/exit,
null tracker returns preceding the guard, the exact IOException, and relevant
ZooKeeper reads. `run.sh` launches the unmodified original JUnit with JaCoCo.
No JVM has been run for this mapping yet, so HBASE-27 remains `no_cluster_test`
with zero measured target hits or fault trials. HBASE-17's active campaign has
its own directory, data, ports, and checkpoint.
