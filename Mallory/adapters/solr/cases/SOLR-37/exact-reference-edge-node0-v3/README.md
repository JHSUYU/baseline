# SOLR-37 exact reference edge, healthy diagnostic

The previous healthy run passed `ShardSplitTest#test` and reached the exact
`DistributedZkUpdateProcessor.doDefensiveChecks@994` guard 180 times. Its 90
watcher-to-target state links were **candidate** edges: `Probe.stateWrite` and
`stateRead` used a sampled counter, and the hook read the reader's current
collection after `constructState` returned. Concurrent watcher updates could
therefore make that snapshot belong to a different publication.

This isolated v3 agent adds `stateWriteExact` / `stateReadExact`. A read event is
emitted only when its actual Java reference equals the last instrumented
publication for the same owner and key. The adapter captures:

1. The `ClusterState` reference at `ZkStateReader.constructState`'s actual
   `clusterState` field assignment, while a collection watcher is active.
2. The same reference returned by `ZkController.getClusterState` to a
   `DistributedZkUpdateProcessor`.
3. The processor's actual `clusterState` field assignment.
4. The same processor field reference at the exact @994 guard.

All relevant `clusterState` assignments in the pinned processor class are
instrumented. The core graph already pairs unique, exact state versions; its
event-time reachability rejects reversed edges. `audit_exact_path.py` admits
only a named watcher I/O door whose path contains both exact reference state
edges and reaches the named target. Object identity remains within the single
MiniCluster JVM; it is not inferred from a printed hash or matching range
values. A different publication reference, reader, processor, actor, or
sampled version cannot pass the audit.

The package runs **one healthy trial only**, with a fresh output root and a
node0 steward GO receipt. No fault campaign is admitted until its new trace
passes `audit_exact_path.py` and the target guard remains nonthrowing. The
previous v2 trace remains candidate-only; no old result is promoted.

Offline checks:

```
cd Mallory/adapters/solr/cases/SOLR-37/exact-reference-edge-node0-v3
python3 -m unittest -q test_audit_exact_path.py
python3 run_campaign.py --mode healthy --preflight-only
```
