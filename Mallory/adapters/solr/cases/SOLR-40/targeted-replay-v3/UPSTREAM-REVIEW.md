# SOLR-40 source and issue comparison

In Solr 8.11.4, `ZkStateReader.AliasesManager.process` reads `/aliases.json`
with `this` as the new watcher and then calls `setIfNewer`. Its
`ConnectionLossException` catch only logs the failure
(`solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java:2302-2315`).
If the read fails, neither the local alias reference nor this watch is updated
by that callback. `RoutedAliasUpdateProcessor.getAliasProps` reads the local
properties and throws immediately when the map is empty
(`solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java:129-134`).
The directed Mallory trace observes precisely this path on one manager object.

The related [SOLR-12256](https://issues.apache.org/jira/browse/SOLR-12256)
describes stale ZooKeeper reads in `AliasesManager.update()`. Its
[patch](https://issues.apache.org/jira/secure/attachment/12920072/SOLR-12256.patch)
adds `update()` before `SetAliasPropCmd` checks alias existence and adds
`sync()` inside `update()`. It does not change the watcher callback's
connection-loss catch or `RoutedAliasUpdateProcessor.getAliasProps`.
[SOLR-12258](https://issues.apache.org/jira/browse/SOLR-12258) adds retry when
V2 dispatch cannot resolve a collection or alias. Here dispatch reached an
underlying core and the routed-alias update processor rejected its stale
properties. [SOLR-13059](https://issues.apache.org/jira/browse/SOLR-13059)
tracks a test failure reporting `no core retrieved`, a different stack.

These source differences support a distinct failure path, but they do not
prove an unreported upstream bug. The injected exception represents one
final-visible ZooKeeper read failure, not a full network disconnect and
reconnection. A real fault and a fix comparison would be needed to establish
the operational scope and upstream novelty.
