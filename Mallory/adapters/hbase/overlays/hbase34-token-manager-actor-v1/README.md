# HBASE-34: bind the token manager's actual RegionServer

The sealed HBASE-34 v3 healthy trial passed the unchanged
`TestGenerateDelegationToken#testOnlyToken` JUnit (`1/0/0`) and observed the
exact `AuthenticationTokenSecretManager.retrievePassword` check at source
line 159. Event `234` was on `RS-EventLoopGroup-3-11` with `node=unknown`, so
the controller correctly stopped at `healthy_node_identity_missing`. The
v3 checkpoint, result, and compressed event stream are pinned in
`manifest.json`. This package leaves that evidence untouched.

`RpcServer.createSecretManager` passes its server's **same ZKWatcher object**
to the token manager. The manager stores a `ZKSecretWatcher`, whose inherited
`ZKListener.watcher` is that object. The existing MiniCluster adapter
registers each server's ZKWatcher under its indexed actor (`masterN` or
`rsN`). This overlay scopes only the exact `retrievePassword` receiver to
the already registered watcher identity. If any part of that object chain is
missing, the event remains `unknown`. The scope closes on normal and
exceptional exits; it does not infer an actor from the thread name.

`healthy-v4.json` is a **future-only, one-run calibration**, with the original
cluster JUnit, target sites, and HBase jars. It loads the immutable actor
overlay after the existing HBase adapter. Run the read-only preflight with
`python3 preflight.py`. Maven offline unit tests validate the hook's object
identity behavior and balanced bytecode scope without running the cluster
JUnit. The node1 lane owner may stage this package and run a healthy trial
when that lane is free.

The observed v3 `RpcServer.call@447` doors are not enough to admit a full
campaign. The target occurred in token authentication before the relevant
`RpcServer.call`; the v3 target had root context and no proven door-to-target
edge. After v4, require an exact named target actor **and** a relevant
pretarget physical I/O door with a replayable path. A ZK key read or watcher
handoff may be a suitable door only if a fresh trace proves it. Until then,
the full campaign stays on hold. This overlay changes attribution only; it
does not claim a bug or causality from temporal order.
