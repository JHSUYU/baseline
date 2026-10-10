# SOLR-39 original-102 full campaign stage

Selected JUnit: `TimeRoutedAliasUpdateProcessorTest#test`. Selected guard: `RoutedAliasUpdateProcessor.lookupShardLeadersOfCollections@246`. TimeRoutedAliasUpdateProcessorTest.java:110-139,175-176 creates the alias, then commits and deletes through it. RoutedAliasUpdateProcessor.java:194-201 calls lookupShardLeadersOfCollections, whose line-246 null guard is the selected check.

The earlier calibration failed during ConfigSet creation before the target. The source provides a route to the guard, but a passing healthy run and named pretarget I/O have not yet been observed. This package stages a fresh healthy prerequisite; full mode refuses to run until that JUnit passes once, the exact guard is nonthrowing on a named actor, and an injectable pretarget I/O door is recorded.

The full campaign starts its own fresh healthy seed and then runs up to 80 fault trials, 3600 cumulative trial seconds, and three exception faults per trial. Healthy JUnit success, exact nonthrowing target, named actor, and named injectable pretarget I/O are admission conditions. Target retention after injection and graph path quality are reported outcomes; no event-time path is required to launch.

The case-local configs pin Solr source and compiled target hashes, the immutable numeric-thread agent, v38 Solr adapter, direct JUnit runner, real I/O site catalog, and frozen graph-order core. The node2 shell holds case and Solr source locks and checks disk and RAM floors. `admission-request.json` has `go=false`; dispatch GO receipts are absent. No JVM was launched while staging. Run `run_campaign.py --mode healthy --preflight-only` on node2, then dispatch may run `run_node2.sh healthy` and then `run_node2.sh full`.
