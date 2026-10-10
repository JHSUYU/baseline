# HDFS-33 map-window healthy probe

The selected check is `DataStorage.VolumeBuilder.build()` line 259,
`assert bpStorage != null`, in the existing one-DataNode
`TestDataNodeHotSwapVolumes#testAddOneNewVolume` test. The archived original
healthy run passed and reached both nonthrowing target branches, but its target
actor was `unknown`. The prior fresh v2 package has passing static and node2
preflight receipts; no v2 raw result was available in shared storage during
this review.

`DataStorage.prepareVolume` inserts the block-pool entry before it returns the
builder. `FsDatasetImpl.addVolume` subsequently calls `builder.build`. A
thrown preparation or dataset `IOException` aborts that call. The directory
check at `StorageLocation.makeBlockPoolDir` line 276 catches `IOException`,
but a failed check can leave the directory absent, causing the later block-pool
load to throw before the builder is returned. That door is diagnostic only.

The only source map removal is `DataNode.shutdownBlockPool` calling
`DataStorage.removeBlockPoolStorage`, through `BPOfferService.shutdownActor`
when the last BP actor stops. A generic `IOException` from
`BPServiceActor.sendHeartBeat` is caught and retried in `offerService`; it does
not itself shut down the actor. The special `RemoteException` classes that do
stop it require an RPC response type that the pinned injector cannot create.
Even with that response, the selected test has no demonstrated same-DataNode,
same-block-pool shutdown between map insertion and `builder.build`.

This package adds healthy-only method and sampled map events for
`DataStorage`, `BPServiceActor`, `BPOfferService`, and `FsDatasetImpl`. It
records the typed heartbeat call as another diagnostic door. The pinned agent
records `Map.get` and `Map.put`, but **does not record `Map.remove` or a map
read's returned value**. `audit_healthy.py` therefore reports method entry
for removal without claiming key-specific removal or fault retention. A named
target and an ordered map pair would narrow the gap, but cannot admit a fault
campaign by themselves.

On node0, `python3 -B preflight.py --static` checks hashes, config, source
markers, and healthy-only guards without Java. Once dispatch grants the node2
HDFS lane, dispatch may run `MALLORY_DISPATCH_ADMITTED=1 ./run_healthy.sh` there.
The runner locks the shared HDFS lane, checks pins, and performs one fault-free
JUnit. Then run `python3 -B audit_healthy.py <output>/trials/r0000` offline.
The 80/3600/max3 full campaign remains unadmitted until a typed, observed,
target-retaining path is established. This package has no fault plan.
