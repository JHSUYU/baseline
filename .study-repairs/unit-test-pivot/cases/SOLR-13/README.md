# SOLR-13: routed alias creation visibility check

Selected Solr 8.11.4 check: `RoutedAlias.doSynchronous`,
`solr/core/src/java/org/apache/solr/cloud/api/collections/RoutedAlias.java:348-350`.
After `ensureCollection` and a ZooKeeper alias refresh, it throws if the
created collection is absent from the observed alias list. The mapped original
cluster test is `TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation`.

**Status: no usable healthy original cluster test yet.** The original test
class inherits `@AwaitsFix(SOLR-13696)` from
`RoutedAliasUpdateProcessorTest.java:64`. With the default test-group setting,
JUnit reported one test and zero failures but the listener recorded an
assumption failure: the method body did not run. These two nominally green
attempts took 2.27 and 2.12 seconds. They are not counted as healthy seeds or
as fault trials.

Enabling the existing `tests.awaitsfix` group left the original JUnit source
unchanged and started its four-node embedded cluster. This third attempt
failed after 7.937 seconds in the test's `createConfigSet` setup:
`ConfigSetsHandler` rejected an unauthenticated request to copy the trusted
`_default` base configset. The selected `RoutedAlias` check had not run. The
failure occurs before any injection, so it is not a new bug from this
experiment. The three run manifests and the assumption/failure logs are in
`independent/evidence/healthy-*`; `independent/build.json` records the
unmodified source hashes and released Solr JAR hash. The case-local healthy
runner uses the original JUnit class, the original four-node cluster setup,
and no GraphChecker runtime JAR.

No fault sequence was run or credited. The case can be reopened if an
unchanged original cluster JUnit that reaches this exact check is identified.
