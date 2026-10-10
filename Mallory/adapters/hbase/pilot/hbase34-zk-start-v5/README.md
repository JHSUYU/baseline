# HBASE-34: pretarget token-key ZooKeeper I/O

The sealed v4 healthy trial passed `TestGenerateDelegationToken#testOnlyToken`
(1/0/0). It observed the exact `AuthenticationTokenSecretManager.retrievePassword`
check at line 159 on `rs0`, event 234. Its 28 configured
`RpcServer.call@447` doors were in separate RPC contexts and do not explain
the token-key lookup. The node1 v4 result and event stream are SHA-pinned in
`manifest.json`; this package does not modify them.

The pinned HBase 2.6.6 `ZKSecretWatcher.start` registers the watcher, then
calls `ZKUtil.watchAndCheckExists` at line 61 and, if present,
`ZKUtil.getChildDataAndWatchForNewChildren` at line 63. Both are typed
ZooKeeper I/O calls. Bytecode call signatures and line numbers are checked by
`preflight.py`. A `KeeperException` from either call exits to
`AuthenticationTokenSecretManager.start`, which logs it and returns without
calling `watcher.abort`. An `rs0` key-load failure could leave the key absent
until `retrievePassword` executes its refresh path, while preserving the
line-159 check. This is a source-backed hypothesis, not an observed fault
outcome.

`healthy-v5.json` runs the same unmodified cluster JUnit once, with only these
two explicit I/O doors. The existing token-manager overlay binds the exact
target receiver to its MiniCluster watcher. The v5 probe includes
`ZKSecretWatcher` and scopes its `start` method as a region; it also samples
`allKeys` map writes and reads by object and key identity. This can expose a
healthy-run state edge from key loading to the target check. Before any full campaign,
require an observed `rs0` typed door preceding the exact `rs0` target and a
source and event-time relation between the key read and target. A fault trial
must retain the target; a lost target is discarded. The full campaign remains
on hold. Node1 lane execution belongs to the dispatcher.
