# SOLR-37 reader and range telemetry, healthy only

`ShardSplitTest#test` reaches the selected `DistributedZkUpdateProcessor.doDefensiveChecks@994` guard. The archived HTTP forwarding pilot injected after the same request's guard; subsequent checks are in different requests. The previous `ZkStateReader.fetchCollectionState@1641` observation saw typed watcher I/O and later target checks, but did not identify the `ZkStateReader` or the range values that the guard consumed.

This isolated adapter preserves v46's HTTP and watcher handoffs. It adds a trace event at the exact source line 994 with the serving reader identity, collection, parent and child shard names, cached document identity, ZooKeeper version and range operands. The watcher callback logs before and after document identities and emits a `STATE_WRITE` only if the callback actually publishes a new collection object; the target emits a same-reader and same-collection `STATE_READ`. The typed `SolrZkClient.getData` call at `ZkStateReader.fetchCollectionState@1641` remains the only configured door. An interrupted refresh that does not publish a document does not emit a state write.

This package runs one fresh healthy trial only, after a case-local node0 dispatch GO. It does not admit fault trials from same-node ordering alone. Admission needs an observed same-reader, same-collection watcher publication to the exact target read, with the selected range values and a time-respecting graph path. A later fault trial would also have to prove that the fault changed the retained target operand. A failed refresh is a missing write; the current graph does not automatically encode that counterfactual edge.

Static preflight (no cluster JVM):

```
python3 Mallory/adapters/solr/cases/SOLR-37/operand-telemetry-v1/run_campaign.py --mode healthy --preflight-only
```

The package pins the clean Solr 8.11.4 source, compiled target and watcher class bytes, agent and adapter JARs, v46 direct JUnit runner, case catalog, and case-local runner. Runtime output is reserved under `data/mallory/solr37_operand_telemetry_healthy_v1_node0/SOLR-37/healthy`; no live trial has been run for this package.
