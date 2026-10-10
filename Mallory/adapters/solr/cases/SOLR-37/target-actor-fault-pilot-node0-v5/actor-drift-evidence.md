# SOLR-37 v4 actor drift and v5 correction

The sealed v3 healthy run had 188 exact @994 target checks on `shard-4`.
The sealed v4 healthy run had 160 exact @994 checks on `shard-2`, while its
manual qualified door admitted only `shard-4` and emitted 18 such doors there.
The absence of v4 strict witnesses follows from this actor mismatch. It does
not invalidate the two observed exact-reference state edges in v3. The v3
automatic @1641 doors lacked a resource field, so a v3 witness alone did not
establish that a specific door used `collection1`'s state file.

One v4 source-backed path supplies that missing resource evidence for the
actual target actor. In `r0000/events.jsonl.gz`, automatic watcher door
`SOLR-37-r0000:7795` is on `shard-2`, epoch 0, within the official
`ZkStateReader$StateWatcher.refreshAndWatch` occurrence. The same watcher
callback's `junit.log` diagnostic at line 8625 records `collection1`, reader
`7fa5280a`, and `/collections/collection1/state.json`; its after diagnostic
at line 8641 records the same reader and state version 12. The selected door
is before the `getData(collectionPath, watcher, stat, true)` call at
`ZkStateReader.java:1641`. `refreshAndWatch` then invokes
`constructState(Collections.singleton(coll))` at line 1387.

The graph path is:

```
door :7795 (shard-2 watcher, collection1 state.json)
  → exact publication :7813 (reader object o3, version 23)
  → exact read :7958 (same o3, version 23)
  → processor assignment :7963 (object o437, version 3)
  → exact guard read :7965 (same o437, version 3)
  → @994 target check :7966 (shard-2)
```

Both `:7813→:7958` and `:7963→:7965` are **observed** state edges in the
pinned Mallory graph, not value-equality guesses or candidate edges. The
target diagnostic at `junit.log:8781` records the same reader
`7fa5280a`, `collection1`, document version 12, child range
`80000000-bfffffff`, and parent range `80000000-ffffffff`. The diagnostic
reader ID is corroboration; the observed state edges use the exact Java
references captured by `Probe.stateWriteExact/stateReadExact`. The latest
instrumented publication for reader o3 before door `:7795` was version 21
at `:7680`; the callback later published versions 22 and 23.

V5 keeps the v4 registered-reader, exact current ClusterState reference,
official watcher occurrence, and exact resource checks. It emits qualified
doors on any named shard actor, then admits only doors with an observed
two-edge path to @994 on the actual target actor of that healthy run. A fault
sequence remains on that actor. After injection, the exact target must run
later on the same actor; otherwise the trial is recorded as target lost and
is not expanded. Literal occurrence IDs contain per-run callback tokens, so
the replay plan matches the stable door ordinal and structural watcher
occurrence while receipts compare the actual dynamic occurrence within each
run.
