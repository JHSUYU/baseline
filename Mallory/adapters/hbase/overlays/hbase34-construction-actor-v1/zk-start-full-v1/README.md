# HBASE-34 typed ZooKeeper start fault campaign

This package runs the unchanged `TestGenerateDelegationToken#testOnlyToken` cluster JUnit with the exact `AuthenticationTokenSecretManager.retrievePassword` guard at source line 159 and throw at 160. It reuses the v6 indexed-constructor actor overlay, so the region-server watcher start doors have actor `rs0` before the server constructor returns.

The sealed v6 healthy run passed JUnit 1/0/0. Its `rs0` watcher calls at lines 61 and 63 occurred before `allKeys` write `o2/key=1/version=1`, and a later read of that same sampled key version immediately preceded the exact target. The graph labels this state edge **candidate**, because the map version is sampled. The full campaign retains that evidence label.

Source review: `ZKSecretWatcher.start` declares `KeeperException`; `AuthenticationTokenSecretManager.start` catches it and logs without calling `watcher.abort`. A one-shot `ConnectionLossException` at either typed watcher call can therefore let startup continue with a missing key. `retrievePassword` later calls `refreshKeys()` before the final null guard, so neither target retention nor an `InvalidToken` is guaranteed by source alone.

`run_full_node1_v1a.sh` requires the dispatcher grant and an idle node1 HBase lane. Launch it with `bash run_full_node1_v1a.sh` or as an executable. It verifies the pinned legacy core manifest and every listed file SHA before starting. The generic release verifier requires a content-derived release directory name, which this older release does not have; the case-local verifier keeps its byte-integrity check.

The runner creates a fresh calibration-only r0000, verifies JUnit, exact `rs0` target, both typed pretarget watcher doors, the same object/key/version sampled state witness, and a queue containing only those two closure doors. Only then does it promote that checkpoint and run up to 80 fault trials, 3600 seconds, and 3 faults per sequence. Target-absent fault trials are recorded and not expanded. The terminal summary and offline audit require separate source review before any bug claim.
