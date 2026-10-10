# HBASE-32 target-absent discovery package

Pinned source: HBase 2.6.6, `d5f63f523c065f963992ea4e74db268d17816631`. This package uses the **unchanged** `TestRegionReplicaFailover#testSecondaryRegionKill` MiniCluster JUnit as its workload. Its setup starts three RegionServers and enables replica replication plus waiting for the primary flush. The test kills a secondary and verifies that it reopens and serves the rows. See `TestRegionReplicaFailover.java:61,75-88,202-235`.

The check is `RegionReplicaFlushHandler.triggerFlushInPrimaryRegion(HRegion)` at `RegionReplicaFlushHandler.java:130`; the throw is at line 136. The handler calls `RpcRetryingCaller.callWithRetries(FlushRegionCallable)` at lines 126-128. The check only runs if that call throws an `IOException`. The prior healthy run passed one JUnit, entered this function, reached zero exact checks, and ran zero fault trials (`data/mallory/calibration_v19/HBASE-32/result.json`, SHA-256 `a164b17c98f4098b40438393dccb3a256229984e362c949e5c17b7d67a9e21a7`). That is negative healthy evidence, **not** a reason to mark the case complete.

The explicit bootstrap door is `FlushRegionCallable.call(HBaseRpcController)` at source line 81, immediately before `AdminService.BlockingInterface.flushRegion` RPC. The bytecode was checked with `javap -p -c -l`; the pinned class SHA-256 is `39dfca972e451d1a35b44051a19b0ff1001036e00121aa26910b7d95742ce6a2`. The injected `DoNotRetryIOException` is an `IOException` and `RpcRetryingCallerImpl` fails fast on it, so one effective injection can reach the catch. Exact door identity is `...FlushRegionCallable#call(Lorg/apache/hadoop/hbase/ipc/HBaseRpcController;)Lorg/apache/hadoop/hbase/shaded/protobuf/generated/AdminProtos$FlushRegionResponse;@81:door:1`.

The case-local actor overlay enters `RegionReplicaFlushHandler.process()` with the MiniCluster RegionServer identity registered for its inherited `EventHandler.server`. This scope covers `triggerFlushInPrimaryRegion` and the synchronous `FlushRegionCallable.call` on that handler thread. It never guesses a node from the thread name. The general HBase adapter still registers `rsN` identities and handles RPC context. A fresh healthy trace must verify the overlay and an exact, named door; the static preflight cannot do so.

`config-healthy.json` runs a fresh fault-free calibration. If it passes, records an exact target-absent site catalog and observes a named bootstrap RPC door, `config-full.json` can run at most 80 fault trials, 3600 seconds, and three faults per trial. The first effective exception trial should enter @130; the controller only binds the target after exact postfault check observation with complete actor identity. Later trials use runtime coverage and observed I/O. The target exception is **not automatically a bug**: this source intentionally rethrows a non-`TableNotFoundException` flush failure when the table remains enabled. Any candidate needs replay and independent source/contract review.

Offline admission (does not launch Java):

```sh
python3 Mallory/adapters/hbase/cases/HBASE-32/target-discovery-v1/preflight.py
```

On an assigned, isolated lane, a controller can run a fresh healthy campaign, then the full campaign using **different** output directories:

```sh
python3 Mallory/adapters/hbase/cases/HBASE-32/target-discovery-v1/run_campaign.py --mode healthy --out /path/to/isolated/healthy
python3 Mallory/adapters/hbase/cases/HBASE-32/target-discovery-v1/run_campaign.py --mode full --out /path/to/isolated/full
```

No runtime attestation or fault trial has been performed for this package. The full run must not be counted as checked until its receipts show the exact target, effective injection, replay, elapsed time, and outcome.
