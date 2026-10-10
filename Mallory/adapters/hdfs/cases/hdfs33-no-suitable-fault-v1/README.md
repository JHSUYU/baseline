# HDFS-33: no suitable fault model and existing test

**Verdict:** hold the 80/3600/max3 full campaign. This verdict is scoped to
Hadoop 3.4.3 commit `9d50c6884666e794e45102260a4017bb31802e1b`,
the existing HDFS cluster JUnits reviewed below, and Mallory's pinned
exception injector. It does not claim the assertion is unreachable.

## What the healthy runs establish

The archived fresh v2 `TestDataNodeHotSwapVolumes#testAddOneNewVolume` run
passed Surefire 1/0/0 and reached the exact nonthrowing line-259 assertion
twice on `hdfs-cluster-1/dn0`. Its independent offline causal audit found no
healthy observed-path door in the target closure. The copied node2 map-window
healthy probe also passed 1/0/0 and reached two named targets, with one
same-key `bpStorageMap` put/read pair (sequences 11/77) and no removal
method event. Four diagnostic door events precede the target; three have
`dn0` identity and one is `unknown`, and none is in the target closure. Its
twelve copied files match the node2 remote SHA-256 index.

## Exact missing causal edge

`DataStorage.prepareVolume` (lines 325–346) inserts the block-pool map entry
through `getBlockPoolSliceStorage` (1409–1417), then loads the block-pool
directory and returns the builder. `FsDatasetImpl.addVolume` (507–562) calls
`builder.build` only after preparation and temporary volume-map construction
have succeeded. Any `IOException` in those operations aborts that builder or
is rethrown before the selected assertion. The earlier
`StorageLocation.makeBlockPoolDir` directory-check exception is caught, but a
missing block-pool directory fails the later load before `build`.

The only `bpStorageMap.remove` is `DataStorage.removeBlockPoolStorage`
(1421–1423). It is called by `DataNode.shutdownBlockPool` (2147–2165) after
dataset block-pool shutdown, when `BPOfferService.shutdownActor` (467–481)
removes the last actor. A fault would need to make that lifecycle removal
occur for the *same DataNode, DataStorage object, and block-pool ID* after the
builder's namespace list is captured and before its line-258 map read, while
the volume worker still reaches `build`. Neither healthy run observes this
removal. The pinned agent records map get/put, but not map remove or the get
return value; a future fault trial would need additional key-specific
evidence and a retained exact target event.

`BPServiceActor.offerService` (703, 772–789) catches and retries a generic
heartbeat `IOException`. It stops the actor only for `RemoteException` whose
remote class is `UnregisteredNodeException`, `DisallowedDatanodeException`,
or `IncorrectVersionException`. Mallory's pinned `Probe.exceptionFor`
constructs exceptions using a one-string or no-argument constructor, whereas
Hadoop `RemoteException` requires `(className, message)`. Thus the currently
available heartbeat exception fault does not produce this shutdown. An
initial-handshake `IOException` can end an actor only on the non-retry path;
the selected hot-swap test starts its DataNode before adding a volume, and an
initialization failure does not establish a retained builder check.
An unchecked `RuntimeException` from `offerService` is caught by the
per-iteration `BPServiceActor.run` handler and retried. An injected `Error`
would reach its outer `catch (Throwable)` and cleanup, but it is outside the
typed I/O exception model and still has no observed retained builder window
in an existing test.

`BlockPoolManager.refreshNamenodes` (149–173) catches address-discovery
`IOException`, then throws if the address map is absent, before
`doRefreshNamenodes` can stop old services. Its later `toRemove` path
(236–253) and `BPOfferService.refreshNNList` (145–172) stop actors because
of an explicit changed nameservice/NN list, not a typed I/O fault in the
selected test.

## Existing test review

| Test | Relevant behavior | Missing condition |
| --- | --- | --- |
| `TestDataNodeHotSwapVolumes#testAddOneNewVolume` | Real one-DN hot add; exact target reached in fresh healthy. | No namespace refresh or last-actor stop before target. |
| `#testAddVolumesConcurrently` and `#testAddVolumesToFederationNN` | Real hot adds, including parallel workers or two namespaces. | Neither schedules a block-pool actor removal. |
| `TestRefreshNamenodes#testRefreshNamenodes` and `#testRefreshNameNodeDeadLock` | Real DataNode actor refresh. | No hot-add builder during removal. |
| `TestDeleteBlockPool#testDeleteBlockPool` and `#testDfsAdminDeleteBlockPool` | Real federated namespace removal and block-pool deletion. | No hot-add builder during removal. |
| `TestBlockPoolManager#testFederationRefresh` | Nameservice refresh with mocked offer services. | No real `DataStorage` or target. |
| `TestFsDatasetImpl` add-volume methods | Mock `DataStorage.prepareVolume` returns a bare `VolumeBuilder`. | Its block-pool directory map is empty, so the selected assertion loop has no entry. |

No reviewed existing cluster JUnit combines a real, retained builder with
same-block-pool actor removal in the required window. A new specialized RPC
fault and concurrent test would be a separate experimental design, requiring
healthy event-time path evidence and a new pinned injector. The present
healthy results do not authorize a fault trial or full campaign.

Run `python3 -B verify_receipt.py` for the source and archived-v2 hashes. It
starts no JVM and does not touch the checklist or live releases.
