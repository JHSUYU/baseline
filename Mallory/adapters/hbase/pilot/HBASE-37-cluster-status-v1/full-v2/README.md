# HBASE-37 full-v2 admission

This package runs the unchanged `TestRSStatusPage#testStatusPage` LocalHBaseCluster test. The selected check is `MasterAddressTracker.getMasterInfoPort(ZKWatcher)` at source line 205; the selected throw is line 206. The only configured fault door is `ZKUtil.getData` at line 343 with `KeeperException.NoNodeException`.

The sealed node1 healthy-v2 run passed JUnit 1/0/0. Its named `master0` door event 205 precedes target check event 206 in the same epoch, occurrence, and thread. `stage-manifest.json` pins its collection receipt and all package files. `preflight.py` verifies those pins without starting a JVM.

`run_full_node1.sh` requires dispatch's `MALLORY_HBASE37_NODE1_GRANT=full-v2`, node1, free disk and memory, and exclusive HBase lane locks. The runner first executes a fresh `r0000` with the frozen controller's `--calibration-only` option. `healthy_gate.py` verifies a new exact typed door/check pair, a named target, JUnit 1/0/0, closure membership, and a local timeline witness. Only then does it promote the controller checkpoint and resume fault trials. A failed gate leaves the checkpoint in calibration mode with zero fault trials.

The budget is 80 fault trials or 3600 seconds, at most three faults per trial. Trial and campaign results remain under `data/mallory/cases/HBASE-37/campaigns/cluster-status-nonode-v2-full` and can resume after a controller interruption. `verify_terminal.py` accepts only a natural budget or queue terminal after at least one fault trial.

`ZKUtil` catches `NoNodeException` and returns null, which can intentionally trigger the selected `IOException`. `ActiveMasterManager` catches that exception and returns port `0`. A reproduced target throw is a candidate observation; source and user-visible invariant review are still required to call it a new product bug.
