# SOLR-39 v2 source and previous-run review

The selected check is Solr 8.11.4
`RoutedAliasUpdateProcessor.lookupShardLeadersOfCollections()` at line 246.
`processCommit` invokes it at line 201 before distributing the commit; a null
alias collection list throws `newAliasMustExistException` at line 247.

`DimensionalRoutedAliasUpdateProcessorTest.java:73` starts four Jetty servers.
Its `@Test testTimeCat` begins at line 94, creates a time and category routed
alias at lines 102-111, and calls inherited `addDocsAndCommit` at lines 119,
134, 171, 193, 219 and later. The helper at
`RoutedAliasUpdateProcessorTest.java:256-315` sends updates through the alias
or a constituent collection and either commits explicitly or waits for a
commit-within. It is source-valid for the selected check, but exact reach and
a passing JUnit still require a fresh trace. It inherits `@AwaitsFix`; the
seed sets `MALLORY_SOLR_AWAITSFIX=1` and retains the ConfigSet fixture flag
that made the Time test run.

Category v1 used the pinned seed `F0993D5343E20BA4` and applied no fault.
`CategoryRoutedAliasUpdateProcessorTest.java:194` submits one document;
`assertInvariants` at lines 410-439 checks the alias and constituent
collection document counts. Its log shows an `add=[1]` request and commit
requests but both constituent collection queries and alias query returned
zero hits. The test failed `Expected to find 1 docs but found 0` at line 438.
The exact target check occurred once on node1 with no throw. This is an
invalid healthy seed, not evidence of a target bug. Repeating the identical
randomized seed would duplicate the same randomized choices without proving
the race resolved. A different seed could be tried later if the dimensional
selector fails, but it cannot reuse Category v1 as a fault seed.

The original Category v1 case-local executable was named `run_category.py`.
The pinned Mallory JUnit classifier recognizes only `run_pilot.py` for Solr,
so the generated JUnit receipt was `not_applicable` despite a test result
marker in the log. The v2 executable uses the recognized basename. The
source and bytecode target remain the same.

`ZkStateReader.AliasesManager.process` reads `/aliases.json` at line 2312,
publishes a new `Aliases` reference via `setIfNewer` at lines 2314 and
2336-2343, and catches `ConnectionLossException` at lines 2315-2319. The
volatile cache is returned by `getAliases` (lines 2220-2224). The healthy
selector checks exact Java owner/reference/version identity and an event-time
graph witness; it does not infer causal reachability from timestamps alone.
