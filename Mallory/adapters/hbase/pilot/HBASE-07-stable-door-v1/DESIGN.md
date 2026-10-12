# HBASE-07 stable fault door

## Observed failure of the old pilot

The old plan addressed `RpcServer.call@447` by the server's global ordinal.
`rs1` ordinal 142/144 did not match in two trials; ordinal 143 matched in the
other trial after both selected `HBaseAdmin.restoreSnapshot` checks had already
run. The target therefore did not execute after that fault. The healthy source
trace used `rs2` for the meta reads while a second healthy run used `rs1`.
Server ordinal and meta-region placement are not stable replay identities.

## Candidate that can survive a single injected exception

`TestRestoreFlushSnapshotFromClient#testRestoreSnapshot` calls `restoreSnapshot`
twice. Each invocation calls `getTableNameBeforeRestoreSnapshot`, which invokes
`listSnapshots`. `listSnapshots` creates an anonymous `MasterCallable` whose
`rpcCall()` invokes `MasterKeepAliveConnection.getCompletedSnapshots` at
`HBaseAdmin.java:3019`. In the pinned HBase 2.6.6 distribution this is the
unique `HBaseAdmin$74#rpcCall()Ljava/util/List;` callsite. It executes on the
test client's thread inside the exact `restoreSnapshot` region. The first call
has the stable occurrence `client:0:...restoreSnapshot...:root:1` and site hit 1.

The source path wraps this call in `HBaseAdmin.executeCallable`, which uses
`RpcRetryingCallerImpl.callWithRetries`. That loop catches an `IOException`
and retries unless the cause is a `DoNotRetryIOException` or retries expire.
An `IOException` at the selected callsite can therefore allow a later retry to
reach the target check. This is a source-backed hypothesis, not an observed
target-retained fault. A bounded pilot must verify it.

The preflight joins each client `GetCompletedSnapshots` SEND to its exact
`master0` RECV and the server door by the transported correlation token. Across
the earlier healthy trace and the healthy plus three fault trials from the
failed pilot, both target invocations each had one unique request before the
check. The method-wide client request ranks were 1 and 2 in all five runs.
`preflight-result.json` preserves each trace SHA and the event sequences.

## Replay and admission

`candidate-site-rules.json` is an isolated configuration fragment. Merge its
explicit door and anonymous class include into a fresh, immutable case config.
Do not replace the existing target/region or RPC handoff rules. The generated
bytecode site must equal its `expected_site_after_instrumentation` value, and
the compiled class SHA must match the pinned distribution. For the first pilot,
match `site + client + epoch 0 + target-region occurrence + hit 1`. Omit global
door ordinal. The existing agent matcher supports occurrence and hit, but the
current automatic scheduler promotes `door_ordinal` whenever present, so an
automatic full campaign would need an opt-in selector for region-scoped doors
or an explicit stable plan queue. Never use an actor-wide or arbitrary RPC
ordinal as a substitute.

Before any injected run, require one passing JUnit healthy run with exact
nonthrowing `@2787` target, the new client door in the same region/thread before
the check, and a fresh event-time audit showing the door reaches the target.
Then run a small one-fault pilot. Require exact fault match/application, a
retry of `GetCompletedSnapshots`, and the same client target invocation after
the fault. Record an unmatched fault or target loss as a negative trial, not a
bug. Only then may dispatch consider a full fuzz budget.

An alternative method-qualified server door would need to carry a stable
client-region replay tag in the actual request header and select the exact
server call by that tag and RPC method. The client callsite above uses the
existing target-region occurrence and needs no new cross-process replay tag.

## Source and artifact pins

- HBase source commit: `d5f63f523c065f963992ea4e74db268d17816631`.
- `HBaseAdmin.java` SHA256: `2cfbe453b9ddbe6669c17d93b77f9a43ff9bd3bd2ab47ff9ad6f3b82ee5d06d0`.
- `RpcRetryingCallerImpl.java` SHA256: `83d85c0d92c140a84f62a8ae7a76144d459f23ee9d05f3873ee02e3d279465b2`.
- `hbase-client-2.6.6.jar` SHA256: `b3c9537a0c5f4b057134c59298b453ae207d2e6279be66d71c80da36d0d2de54`.
- `HBaseAdmin$74.class` entry SHA256: `34cab92eed3b7f547a9f791d0be468efa899812e4006be3b7b498fdbd0292d57`.
- Existing fa5f healthy result SHA256: `b295b2a92403b9c7bd3b9f5cdb59bc2c8a73885377b4b1ff8aadfb6cfc09f78a`.
- Existing fa5f healthy audit SHA256: `64cf20d4c6e98cbaa70afd3dafaf3577822c39327f084a71bf805f117e0637c1`.
