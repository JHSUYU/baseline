# SOLR-40 node0 healthy-only successor audit

Static audit only; no Solr JVM or fault was launched. The unchanged cluster
JUnit is `TimeRoutedAliasUpdateProcessorTest#test` (`configureCluster(4)` at
line 89; alias creation and add/commit at lines 132-139). Its Solr 8.11.4
source revision is `e27f44e3d78dfcec230c97e0a1240e3751daeff9` and source
SHA-256 is
`727cc38dd0fd0d42e641724b08d96b00e0e9d8ab492d23cbc572284824079d37`.
The passing SOLR-10 v23 run is a same-selector JUnit fixture (1/1); its
selected target is different and it does not establish a SOLR-40 door or
check hit.

The selected SOLR-40 check is
`RoutedAliasUpdateProcessor.getAliasProps@132:branch:1`, with the line-133
throw. The target source SHA-256 is
`6ed4337435f68d00ba85d7b05eeb324cea9a14298c34cabd137756d682f24590`;
compiled class SHA-256 is
`a146513b1cf3bdd7a724fd83ba203021b02348f92adc0d6784c3fa86b286baf0`.
The typed pretarget candidate is
`ZkStateReader$AliasesManager.process@2312:door:1`, a
`SolrZkClient.getData` call that can throw
`KeeperException.ConnectionLossException`. The watcher catches that exact
type at lines 2317-2319 and returns. On a successful read, it calls
`setIfNewer` at line 2314, which writes the volatile alias cache at line
2342; `getAliases` reads the cache at line 2223 before the target checks it.
The watcher source SHA-256 is
`83e14eadfcc4896ff05f9ac77706fdb683e0c181caeee21802f8861f68ac373d`;
compiled `AliasesManager.class` SHA-256 is
`11316fa5cf00d33d779e5ae96fbb04048e9a61070fb827641395589b84e2e8ad`.
The pinned package records the target branch at bytecode offset 28 and throw
at 35, and watcher `getData` invoke at offset 45.

`healthy-watcher-handoff-v1/run_healthy.py --preflight-only` passed on node0:
source and class hashes, site catalog, agent, adapter, case-local core,
runtime closure, passing same-selector fixture, and healthy-only config were
verified. Its config SHA-256 is
`122b0fddb64a6d20d52bfb70f005efde25f3b6e9dd56250d2863b61176697e8c`.
The package is still host-bound to **node2** in config, GO receipt check,
output path, and lane lock; that successful static preflight is not node0
runtime admission. The package requires 7,650,410,496 free bytes and 8 GiB
available RAM. Node0 had about 6.97 billion free bytes during this audit,
below its disk floor, while ZK11 owned the node0 runtime lane.

The source offers a target-retaining possibility: the watcher handles
connection loss without throwing through a routed update request. The
watcher callback and request normally have distinct occurrences. The
committed `SOLR-40/full-v1/run_campaign.py` analyzer admits only a watcher
door in the **same node, epoch, thread, and occurrence** as the target check.
That local rule is unlikely to establish this cross-context handoff. The
healthy audit separately records observed graph paths and sampled cache
write/read handoffs, but sampled versions or same-node timing alone are
candidate evidence. There is no fresh SOLR-40 healthy trace showing an exact
typed door, named physical target, and observed watcher-to-request causal
path. No full campaign is admitted.

**Dispatch gate:** SOLR-40 is a better source-level healthy successor than
SOLR-14's propagating direct door, subject to a node0-specific healthy-only
package and fresh output after ZK11. Recheck disk and locks, pin the exact
host-specific config/runner/closure, and run its no-JVM preflight before any
GO. A later full request requires a passed fresh JUnit, exact named target,
exact typed pretarget watcher door, and an observed watcher-to-request
handoff (or a valid same-occurrence proof); if only sampled state or time
order is present, retain the source handoff gap.
