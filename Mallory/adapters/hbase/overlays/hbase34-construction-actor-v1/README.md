# HBASE-34: bind token-key I/O during indexed server construction

The sealed v5 healthy JUnit passed (1/0/0) and reached the exact
`AuthenticationTokenSecretManager.retrievePassword@159` check on `rs0` at event
219. The selected ZooKeeper reads in `ZKSecretWatcher.start` occurred at events
2, 3, 7, and 8, before the target, but their node was `unknown`. The second
start's `addKey` at event 9 wrote object `o2`, key `1`, version `1`; the target
run read the same object, key, and version at event 218. This is a genuine
identity gap: the key-map relation is observed but the startup door lacks a
MiniCluster actor. The v5 result and trace digests are pinned in
`manifest.json`; `preflight.py` verifies their event identities.

HBase's `JVMClusterUtil.createRegionServerThread` and `createMasterThread`
receive an explicit cluster index before reflecting into the server
constructor. `HRegionServer` creates its ZooKeeper watcher and starts RPC/token
services inside that constructor. The existing adapter registers the server
only after the factory returns, which is too late for `ZKSecretWatcher.start`.
This overlay enters a `rsN` or `masterN` node scope around the exact indexed
factory, including its reflective constructor, and closes it on every return
and exception. It does not derive identity from thread names or hostnames.

`healthy-v6.json` adds only this actor scope to v5's unmodified cluster JUnit,
target, key-map sampling, and typed ZooKeeper doors. Offline tests verify the
two exact factory methods and balanced scopes; no cluster JUnit has been run
with v6 yet. Run one healthy trial on node1 only with dispatcher lane grant.
The full campaign remains on hold until the typed `rs0` door, same-map state
handoff, and exact `rs0` target form a valid event-time path. An injection that
loses the target is not a detected bug.
