# Solr ZooKeeper exact-version read-from observation

This change is an isolated, general extension of the original GraphChecker
REGION_STATE recording path. It does not change active campaign pins, replay a
cluster test, or claim a detected bug.

## Source semantics

The original `MessageDoors.fetched` treats a `getData` read inside a ZooKeeper
watch callback as a message receipt. A normal polling read returns immediately
when `NOTIFIED` is absent, because reading store data does not itself activate
the writer's causal context. This is a deliberate distinction in the original
`MessageDoors` contract, and the extension preserves it.

The Solr protocol patch calls `fetched("ZOOKEEPER", path + "@" +
stat.getMzxid(), this)` after successful `keeper.getData`. A successful
`keeper.setData` returns the committed `Stat`, so its modification transaction
ID is the exact version written. The Solr patch now calls
`storedVersionedValue` for that response. A successful `create` only returns a
path, and the existing patch obtains its `Stat` through a later `exists` call.
Another writer could update the path between those calls, so that `Stat` is
not proof of the create's version. The create continues to use the original
`stored` hook for watch activation, but is excluded from this value edge.
The path and version key identifies the exact version whose bytes `getData`
returned. A write outside the recording window, a writer not yet filed, or a
version that does not match the observed read cannot be attributed to an
observed producer.

## Implementation and limits

`MessageDoors.fetched` now writes a `STORE_VERSION_READ` trace row only when
the exact `(transport, path@mzxid)` has already been filed by the
`storedVersionedValue` API with a nonempty producer endpoint. It does not
wait for a writer in an ordinary polling read,
install inbound/symbolic context, create an `EXCHANGE_RECEIVE`, or add a
schedule event. The row carries the exact version key, producer endpoint ID,
physical source, and current call ID. This in-JVM lookup has possible false
negatives if a reader observes a version before its writer files it or if
writer and reader reside in separate JVMs; it makes no cross-process claim
without the producer metadata.

The graph summarizer joins that row to one and only one earlier
`EXCHANGE_SEND` with the same transport, version key, attempt, message half,
and producer endpoint ID. It emits a distinct
`ZOOKEEPER|READ_FROM|writer->reader` family only if both endpoints have exact
selected original Finalizer plan occurrences with matching physical sources
and temporal order. A matched observation outside selected regions is counted
but is not represented as a selected region edge. A duplicate or absent SEND,
different version, or read before SEND produces no edge.

`valueReadFromEdgeFamilies` and `newValueReadFromEdgeFamilies` are separate
from activation/watcher `edgeFamilies` and `closureEdgeFamilies`. A new value
family receives two novelty points once; a legacy healthy summary with no
value field gets no synthetic novelty. This can prioritize subsequent queued
fault sequences through graph-delta feedback. It does **not** enlarge
`closureOccurrenceIds`, change target backward closure membership, or make a
fault door eligible. That target-guidance limitation remains, including for
SOLR-19. The static 449 method-return ports alone do not establish a runtime
read-from edge or imply SOLR-09/SOLR-40 detection.

## Evidence and validation

The frozen SOLR-09 and SOLR-19 healthy `r0000` traces each contain zero
`STORE_VERSION_READ` rows because they predate this recorder extension; no
new value edge can be recovered from those traces retroactively. The Solr
source patch and original GraphChecker runtime implementation, rather than
those old traces, establish the version-key semantics above.

The targeted Java test records exactly one row for an exact returned version,
none for an unfiled version or an ordinary create-style `stored` version, and
confirms no `EXCHANGE_RECEIVE` was introduced.
Synthetic REGION_STATE tests verify exact version matching, a missing writer,
read-before-write ordering, unchanged activation edges and closure IDs,
delta novelty, and zero novelty against a legacy healthy summary. The
campaign test verifies first-seen value novelty and zero repeat novelty.

Validation commands in the isolated worktree:

```text
mvn -q -Dtest=MessageDoorsStoreReadTest test
mvn -q -DskipTests package dependency:build-classpath -Dmdep.outputFile=target/native-original-dependencies.txt
python3 -m unittest Mallory.native_graphchecker_feedback.test_region_state_graph Mallory.native_graphchecker_campaign.test_campaign
```

The two Maven commands passed. The Python command passed 63 tests.
