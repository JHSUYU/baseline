# SOLR-10/39/40 actor V2 preparation

This is an **independent, calibrated but not-yet-fuzzed campaign** for the unchanged Solr 8.11.4
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
fully applied sequences that reach a specific guard after the final fault **on
the exact client, alias manager, runtime node and Jetty role of an applied
fault in that trial** contribute feedback for that check. A guard reached on
another registered client is recorded as `target_lost_actor_mismatch` and does
not count as effective or drive mutation. This limits the current campaign to
direct actor overlap; cross-node causal relevance requires a separate
source-supported relation. The exact target exception is a candidate
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
python3 .study-repairs/unit-test-pivot/cases/SOLR-10/actor-v2/probe/budget_smoke.py
```

The build compiles two byte-identical original JUnit test classes, case-local
production hooks and JaCoCo helpers. ASM verifies the compiled instruction
counts: six ZooKeeper methods, one client registration, one Jetty role binding,
and three exact guard hooks. The no-cluster smoke passes the same I/O and
callsite through two different client objects; only the selected actor consumes
two ordered fault ordinals. It also rejects a wrong alias manager at a guard.
The generated build and smoke receipts are `build-receipt.json` and
`evidence/offline-smoke/receipt.json`. The budget smoke checks independent
per-site effective counts, the last-eight boundary, rejection of a failed
injection, and the 720/1152-attempt and 8/10-fault transitions without
starting a cluster.

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
coarse trial results. `evidence/campaign/state.json` is authoritative, with a
separate checkpoint mirror for each check in `evidence/campaign/checkpoints/`.

The **base budget is 80 effective trials per check**, 720 shared attempts, and
at most 8 ordered faults. Effective means every fault in the plan matched and
applied in order on the selected actor, and that particular check ran after
the final fault. When a check reaches its 80th effective trial, the campaign
examines its **last eight effective trials**. If any added a covered production
method, increased a covered production branch count in a method, or exposed a
new stable actor/operation/I/O-resource family, that check's goal extends to
128 effective trials. If any check qualifies, the shared attempt cap becomes
1152 and the fault limit becomes 10. A check with no such signal stays at 80.
The per-check extension decision, recent eight trial receipts, effective count,
goal, and explicit stop reason are persisted after every trial. A check that
misses its effective goal because the shared attempt cap or queue is exhausted
remains under budget and is labeled accordingly. Each completed trial retains
trace, JUnit log, manifest, JaCoCo data and its trial receipt. Embedded-cluster
scratch is removed for non-candidates; exact target-exception candidates retain
their scratch for review. Probe novelty still guides queue
mutation, but probe novelty alone does not trigger the extension. JaCoCo's
per-method branch count is a conservative novelty signal: a higher count proves
additional branch coverage, while equal counts cannot distinguish different
branches. These are configured caps, not completed counts.

## Node2 healthy calibration, 2026-10-06

Four bounded healthy invocations ran in persistent tmux session
`solr103940_v2_calibrate` on node2, using clean source commit
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`. Node2 had 16 CPUs, about
59 GiB available memory, and about 15 GiB disk free at preflight; a separate
SOLR-36/37 JVM was running at the start. No fixed ports or shared scratch were
used. Both original JUnits passed in 23.14 and 22.78 seconds. Both actor V2
JUnits passed in 25.90 and 25.89 seconds with JaCoCo, four bound Jetty roles,
73 bound `/aliases.json` I/O events each, and exact guard counts of 4, 4, and
11 for SOLR-10, SOLR-39, and SOLR-40 respectively. Neither actor run emitted
a target exception. The original-class runs have no probe trace by design.
The original JUnit bytecode SHA-256 is
`288ade17cb538b6226d1a61b863569a2b7bace75a228e58d60f18d5d2fed5749`.
Raw run directories, logs, actor traces, JaCoCo data and SHA-256 receipts are
under `evidence/healthy-*`, `evidence/healthy-summary.json` and
`evidence/calibration-audit.json`.

SOLR-39's target was on `jetty:node4` in the first actor run and
`jetty:node1` in the second. The actor-relative seed queue has 655 plans
derived only from I/O on a healthy target's actual client/manager pair.
`smoke.py` also moves a guard to a different **registered** client while
leaving both faults intact; the ledger must reject that guard as an effective
target-after-fault. Logical `nodeN` alone does not prove cross-run semantic
actor identity. The fuzz campaign has **not been launched** and no actor V2
fault result or new bug is claimed here. It requires a separately allocated
node2 slot after the current priority work.
