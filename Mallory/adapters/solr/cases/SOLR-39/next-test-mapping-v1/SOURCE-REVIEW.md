# SOLR-39 workload and causal-door review

## Selected target

Pinned Solr 8.11.4 `RoutedAliasUpdateProcessor.java:243-249` reads a cached
`Aliases` object and checks whether the current routed-alias name maps to a
collection list. The exact branch is `lookupShardLeadersOfCollections@246`,
and the corresponding `newAliasMustExistException` throw is at line 247.
`processCommit` and `processDelete` call this method at lines 193-203. The
method performs no I/O before the check.

## Existing cluster JUnit candidates

| Selector | Source evidence | Assessment |
| --- | --- | --- |
| `CategoryRoutedAliasUpdateProcessorTest#test` | `@Before` starts four servers at line 70; `@Test` begins at 166; creates a category-routed alias at 186-189; `addDocsAndCommit(true, ...)` at 194 and 205. | First healthy seed. Fewer collections and operations than the dimensional test, but two update phases and several alias changes. |
| `DimensionalRoutedAliasUpdateProcessorTest#testTimeCat` | `@Before` starts four servers at 73; `@Test` begins at 94; creates a time+category alias at 102-111; calls `addDocsAndCommit` repeatedly at 119, 134, 171 and later. | Source-valid backup, with more update opportunities but larger and slower fixture. |

The shared helper `RoutedAliasUpdateProcessorTest.java:256-315` sends documents
through the alias, sometimes in threads, then either explicitly commits or
waits for commit-within. Thus source alone does not guarantee a particular
number of exact checks in one randomized run. The inherited `@AwaitsFix` at
the base class line 64 requires `tests.awaitsfix=true`; the existing runner's
`MALLORY_SOLR_AWAITSFIX=1` provides it. The old ConfigSet setup failure is
addressed by the same pinned `solr.disableConfigSetsCreateAuthChecks=true`
fixture used by the passing Time selector. Neither alternate has a new
healthy trace yet, so target and door admission remain empirical.

## Prior Time-test evidence

The sealed v3 receipt
`data/mallory/evidence_archives/SOLR-39-exact-alias-reference-fault-node1-v3.receipt.json`
reports one exact applied `ConnectionLossException` at node2's first watcher
door, passing JUnit, and zero postfault target checks on the bound actor. The
sealed v4 receipt
`data/mallory/evidence_archives/SOLR-39-exact-alias-reference-node1-v4.receipt.json`
reports one exact applied fault at node1's second watcher door, passing JUnit,
zero postfault target checks on node1, and three global checks elsewhere.
The v4 healthy event-time graph has no door-to-target path; temporal order and
the shared alias reference do not qualify it as an in-closure trial.

## Candidate source path and admission

`ZkStateReader.AliasesManager.process` reads `ALIASES` at line 2312, where
`ALIASES` is `/aliases.json` (line 119). On success it publishes a new
`Aliases` reference via `setIfNewer` at lines 2314 and 2336-2343. The field
is volatile (line 2220), and `getAliases` returns it (2222-2224). The target
reads that cache via `getAliases` and the alias list. The watcher catches
`ConnectionLossException` at lines 2315-2319, so a late failed refresh may
leave a previous valid alias reference available to a later request. This is
a source-backed possibility, not a fault-time target guarantee.

The healthy candidate selector in `select_late_watcher.py` requires an earlier
same-manager, same-actor nonthrowing target check using an older exact
`Aliases` reference; then a typed watcher door, a newer publication, paired
constructor/target reads of that same Java reference and version, and an
event-time graph witness from door to check. It emits no fault plan if any
condition fails. A future fault plan must additionally bind the runtime actor,
epoch, door occurrence/ordinal, and `/aliases.json` resource before injection;
after injection it must revalidate the target and manager identity. The
selector does not treat v4's postpublication door as causal.
