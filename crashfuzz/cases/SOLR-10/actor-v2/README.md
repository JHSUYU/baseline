# SOLR-10/39/40 actor-aware campaign

This is an **independent, active actor-aware campaign** for the unchanged Solr 8.11.4
`TimeRoutedAliasUpdateProcessorTest.test`. It uses the existing clean source and
dependency jars in `../work`, but writes new traces and checkpoints only here.
The older `../work/evidence/campaign` is historical coarse-actor evidence and is
not an actor V2 seed or completion result. No checklist or case result is changed
by these scripts.

The authoritative current checkpoint is `evidence/campaign-v4/state.json` on node2,
in isolated tmux. The earlier five-trial actor V3 pilot remains in
`evidence/campaign/` and is excluded from the V4 effective count. Its physical
Jetty-role selector missed a moving Overseer writer four times. The V4 hook
uses the real bound `SolrZkClient` that performs `SET_DATA /aliases.json` as a
stable logical `alias-writer` selector, while recording its actual physical
Jetty node, client and `AliasesManager` identity on every event. Source-backed
cross-node relevance additionally requires the exact alias key in the
proposed `/aliases.json` write payload; no write success is inferred from a
pre-write exception. A target on another node with a different alias key is
ineligible. The V4 build receipt hashes the clean source commit, source files,
unchanged JUnit bytecode and actor-hook production bytecode.

## Runtime identity contract

`ZkController` registers the actual `SolrZkClient` receiver, its
`ZkStateReader.aliasesManager` object, and runtime node name. The original
`MiniSolrCloudCluster` assigns `node1` through `node4` instance names; a
case-local hook maps each name to the corresponding live Jetty node name after
startup. Every intercepted `SolrZkClient` I/O records operation, exact path,
source callsite, physical `jetty:nodeN` role, runtime node, client object ID,
alias manager object ID, and thread. IDs are within-JVM diagnostics, not stable
cross-run identifiers or ZooKeeper session IDs. An unbound client gets
`actor=unbound` and cannot match a fault selector. The real receiver is passed
as `this`; no thread-name inference is used to assign actors.

Each selector has the form `OP|exact-path|ordinal|caller=Class#method:line|actor=jetty:nodeN`.
The exact alias writer uses `actor=alias-writer` because Overseer leadership
can move among the four Jetty nodes between fresh runs. Its receipt still
names and verifies the physical node and live client/manager pair.
Mutation appends `@relative-ordinal|...|after=F0|seed_global=N`. Both global
and relative ordinals count **only the matching actor, callsite, operation and
path**. The selected three guards separately emit `SOLR-10`, `SOLR-39`, or
`SOLR-40`, with their actual client and alias manager identities. A guard
whose manager does not belong to the registered client fails closed. Only
fully applied sequences that reach a specific guard after the final fault **on
the exact client, alias manager, runtime node and Jetty role of an applied
fault in that trial**, or after an alias-writer fault carrying that precise
alias key, contribute feedback for that check. A guard with no verified
runtime relation is recorded as `target_lost_runtime_relation` and does not
count as effective or drive mutation. The exact target exception is a candidate
requiring replay and source review, not an automatically labeled new bug.

The selected guards are:

| Case | Production guard |
| --- | --- |
| SOLR-10 | `MaintainRoutedAliasCmd.call`: `ra == null` |
| SOLR-39 | `RoutedAliasUpdateProcessor.lookupShardLeadersOfCollections`: `collections == null` |
| SOLR-40 | `RoutedAliasUpdateProcessor.getAliasProps`: `aliasProperties.isEmpty()` |

## Build and execution

Offline work already completed:

```sh
python3 crashfuzz/cases/SOLR-10/actor-v2/probe/build.py
python3 crashfuzz/cases/SOLR-10/actor-v2/probe/smoke.py
python3 crashfuzz/cases/SOLR-10/actor-v2/probe/budget_smoke.py
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

The fresh V4 healthy seeds and the V4 checkpoint use these commands. Start the
campaign in tmux so it survives terminal disconnects:

```sh
python3 crashfuzz/cases/SOLR-10/actor-v2/probe/calibrate.py
python3 crashfuzz/cases/SOLR-10/actor-v2/probe/campaign.py --max-new-trials 5
python3 crashfuzz/cases/SOLR-10/actor-v2/probe/campaign.py
```

`calibrate.py` runs two clean original JUnits and two actor-instrumented healthy
JUnits, each in its own scratch directory. It requires an unskipped pass,
all three exact guards, all four Jetty roles, and consistent client/manager
identities. The original test inherits `@AwaitsFix`; the runner enables it and
uses the `_default` configset compatibility property from the prior successful
run. `campaign.py` cannot initialize without the two verified actor-aware
healthy traces. It keeps a case-local durable `inflight` checkpoint so an
interrupted trial restarts from its own clean scratch; it never imports old
coarse trial results. `evidence/campaign-v4/state.json` is authoritative, with a
separate checkpoint mirror for each check in `evidence/campaign-v4/checkpoints/`.

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

## Current V4 evidence, 2026-10-07

V4 was rebuilt on node2 from clean Solr source commit
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`. The unchanged original JUnit
class SHA-256 is `288ade17cb538b6226d1a61b863569a2b7bace75a228e58d60f18d5d2fed5749`;
the V4 actor hook class SHA-256 is
`8146a455d16ca8c3702e7180d388fb60a9a428ae0c49045b876e54ca529c8947`.
Both original healthy JUnits passed in 22.984 and 22.731 seconds, and both
current-instrumented healthy JUnits passed in 25.939 and 25.884 seconds. All
three target guards ran without a target exception. The four raw runs and their
SHA receipts are under `evidence/healthy-*-v4-*` and
`evidence/healthy-summary-v4.json`; the prior V3 seeds are not used.

The first V4 pilot stopped after five completed trials at a durable boundary.
Four fault sequences matched and applied all selected faults. One sequence
reached SOLR-10 through the same live client/manager after the fault and
SOLR-40 through the exact `myalias` shared-znode payload relation. SOLR-39
did not receive an effective trial in these five attempts. There were no
selected target exceptions. Independent recomputation from the five raw traces
reported zero ledger discrepancies in `evidence/campaign-v4/audit.json`; summed
trial time was 97.832 seconds. The subsequent scheduler migration preserves
all five trials and periodically selects single-fault `/aliases.json` watch
reads that precede SOLR-39 on the same healthy reader. Its source and checkpoint
SHA are recorded in `evidence/campaign-v4/scheduler-migration.json`. The full
V4 result remains in progress and the effective counts must be read from the
checkpoint, not from this pilot paragraph.

After 17 V4 trials, a second checkpoint migration added at most two extra
fresh runs of each strict alias-watch read that was followed by SOLR-39 on a
different reader. These repeats sample nondeterministic request placement;
the other-reader checks remain ineligible for the effective count. The
migration receipt records the exact prior checkpoint SHA and trial numbers in
`evidence/campaign-v4/reader-retry-migration.json`. At the 32-trial boundary,
raw auditing found 23 strict injections and effective counts of 5, 1, and 5
for SOLR-10, SOLR-39, and SOLR-40, with zero audit discrepancies. A SOLR-40
target-exception candidate was independently reproduced in three of ten
fresh exact-plan replays; see `CANDIDATE-SOLR-40.md` and the per-run receipts.
The full budget continues from that checkpoint in isolated node2 tmux session
`solr103940_v4_full`.

## V5 scheduling within the same V4 campaign

At the completed trial-102 checkpoint, SOLR-39 had only four effective trials.
The audited V4 queue still contained 183 untested single-fault roots whose
healthy trace connected their I/O to SOLR-39. The scheduler now spends every
other round on one of those roots, starting with `LazyCollectionRef#get`
collection-state watch reads; intervening rounds retain the existing
coverage-guided mutation queue. This is a queue-selection change only: the
original JUnit, production hook bytecode, runtime identity gate, fault model,
per-check goals, and already completed plans are unchanged.

The in-flight trial 102 was rerun from its clean scratch after restarting
tmux, completed once in the ledger, and then the migration wrote a new atomic
checkpoint. `evidence/campaign-v4/root-balance-migration.json` records the old
and new scheduler source SHA-256, checkpoint SHA-256 before and after, and the
102 completed/seen plans. The first priority root, trial 104, was strictly
injected and had a verified healthy-trace link to SOLR-39/40, but its live
post-fault check reached only SOLR-10; it therefore does not count for
SOLR-39/40. Its selector, actual target relation, original JUnit/hook hashes,
and raw trace SHA-256 are in `root-balance-first-trial.json` beside the
migration receipt. In the next four priority-root rounds through trial 110,
two reached SOLR-39 on the same live client and alias manager. The full
campaign continues in `solr103940_v4_full`; the latest effective counts are
in the checkpoint and the synchronized per-check result records.

A bounded V6 scheduling pilot tested whether healthy same-reader I/O near
SOLR-10 could improve its effective yield. It gave one in four rounds to an
untested SOLR-10 root, while retaining the SOLR-39 even-round preference and
multi-fault mutation. The four priority roots in trials 133, 137, 141, and
145 all selected an Overseer leader read on a physical Jetty node that did
not perform that read in the fresh run. None applied a fault, so none counted
as effective. The other trial types added three effective trials per check
over trials 130–145. At the completed trial-145 boundary, the scheduler was
returned to V5 without changing the original JUnit, actor hook, completed
trials, or seen plans. The V6 source, its first-trial role-drift audit,
V5-to-V6 migration hashes, and V6-to-V5 reversion hashes are retained as
`evidence/campaign-v4/{scheduler-v6.py,target-root-first-trial.json,target-root-migration.json,target-root-reversion.json}`.
The active source is again the SHA-256 `749089fd1b442d27c72dd721567ccdd492d89ebae3a370b8a1cf8664f77f3582`
V5 scheduler. This pilot shows that a close healthy I/O-to-guard distance alone
cannot replace live actor matching when the Overseer role moves.

## Historical node2 healthy calibration, 2026-10-06

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
actor identity. At the time of this historical calibration, the fuzz campaign
had not been launched. The current V4 campaign and its results are described
above and recorded in its separate checkpoint.

## V8 bounded same-reader retry, 2026-10-07

The V7 scheduler added 52 distinct healthy-trace `LazyCollectionRef#get`
`/state.json` occurrence selectors on the SOLR-39 target's physical Jetty
client. At the complete node1 trial-328 boundary, 30 such selectors had
already produced a strictly injected fault followed by the same-reader
SOLR-39 check. Another 17 most recent attempts had no exact injection, and
34 had an exact injection but the target check did not reappear on that
reader. V8 retains the original queue and completed/seen ledger, appends
only those 34 selectors, and permits at most two extra exact-selector runs
per root. It stops retrying a root as soon as the same-reader target appears;
unmatched injections do not enter the retry set. Fresh untested healthy roots
retain priority over retries. All fault and target gates remain unchanged.

The pause gate finished trial 328 and intercepted unstarted trial 329.
`evidence/campaign-v4/node1-handoff-calibration/pause-applied-v8.json`
records the complete boundary and state SHA. The V8 migration receipt at
`evidence/campaign-v4/lazy-retry-migration-v8.json` verifies the 877-plan
queue prefix and all 328 completed/seen plans were preserved. Source SHA-256
changed from `15b4a3a5d6351163b15bd10aa9184edc059ca86efee545a134642661cc933a68`
to `a3cb548fec2807323df258dbd1f649162ec177d86c44738aa91048decb5a6b8e`;
the original runner SHA-256 remains
`7a1850ff1233aac53114cd340d2795bb9d8ba28e491534a759a64850b871e15d`.
The two-trial V8 pilot ended at trial 330 with an atomic checkpoint. Trial
329 did not inject its entire two-fault plan. Trial 330 injected its one
fault exactly but did not reach SOLR-39 on that reader; its selector was
queued for one final bounded retry. Neither pilot trial counted as effective.
The full continuation runs in node1 tmux `solr103940_v8_full` and stops at
each check's effective budget or a recorded queue/attempt limit. The
per-check result records and 104-row checklist report current counts.

## V9 existing healthy calibration roots, 2026-10-07

The node1 migration gate had already run the unchanged original JUnit once
without faults using the same Solr 8.11.4 source, test class, build, and
actor hook as V8. Its actor trace was not among the two V7 seed traces.
Rechecking every I/O occurrence against a later SOLR-39 target on the same
live client and alias manager found 33 untried `LazyCollectionRef#get`
`/state.json` selectors. V9 adds only these healthy-observed single-fault
roots and their verified target-site metadata. It preserves the prior queue
prefix, all completed trials, seen-plan ledger, budget, original JUnit,
fault hook, runtime identity gate, and target oracle. The existing V8 bounded
retry rule remains active for these roots.

The V8 full run finished trial 419 before a temporary gate intercepted the
unstarted trial 420. The V9 receipt
`evidence/campaign-v4/handoff-healthy-roots-v9.json` records state SHA-256
`8bccc72886d1599b0c8b8ad27e3ca20fa6fb69e1e52580e98770f7dc876fa6f3`
before and `217b584e80385859d1611900e2bf5bf54cf462db69f2ae00ffdac89cb4787bcd`
after migration, the unchanged completed/seen ledger SHA-256
`63ea3b353d29df35202d3f065d44b0713600c9ad557c6a8e6881a6b7514bafa3`,
and queue length 928 to 961 with its first 928 entries preserved. Its
healthy source trace SHA-256 is
`fa1bed9b41c35457d8a2e7afdddc6ae91284d8fc6525423ab8e2dae25635c9c0`.
Each new root includes the source I/O and later target sequence numbers and
the matching live actor identity. The separate two-trial pilot audit at
`evidence/campaign-v4/node1-handoff-calibration/v9-pilot-audit.json`
recomputed strict injection and target gates from raw traces. Both faults
injected exactly, neither took a target exception, and the full continuation
runs from trial 421 in node1 tmux `solr103940_v9_full`.

## Final actor V2 campaign, 2026-10-07

V10b completed **757 shared original-JUnit fault trials** on node1. It kept
the V9 queue and completed ledger, alternating target-linked healthy roots
with the existing fault-sequence queue and ranking roots by observed
coverage/target yield. The selected test class, actor hook, target oracle,
and `probe/run.py` remained byte-identical. The campaign stopped naturally
with `inflight=null` when all three check-specific goals were met:

| Check | Exact target guard | Strict same-reader effective / goal | Target exceptions | Time to goal |
| --- | --- | ---: | ---: | ---: |
| SOLR-10 | `MaintainRoutedAliasCmd.call:116` | 128 / 128 | 0 | 22,836.556 s |
| SOLR-39 | `RoutedAliasUpdateProcessor.lookupShardLeadersOfCollections:246` | 87 / 80 | 0 | 15,182.720 s |
| SOLR-40 | `RoutedAliasUpdateProcessor.getAliasProps:132` | 154 / 128 | 5 strict reproductions of one candidate | 15,182.720 s |

The overall campaign had 481 strictly injected sequences. The independent
`probe/audit.py` recount of all 757 raw traces, manifests, original JUnit
logs, and JaCoCo files found **zero discrepancies**. The immutable per-file
SHA list is `evidence/campaign-v4/audit.json` (SHA-256
`b4bb1a9ea035b96d99bd8355967fe86528934d14e4d4f6c789d90a8f11b4a954`);
the terminal state SHA-256 is
`d410ad2a64d185c8b042f741178c8bfddfb4225cb1a0d2529af2588dd502dc55`.
`evidence/campaign-v4/terminal-receipt.json` binds those files to the
released source commit, unchanged JUnit class, production class bytes,
actor probe, scheduler, and runner. Full raw trials remain on node1 under
`evidence/campaign-v4`; the node0 copy retains the terminal checkpoint and
audit. The case results and 104-row checklist give each check its own
completion time and outcome.

SOLR-40's five strict exceptions are the **same reproduced fault-induced
alias-cache candidate**, not five bugs and not a confirmed new bug.
`CANDIDATE-SOLR-40.md` records independent original-JUnit replays, persisted
ZooKeeper alias metadata, source comparison, duplicate review, and the
application-entry versus lower-level retry limitation.
