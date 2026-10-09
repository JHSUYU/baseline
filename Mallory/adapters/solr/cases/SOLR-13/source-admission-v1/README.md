# SOLR-13 source and JUnit admission

This directory stages **one healthy-only** run of an unchanged Solr 8.11.4
JUnit. It has not run and makes no exception or bug claim. The source checkout
is pinned to `e27f44e3d78dfcec230c97e0a1240e3751daeff9`; `manifest.json`
binds source, bytecode, test, config, sites, and runner inputs by SHA-256.
`python3 preflight.py` checks them without starting a JVM.

## Selected operation and check

`TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation` starts a four-node
`MiniSolrCloudCluster` in its `@Before` method (line 89). The existing test
creates two time-routed aliases and calls `addOneDocSynchCreation` for each
(lines 284-302); that helper indexes into future buckets and waits for the
collections and aliases (lines 588-608). The test source SHA-256 is
`727cc38dd0fd0d42e641724b08d96b00e0e9d8ab492d23cbc572284824079d37`.

The selected target is `RoutedAlias#doSynchronous(...)@348:branch:1`, with
the line-350 `SolrException` if the refreshed alias list omits the requested
collection. `doSynchronous` first calls `ensureCollection` at line 344,
refreshes parsed aliases at line 346, and reads the alias list at line 347.
The target source SHA-256 is
`f422a5ef312e2e52f375cdbea30b711514cfdce35025bdc0af361144a1774a79`;
the compiled `RoutedAlias.class` SHA-256 is
`d24b8af0ab3596fcdf5cec0af47b963b9c35cafe0c12a3b19e04caa1a9751332`.

## Typed retry candidate

`RoutedAlias.ensureCollection` synchronously sends `MAINTAINROUTEDALIAS` to
the Overseer, then calls `aliasesManager.update()` before its caller checks
the alias list (`RoutedAlias.java:389-409`). The Overseer command calls
`MaintainRoutedAliasCmd.addCollectionToAlias` at line 173. That invokes
`ZkStateReader$AliasesManager.applyModificationAndExportToZk`, whose
`SolrZkClient.setData` at line 2259 can throw the typed
`KeeperException.BadVersionException`. The catch at line 2262 refreshes
aliases with `update()` at line 2270 and loops for another write attempt.
If one version failure is followed by a successful retry, this operation can
still return to the line-348 check with an updated alias list. The compiled
`AliasesManager.class` SHA-256 is
`11316fa5cf00d33d779e5ae96fbb04048e9a61070fb827641395589b84e2e8ad`.
`javap` confirms the `setData` invocation and exact `BadVersionException`
catch range in this bytecode. This is a source candidate, not an admitted
fault site: the fresh trace must establish which Overseer operation reaches
the selected request and that the exact door occurs before its check.

The older v10 healthy JUnit failed while creating a ConfigSet, before the
target: its log reports Solr's unauthenticated trusted-base ConfigSet guard.
The staged config sets the source-defined
`-Dsolr.disableConfigSetsCreateAuthChecks=true` test setup flag and uses the
pinned v38 Solr JUnit runner, adapter, and thread-ID-capable agent. A passing
JUnit and target hit remain unverified. This flag addresses test setup only;
it does not establish target reachability or a fault effect.

## Fresh admission gate

`healthy-node2-lane3.json` enables strict event-time paths, rejects coarse
roots, and disables automatic promotion. `run_node2_lane3_healthy.sh` checks
the node2 host, config SHA, fresh output, both lane and source locks, a
7.125 GiB disk reserve, 8 GiB available RAM, and runtime hashes before one
calibration trial. Dispatch must grant a fresh Solr lane/resource gate before
that shell is run.

The fresh trial must pass the unchanged JUnit, hit the exact line-348 check
on a registered actor with the pinned class and loader, and observe the exact
line-2259 typed door on a named Overseer actor. An observed request/reply or
task-token chain and a unique event-time graph path must connect that door
to the selected target occurrence. Equality of alias names, a global door
count, a later door, or a merely plausible source path does not establish
that cross-actor link. If the JUnit still stops in setup or the graph path is
absent, record the corresponding gap. No fault or full campaign is admitted
by this healthy selector alone.
