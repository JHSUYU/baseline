# SOLR-10/39/40 actor V2 preparation

This is an **independent, not-yet-run campaign** for the unchanged Solr 8.11.4
`TimeRoutedAliasUpdateProcessorTest.test`. It uses the existing clean source and
dependency jars in `../work`, but writes new traces and checkpoints only here.
The older `../work/evidence/campaign` is historical coarse-actor evidence and is
not an actor V2 seed or completion result. No checklist or case result is changed
by these scripts.

## Runtime identity contract

`ZkController` registers the actual `SolrZkClient` receiver, its
`ZkStateReader.aliasesManager` object, and runtime node name. The original
`MiniSolrCloudCluster` assigns `node1` through `node4` instance names; a
case-local hook maps each name to the corresponding live Jetty node name after
startup. Every intercepted `SolrZkClient` I/O records operation, exact path,
source callsite, stable `actor=jetty:nodeN`, runtime node, client object ID,
alias manager object ID, and thread. IDs are within-JVM diagnostics, not stable
cross-run identifiers or ZooKeeper session IDs. An unbound client gets
`actor=unbound` and cannot match a fault selector. The real receiver is passed
as `this`; no thread-name inference is used to assign actors.

Each selector has the form `OP|exact-path|ordinal|caller=Class#method:line|actor=jetty:nodeN`.
Mutation appends `@relative-ordinal|...|after=F0|seed_global=N`. Both global
and relative ordinals count **only the matching actor, callsite, operation and
path**. The selected three guards separately emit `SOLR-10`, `SOLR-39`, or
`SOLR-40`, with their actual client and alias manager identities. A guard
whose manager does not belong to the registered client fails closed. Only
fully applied sequences that reach a specific guard after the final fault
contribute feedback for that check. The exact target exception is a candidate
requiring replay and source review, not an automatically labeled new bug.

The selected guards are:

| Case | Production guard |
| --- | --- |
| SOLR-10 | `MaintainRoutedAliasCmd.call`: `ra == null` |
| SOLR-39 | `RoutedAliasUpdateProcessor.lookupShardLeadersOfCollections`: `collections == null` |
| SOLR-40 | `RoutedAliasUpdateProcessor.getAliasProps`: `aliasProperties.isEmpty()` |

## Preparation and later execution

Offline work already completed:

```sh
python3 .study-repairs/unit-test-pivot/cases/SOLR-10/actor-v2/probe/build.py
python3 .study-repairs/unit-test-pivot/cases/SOLR-10/actor-v2/probe/smoke.py
```

The build compiles two byte-identical original JUnit test classes, case-local
production hooks and JaCoCo helpers. ASM verifies the compiled instruction
counts: six ZooKeeper methods, one client registration, one Jetty role binding,
and three exact guard hooks. The no-cluster smoke passes the same I/O and
callsite through two different client objects; only the selected actor consumes
two ordered fault ordinals. It also rejects a wrong alias manager at a guard.
The generated build and smoke receipts are `build-receipt.json` and
`evidence/offline-smoke/receipt.json`.

When a cluster slot is available, run the following **sequentially**:

```sh
python3 .study-repairs/unit-test-pivot/cases/SOLR-10/actor-v2/probe/calibrate.py
python3 .study-repairs/unit-test-pivot/cases/SOLR-10/actor-v2/probe/campaign.py
```

`calibrate.py` runs two clean original JUnits and two actor-instrumented healthy
JUnits, each in its own scratch directory. It requires an unskipped pass,
all three exact guards, all four Jetty roles, and consistent client/manager
identities. The original test inherits `@AwaitsFix`; the runner enables it and
uses the `_default` configset compatibility property from the prior successful
run. `campaign.py` cannot initialize without the two verified actor-aware
healthy traces. It keeps a case-local durable `inflight` checkpoint so an
interrupted trial restarts from its own clean scratch; it never imports old
coarse trial results. The default cap is 240 attempts, 40 eligible trials per
check, and 10 ordered faults, with feedback from production JaCoCo probes and
stable per-actor I/O identities. These are caps, not completed counts.

The four healthy JUnit invocations and the campaign have **not been launched**;
no actor V2 fault outcome or new bug is claimed here. Stable Jetty instance
names identify the test harness's logical node slots; if a later replay needs
a more specific semantic role, its guard and I/O trace must demonstrate that
role in addition to `nodeN` before claiming exact semantic replay.
