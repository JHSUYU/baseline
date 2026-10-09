# SOLR-31 watcher door correction

The existing `ForceLeaderTest#testReplicasInLowerTerms` workload reaches the exact `CollectionsHandler.forceLeaderElection` guard. Its private `doForceLeader` sends one client request and propagates `IOException`, so an exception at the observed client HTTP doors ends the test before that guard.

`sites-v14.json` declared a `ZkShardTerms#retryRegisterWatcher` door at source line 403. The call at line 403 is `zkClient.exists(znodePath, watcher, true)` inside `ZkShardTerms#registerWatcher`. `retryRegisterWatcher` calls that method and catches `KeeperException`, waits for reconnection, then retries. Because the original method name was wrong, the door was absent from the healthy site catalog and target closure.

`sites-v19.json` changes only the method name to `registerWatcher`; it retains line 403 and the typed `KeeperException$ConnectionLossException`. `config-v19-lane2-calibration.json` pins this site file and the same existing JUnit workload, target check, Solr source, adapter JAR, agent JAR, and fixed core release. It is calibration only until a healthy trace proves the exact door and observed path to the guard. A later strict fault pilot must separately show matched injection and post-fault target retention.

The active v18b campaign uses its original pinned site file and remains separate evidence.
