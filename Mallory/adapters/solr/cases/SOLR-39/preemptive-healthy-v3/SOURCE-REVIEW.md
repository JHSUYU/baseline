# SOLR-39 v3 source and no-fault evidence

The exact target is `RoutedAliasUpdateProcessor.lookupShardLeadersOfCollections()`
at the `collections == null` branch on line 246; line 247 throws when the alias
is absent. `processCommit` calls this method at line 201. A useful workload
therefore needs an alias-routed commit after alias metadata has changed.

Two unchanged four-server JUnit seeds are already invalid and remain sealed:

* Category `test` v1 reached the exact branch once but failed its no-fault
  document-count assertion (`Expected to find 1 docs but found 0`). Its
  reference audit found no watcher-publication-to-target candidate path.
  Archive SHA-256: `e1cbf2105bd1ca7ea4189cb41115037a87b0bae18c9f9a24fc7f4d556e17c297`.
* Dimensional `testTimeCat` v2 failed on its first ADD before any exact branch
  check (`String cannot be cast to Date`). Its `newDoc` supplies
  `instant.toString()` for `timestamp_dt` (test lines 707-713), while
  `DimensionalRoutedAlias.findCandidateGivenValue` calls
  `TimeRoutedAlias.formattedRouteValues`, which casts that field to `Date`
  (source lines 172 and 205-210 respectively). The ordinary time router
  separately accepts `CharSequence` in `parseRouteKey` (lines 430-441).
  This mismatch exists before any injected fault; a randomized seed or the
  existing fixture flags cannot change the Java value's type. Archive
  SHA-256: `b3b7a2e521600df69fe9d482abae218f16e5dee21befdfee4f612e21d2772b70`.

The v3 selection is the existing, unchanged
`TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation`. Its `@Before`
starts four Jetty servers (line 89). The test creates two time-routed aliases
with preemptive collection creation (lines 284-302), then performs concurrent
updates on both aliases (lines 309-344) and further alias property changes
and explicit commits (lines 407-483). `addOneDocSynchCreation` itself adds a
document and explicitly commits each alias (lines 588-596). Those operations
can produce more than one alias-reference generation and routed commit in
the same test, making a later watcher-publication-to-commit path plausible.
The same class's simpler `test` has already passed under the pinned Solr
JUnit harness and reached the exact branch; this supports the class/harness
mapping, not admission of the new method.

This test has timing-sensitive assertions and is annotated `@Slow` in a
`@BadApple` class. It is a candidate for **one healthy-only run**, not a
validated seed. Admission requires an unchanged passing JUnit, exact @246
checks, paired exact `Aliases` object/owner/version telemetry, and an
event-time graph witness for a later watcher door into the target. If the
no-fault test fails or the strict path is absent, no fault campaign is
authorized by this package. The alternative `testSliceRouting` has one
explicit alias commit (lines 235-253) but has a much weaker source basis for
a *later* watcher generation before another routed commit.
