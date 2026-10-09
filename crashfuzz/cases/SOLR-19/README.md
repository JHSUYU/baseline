> **Actor-qualified V3 complete.** Earlier coarse-actor trials remain under
> `legacy_coarse_actor` and do not count toward the current result. The V3
> campaign used the unchanged cluster JUnit, same-run CREATE sender and
> ZooKeeper-client identity, exact ordered I/O selectors, and production
> coverage feedback. Its terminal result is below.

# SOLR-19: core node identity before core creation

- Original Solr 8.11.4 source commit: `e27f44e`; `independent/solr-source` is a read-only link to the clean SOLR-05 source worktree to save disk space. All classes, temp state, traces, and checkpoints are case-local.
- Selected check: `solr/core/src/java/org/apache/solr/core/CoreContainer.java:1329`, `CoreContainer.create(String, Path, Map, boolean)`, `if (cd.getCloudDescriptor().getCoreNodeName() == null)` in non-legacy mode; the next line throws `SolrException(SERVER_ERROR, "non legacy mode coreNodeName missing ...")`.
- Original workload: unchanged `AddReplicaTest.testAddMultipleReplicas`, an embedded SolrCloud JUnit adding replicas. The uninstrumented JUnit passed in 23.095 seconds. The independently instrumented healthy JUnit passed in 27.554 seconds and hit the exact check 9 times on its nonthrowing branch.

The case-local `independent/probe/weave.py` builds a target marker in `CoreContainer` plus six `SolrZkClient` method hooks. The original source is not modified. Faults are `KeeperException.ConnectionLossException` at exact observed operation, ZooKeeper path, and hit ordinal; relative phase anchors are used for later faults in a sequence. JaCoCo production coverage and stable caller-operation-resource I/O identities guide mutations. ZooKeeper collection state, leadership, live-node and Overseer paths form the scoped I/O input. File I/O and HTTP are not intercepted in this initial scope.

Only a complete ordered injection followed by a later execution of this **same** selected check supplies coverage feedback or a target-exception candidate. The base budget is 80 trials, at most eight faults per sequence; valid new production coverage or stable I/O identity in trials 73–80 extends the same checkpoint to 128 trials and ten faults. An exact throwing-guard event is a candidate for original-source review and clean replay, not a confirmed new bug. Per-trial time, plan, matched/applied events, target timeline, JUnit log, and JaCoCo data are retained under `independent/evidence/campaign/`.

The campaign supervisor runs in tmux `solr19-independent`, and `solr19-independent-sync` refreshes the 102-check table. This campaign has its own healthy trace and checkpoint and does not reuse SOLR-07 or SOLR-05 fault-trial counts.

Source review: `CoreContainer.create` builds a `CoreDescriptor` from the create request parameters before this check. In non-legacy cloud mode, the guard validates its `coreNodeName` before the subsequent ZooKeeper existence check and core properties writes. A later ZooKeeper failure or a JUnit assertion failure therefore does not by itself establish that this selected guard threw.

## Historical coarse-actor campaign

The independently calibrated campaign completed 128/128 fault trials. Trial 76 added five production coverage probes with all planned faults applied and a later selected check, so the configured 80-trial budget extended to 128/max10. Of the 128 trials, 116 applied every requested exception in order and 81 both applied them and reached this exact guard after the final fault. The deepest strictly applied sequence contained ten exceptions. Eligible runs added 585 production JaCoCo probes, 63 covered production methods, 233 covered production branches, and three stable caller-operation-resource I/O identities. The summed trial duration was 6,821.336 seconds.

The exact `coreNodeName == null` throwing outcome occurred **zero** times. The unchanged JUnit returned success 68 times, failure 52 times, and hit the 240-second single-trial limit eight times; these are distinct workload outcomes and are not evidence that this selected exception occurred. The audit recomputed all 128 injection sequences and target timelines from raw events. This result covers the six instrumented `SolrZkClient` methods on relevant collection, leader and Overseer paths in the original test; file and HTTP I/O were outside this case's injection scope. No new bug is confirmed for this check within that scope and budget.

Machine-readable evidence: `independent/evidence/campaign/state.json`, `audit.json`, `coverage-summary.json`, and each `trial-NNN/{trial.json,events.tsv,junit.log,jacoco.exec}`. Completed trial scratch was removed; original logs, traces and JaCoCo files remain.

## Actor-qualified V3 result

The unchanged three-Jetty `AddReplicaTest.testAddMultipleReplicas` reached the
exact guard nine times in each of two passing healthy seeds. The V3 campaign
then ran **134 original JUnit attempts**, applying every planned exception in
order and to the intended dynamic actor in **92**. In **80** of those, the
same core and CREATE sender reached the selected guard after the last fault.
The deepest fully applied sequence contained eight exceptions. The summed
JUnit time was **7,276.230 seconds**; 73 JUnits passed and 61 failed. All
attempts, including failed JUnits, remain in the per-trial ledger.

The selected `coreNodeName == null` throwing outcome occurred **zero** times.
Across archived raw traces there were 897 exact guard events, all with a
present value. The final eight effective trials added no new production
coverage probe or normalized I/O family, so the configured 80-effective-trial
budget stopped without an extension. Feedback added 436 production probe IDs
and 19 normalized I/O identities. The independent JaCoCo union grew from
4,482 to 4,543 Solr production methods and from 5,588 to 5,808 production
branches over all attempts; the healthy-plus-effective union covered 4,532
methods and 5,773 branches. Those branch totals describe the whole selected
method and related production code; the exact guard outcome comes from the
raw `TARGET_GUARD` events.

The source path is `CoreAdminOperation.CREATE_OP → CoreDescriptor →
CloudDescriptor → CoreContainer.create`. `CoreDescriptor` may read external
properties before the guard, and `property.coreNodeName` may override the
standard CREATE parameter. Neither override occurred in the two healthy
seeds. The campaign's scoped ZooKeeper `ConnectionLossException` faults did
not produce the selected missing-name value. JUnit failures after fault
injection were usually asynchronous request-status failures; they are not
evidence that this selected exception occurred. **No new bug is confirmed
for SOLR-19 within this original test, I/O scope, and budget.**

The final immutable checkpoint, all raw trial archives, per-file hashes,
independent identity audits, coverage union, and source review are in
`independent/actor_v2/evidence/`. See `v3-final-audit.json` and
`v3-final-review.md`. The node1 original JUnit tmux exited at the completed
trial boundary; the final checkpoint SHA-256 is recorded in `result.json`.
