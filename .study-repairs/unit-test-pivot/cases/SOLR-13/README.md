# SOLR-13: routed alias creation visibility check

Selected Solr 8.11.4 check: `RoutedAlias.doSynchronous`,
`solr/core/src/java/org/apache/solr/cloud/api/collections/RoutedAlias.java:348-350`.
After `ensureCollection` and a ZooKeeper alias refresh, it throws if the
created collection is absent from the observed alias list. The mapped original
cluster test is `TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation`.

**Status: running graph-free fault campaign.** The original test
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

The failure was test environment setup: `ConfigSetsHandler.java:80,483-486`
supports the compatibility JVM property
`-Dsolr.disableConfigSetsCreateAuthChecks=true`. With that property and
`-Dtests.awaitsfix=true`, the unchanged original four-node JUnit passes
(`ran=1, ignored=0, failures=0`). Its uninstrumented calibration took
39.447 seconds; the case-local ASM + JaCoCo healthy run took 45.22 seconds.
The instrumentation observed **five exact evaluations** of the selected
`List.contains` guard in `RoutedAlias.doSynchronous`, all on its nonthrowing
branch, and no selected exception. A second healthy run reproduced all five
alias/collection identities and 30 exact target-context ZooKeeper I/O
identities. The case-local ASM agent instruments original bytecode at runtime;
it does not change the original JUnit or production source. No GraphChecker
runtime JAR appears on the classpath.

The campaign runs in node0 tmux `solr13_fuzz`. Its atomic checkpoint and
progress are `independent/fuzz/evidence/campaign/state.json` and
`progress.json`. Its budget is 80 strict, same-alias, postfault target-retaining
trials with at most eight injected I/O exceptions per sequence. Recent
coverage or I/O novelty at trial 80 extends this to 128 trials and ten
exceptions. JaCoCo production probes and exact operation, call site, logical
alias/collection, ZooKeeper path and hit ordinal guide mutation. Every JVM
attempt, including unmatched and target-lost attempts, is recorded. A target
exception is a candidate that requires replay and source review before any
new-bug claim. Completed raw traces are checksum-verified and compressed to
bound node0 disk usage.

## Independent Overseer alias-write campaign

The case-local `independent/stage2` agent adds runtime observations at
`MaintainRoutedAliasCmd.remoteInvoke`, `MaintainRoutedAliasCmd.call`, and
`addCollectionToAlias`. It tags the actual `AliasesManager` ZooKeeper
`setData("/aliases.json")` operation with the alias name and newly created
collection carried across the Overseer queue. Two original, instrumented
four-node JUnit healthy runs passed; each produced five selected guards and
the same five exact alias-write identities before those guards. For each
identity, the trace orders RPC send, Overseer receive, alias-write context,
native ZooKeeper write, and the selected guard. The original JUnit and Solr
source are unchanged. This phase has its own agent, JaCoCo probe set,
checkpoint and 80-effective/max-eight budget, independent of stage one.

It runs on node1 in tmux `solr13_stage2`, using only the SOLR-13 case path on
that node. The atomic state and progress are in
`independent/stage2/evidence/campaign/`. A trial counts only when the exact
planned I/O identity applies, the Overseer handoff is correlated at runtime,
and the same alias/collection reaches the guard after the final fault. The
first trial injected at `AliasesManager.applyModificationAndExportToZk`'s
native `/aliases.json` write; the same source reached the guard afterwards,
the original JUnit passed, and production JaCoCo gained 12 probes. It is an
effective trial, with no selected exception and no new-bug claim. Both
campaigns preserve each JVM attempt and compress completed traces after
decompressed-SHA256 verification.
