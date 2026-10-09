# SOLR-05 upstream state-write stage

This stage runs the unchanged Solr 8.11.4
`AddReplicaTest.testAddMultipleReplicas` on its original embedded
`MiniSolrCloudCluster`. The selected oracle is only
`ZkController.register`'s `replica == null` check at source line 1273.
The test intentionally expects a different add-replica capacity failure;
that JUnit assertion is never counted as the selected exception.

## Source-backed relation

`Overseer.ClusterStateUpdater.processQueueItem` feeds
`ZkStateWriter.enqueueUpdate`. The probe compares each `ZkWriteCommand`'s
`DocCollection` to the prior `ClusterState`, identifying a newly added
replica by collection, shard, core-node ID, core name and intended node.
`ZkStateWriter.writePendingUpdates` then calls `SolrZkClient.setData` on
that collection's exact `state.json` path. The probe records the actual
writer object, Overseer `SolrZkClient`, `ZkStateReader`, physical Jetty
role and intended receiver node. A batch containing multiple newly added
replicas, competing writers for the same replica, or an unbound client
fails closed.

The two fault points are immediately before `setData` and immediately
after it returns successfully. Both inject `ConnectionLossException`.
The POST point models a persisted ZK write whose caller observes a
connection failure. They have distinct operation IDs and are selected
only by operation, full path, stable callsite, unique logical replica,
and within-run ordinal. The raw trace retains the writer and receiver
physical node names and Java object IDs. A trial is effective only if
every planned fault is matched and applied in order and the original
target check later runs for the exact same collection, shard, replica,
core and intended node. The target's actual `ZkController` client and
reader must be registered and bound by the same-run identity ledger.

No graph is constructed. Per-run JaCoCo production probes, methods and
covered branch counts plus stable I/O family novelty guide mutation.
The original JUnit is never modified. The base budget is 80 effective
strict postfault-target trials, at most eight ordered faults, and 240
attempts. At 80 effective trials, novelty in the latest eight permits
128 effective trials, at most ten faults and 384 attempts. Queue
exhaustion is reported separately; plans are not repeated to fill a
nominal budget. Each completed trial atomically updates the case-local
checkpoint and is mirrored to `../result.json`; interrupted trials
restart with fresh scratch while completed trials are preserved.

## Preparation and evidence

The source is pinned at `e27f44e3d78dfcec230c97e0a1240e3751daeff9`.
`probe/build.py` checks that original JUnit bytecode is identical in
the clean and instrumented classpaths. `probe/upstream_hook_smoke.py`
confirmed exactly one pending-update, PRE and POST hook and their bytecode
order. An initial PRE-only double healthy calibration is retained under
`evidence/pre-only-calibration` and contributes no fault trials.

After adding POST, two new clean original JUnits passed in 15.213 and
14.862 seconds, and two new instrumented JUnits passed in 15.916 and
15.921 seconds. Each instrumented run reached the selected target nine
times and observed nine unique upstream state writes, each with PRE and
POST points before that same replica's guard. The final calibration is
`evidence/healthy-summary.json`. The independent campaign runs in tmux
`solr05_upstream_campaign`; its checkpoint and raw trial artifacts are
under `evidence/campaign`. A selected throw remains a candidate until
clean replay and source review distinguish a bug from expected failure.

## Completed stage and separate observation

The queue exhausted after 18 attempts and 349.965 seconds. All 18
faults strictly matched and applied. Nine POST-write trials retained the
exact selected replica guard; none threw the selected exception. Nine
PRE-write trials lost that exact target and were excluded from effective
feedback. The independent raw audit is `evidence/campaign/audit.json`
and reports zero errors. This stage reached 9 of its nominal 80 effective
trials because there were no further valid observed plans; it did not
repeat a plan to fill the budget.

Eight POST-write trials made the original JUnit observe one additional
replica, while one timed out. A separate, strict replay of trial 001 in
`evidence/replay-post-001` reproduced the 9→10 assertion and the
`core_node18` → `core_node19` retry for the same core/node. This is not
the selected `replica == null` outcome. The full source and public-issue
comparison is in `POST_WRITE_REVIEW.md`; novelty remains unresolved.
