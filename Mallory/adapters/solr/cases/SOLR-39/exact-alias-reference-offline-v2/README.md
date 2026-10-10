# SOLR-39 sealed healthy reference audit

This package reexamines the **existing**, sealed node1 healthy trace. It starts no JVM, changes no Solr or Mallory runtime code, and performs no fault injection. The original diagnostic run used `TimeRoutedAliasUpdateProcessorTest#test` on a four-server MiniSolrCloudCluster and passed one JUnit test with zero failures or errors.

The previous `exact-alias-reference-node1-v1/audit_identity.py` paired no markers because it compared `Probe.captureContext()` with core event `context`. The former is a full region **occurrence**; the matching core field event stores it in `occurrence`. `audit_identity.py` joins only the matching occurrence, named actor, epoch, thread, exact field-access site and operation type, and requires the marker timestamp to precede that event. It verifies a one-to-one relationship between supplemental manager identity and the core's manager object token on each actor.

The immutable archive `data/mallory/evidence_archives/SOLR-39-aliasref-healthy-node1-v1.tar.gz` (SHA-256 `d84c06f6b10af3375c807aab723c3794c7ff66d2b58bfb177bf21ce1298106db`) yields 310 paired markers out of 310, no transform errors or manager identity collisions, and this qualified healthy path:

| Event | Trace sequence | Actor and meaning |
| --- | ---: | --- |
| Watcher door | 4593 | node2 `AliasesManager.process` calls `SolrZkClient.getData` at `ZkStateReader.java:2312` on task 273 |
| Cache publication | 4630 | same task/thread invokes `setIfNewer` and writes exact `Aliases` reference 14 (ZK version 1) into the volatile `aliases` field of manager 3 |
| Constructor read | 4849 | node2 request context 291 reads reference 14 from the same manager while constructing `RoutedAliasUpdateProcessor` |
| Target read | 4867 | same request reads reference 14 in `lookupShardLeadersOfCollections` |
| Target check | 4870 | exact selected branch at `RoutedAliasUpdateProcessor.java:246`, outcome `TAKEN` (the nonthrowing path) |

No later publication to that manager occurs between constructor read and target check. Thus this healthy run contains a source and exact-reference supported watcher→cache→request→target link, which the core graph alone had left as a sampled field-version candidate. This is a *healthy injection-site admission result*, not a fault result or a new bug. A subsequent fault pilot must match the typed door on its actual physical actor and show both injection and later target retention. If the watcher exception removes that target execution, the trial is abandoned for this check.

Run the archive audit and negative controls from the baseline root:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-offline-v2/run_offline.py
python3 -m unittest discover -s Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-offline-v2 -p 'test_*.py' -v
```

`run_offline.py` checks the archive and member SHA-256 values, the JUnit receipt, exact target count, marker count, and path count before writing `evidence-review.json`. Ten synthetic controls reject wrong occurrence, actor, request context, watcher task, alias reference, ZK version, event order, intervening publication, and manager identity collision.
