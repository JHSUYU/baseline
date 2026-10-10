# SOLR-40 staged full campaign

`TimeRoutedAliasUpdateProcessorTest#test` is an unchanged four-node SolrCloud
JUnit. Its `@Before` configures four nodes. The test creates a time-routed
alias and sends documents through that alias, reaching the update-processor
path in which the selected `RoutedAliasUpdateProcessor#getAliasProps@132`
check inspects cached alias properties. SOLR-13 uses the same test class and
cluster setup, but its selected `#testPreemptiveCreation` method and
`RoutedAlias.doSynchronous@348` check are different workloads and targets.

The case-local `sites.json` selects the exact
`ZkStateReader$AliasesManager.process@2312` `SolrZkClient.getData` call. A
typed `KeeperException.ConnectionLossException` from that call is caught in
the watcher callback. Existing SOLR-18 calibration observed this exact
compiled site. The selected SOLR-40 check performs no local I/O or retry;
the watcher runs asynchronously. No watcher-to-request causal edge has been
established. The graph/path result is recorded as an outcome of the campaign,
not used as a launch gate or treated as a bug claim.

`config-full-node2.json` stages a fresh healthy seed and then up to 80 fault
trials, 3600 cumulative trial seconds, and three faults per trial. The fresh
healthy run must pass exactly the selected JUnit, reach the selected check on
a named actor, and observe the exact watcher door before that check on a
named actor that also reaches the check. The campaign queues only this door,
using its physical node, epoch, and door ordinal. Across fresh cluster runs,
the routed update may move between physical nodes; missed fault matches and
paths are reported as outcomes. The prior SOLR-40 JUnit failed during
ConfigSet creation before this check. The full config retains Solr's
source-defined ConfigSet test flag and `MALLORY_SOLR_AWAITSFIX=1`; a fresh
healthy result for SOLR-40 remains pending.

The package reuses the SHA-pinned SOLR-13 case-local agent release and core
snapshot, plus the v38 Solr adapter and direct JUnit runner. The case-local
JUnit entry point preserves the same pinned agent in its runtime receipt.
It does not copy the core tree. Preflight checks every Python file in that snapshot, all
referenced runtime artifacts, the Solr source revision and source hashes, and
the compiled target and watcher class hashes. The node2 shell holds lane3 and
shared Solr source locks and enforces disk and RAM floors. A separate
`admission-full-node2.json` dispatch GO receipt must match the case, host,
config SHA, runner SHA, and output. `admission-request.json` has `go=false`;
no node2 JVM was launched for this package.

Node0 verification: Python compile, shell syntax, SHA preflight, and refusal
of a `go=false` receipt passed. The pinned agent SHA-256 is
`bee26189cf56dc3030ab0f7d5997c352f5998c9f65bf3b8da2de1f99bec3f89e`.
The config SHA-256 is
`07d389558670f86ef3a6b4be44befb763d078ed0ee9394e8bc0b25a68fa5624b`;
the runner SHA-256 is
`f1183dd33b7461d81d553d7edce173a5115dc4091a5851c47fb650f584b4b173`.
