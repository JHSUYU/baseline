# SOLR-19 V3 bounded pilot, first checkpoint

The unchanged Solr 8.11.4 `AddReplicaTest.testAddMultipleReplicas` is the
workload. The selected check is
`CoreContainer.create(String, Path, Map, boolean)` at release
`solr/core/src/java/org/apache/solr/core/CoreContainer.java:1329–1330`:
`cd.getCloudDescriptor().getCoreNodeName() == null`. The two actor-qualified
healthy seeds each passed the original JUnit and reached all nine nonthrowing
instances of this check. Their raw evidence is in
`v3-healthy-raw.tar.gz` with `v3-healthy-archive-manifest.json`.

The pilot began on node1 at 2026-10-07 06:09:42 UTC. It uses only the 15
two-seed stable, sender-qualified I/O selectors; a dynamic
`PRODUCER_OF_CORE:<core>` actor is resolved from the CREATE sender in the
same original JUnit run. Both completed trials were strict, same-actor
one-fault injections and reached the **same core's** target guard after the
fault. No target guard threw the selected exception.

| Trial | I/O selector resource | Applied→same-core target event | Original JUnit | Time | New Solr production probes |
| --- | --- | --- | --- | ---: | ---: |
| r001 | `EXISTS /collections/testAddMultipleReplicas` | 572→577, guard `present` | exit 1; async status `RUNNING` | 131.436 s | 38 |
| r002 | `EXISTS /collections/testAddMultipleReplicas/counter` | 550→558, guard `present` | exit 1; async status `RUNNING` | 130.953 s | 0 |

For both rows, `FAULT_MATCHED` and `FAULT_APPLIED_CONNECTION_LOSS` name the
planned selector and the bound producer `JETTY_3` in that run. The post-run
identity auditor found zero actor, path, caller, ordinal, and order mismatches.
The two trial times sum to 262.389 seconds. Each original JUnit failed its
existing `AddReplicaTest.java:73–74` assertion because
`processAndWait(..., 120)` returned `RUNNING` instead of `COMPLETED`.
`Overseer.java:329–336` catches the injected ZooKeeper `ConnectionLoss` and
logs that it is skipping the cluster-state update message. That downstream
status is retained as a fault symptom, not marked as the selected target
exception or a confirmed new bug.

The healthy production JaCoCo union covered 4,482 methods and 5,588
branches. Adding r001 raised the union to 4,488 methods and 5,603 branches
(+6/+15); r002 added no further production method, branch, probe, or
normalized I/O identity. `CoreContainer.create` remained covered with 7/24
branches, without the `coreNodeName == null` branch. JaCoCo reported zero
unmatched executed Solr classes.

The scheduler saved `r001` and `r002` in its monotonic `state.json`; the
publisher initially lacked a case result template on node1 after r001, so it
exited **after** that trial's atomic checkpoint. The template was restored,
and r002 resumed from the next queued plan; r001 was not replayed. HBASE-32
r159 exceeded its nearby timing baseline during the r002 overlap. We set
`STOP_AFTER_TRIAL` at 06:14:44 UTC and the scheduler paused at the complete
r002 boundary without starting r003. The node1 Solr tmux/JVM exited.
HDFS startup trials overlapping r001/r002 remained within their nearby
timing baseline. The pilot is paused for node1 timing review, with 2/2
strict and target-retaining trials toward the 80-effective budget.

Raw `actor-events.tsv`, JUnit logs, JaCoCo exec, manifests, trial ledgers,
and checkpoint are archived in `v3-pilot-r001-r002.tar.gz`; individual file
SHA-256 values and archive SHA-256 are in
`v3-pilot-r001-r002-manifest.json`. The node1 and node0 copies of the
archive have the same SHA-256. The old coarse-actor 128 rounds remain
historical and are excluded from these V3 counters.

## Second bounded checkpoint: r003–r008

After the HBASE-32 isolated replay released node1, the same saved queue
resumed at r003 at 2026-10-07 06:44:00 UTC. It naturally stopped after r008
met the five-effective pilot gate, without consuming r009. This batch used
the same unchanged original JUnit and same V3 actor/coverage overlay. The
six runs took 101.198 seconds in total. All six original JUnits exited 0;
the logs for some runs contain injected `ConnectionLoss` errors that were
recovered by Solr. No selected target guard took its missing-value branch.

| Trial | Exact I/O and role | Applied event(s) → same-core target | JUnit | Time | New production probes |
| --- | --- | --- | --- | ---: | ---: |
| r003 | owner `EXISTS_WATCH /collections/testAddMultipleReplicas/state.json` ordinal 1 | 529; target n3 was **before** at 525 | pass | 16.469 s | 0 |
| r004 | same I/O ordinal 2 | 551; target n3 was **before** at 543 | pass | 15.916 s | 0 |
| r005 | owner `EXISTS .../state.json`, `ZkStateWriter.writePendingUpdates` | 534 → 556, guard `present` | pass | 17.868 s | 25 |
| r006 | planned r005 I/O then owner `GET_CHILDREN /collections` | 0/2 faults applied; n3 target occurred without fault | pass | 17.517 s | 0 |
| r007 | r005 I/O then owner `GET_CHILDREN /live_nodes` | 534, 539 → 561, guard `present` | pass | 16.865 s | 4 |
| r008 | producer `EXISTS .../state.json`, same `ZkStateWriter` callsite | 534 → 556, guard `present` | pass | 16.563 s | 0 |

The independent archive auditor `audit_pilot_v3.py` checks each raw
`ZK_BIND` and preceding CREATE sender against the fault actor, exact
operation, path, caller, ordinal, and synchronized IO→match→apply events.
It found no identity discrepancy in the five strict trials. In r005/r007,
the target n3 owner was the dynamically resolved `JETTY_3` in those runs;
in r008 the CREATE producer was `JETTY_3`. Its archived receipt also records
that r003/r004 target n3 preceded the fault, so they count as attempts only.
r006 was unmatched and also counts only as an attempt. All six runs recorded
nine exact nonthrowing guard events and zero external-properties file opens.

The pilot as a whole now has 8 attempts, 7 strict injections, 5 effective
same-core post-fault target trials, 363.587 seconds of JUnit time, and zero
target-exception candidates. The healthy plus r001–r008 JaCoCo union covers
4,490 Solr production methods and 5,614 branches: +8 methods and +26
branches above the healthy union. The selected `CoreContainer.create`
remains at 7/24 branches; its missing-core-node branch has not been taken.
If only the five effective trials are unioned with the healthy seeds, the
counts are 4,490 methods and 5,613 branches (+8/+25). Thus one additional
branch came from a non-effective attempt and did not guide mutation.
Probe-level feedback gained 67 IDs: 38 in r001, 25 in r005, and 4 in r007.
r005's new probes were mainly in `ZkDistributedQueue` and
`Overseer.ClusterStateUpdater`; this is observed execution novelty, not
proof that the fault caused every new path. Four normalized I/O identities
appeared in r005: `/collections` and `/live_nodes` reads, and two
`/overseer/queue/qn-*` reads. The generated queue-item IDs are normalized
for feedback but are excluded from newly generated exact-path child plans;
three preexisting two-seed stable concrete queue IDs remain empirical plans.

Node1 raw files are archived in `v3-pilot-r003-r008.tar.gz`, with per-file
SHA-256 values and archive SHA-256 in
`v3-pilot-r003-r008-manifest.json`. The node0 archive copy matches the node1
SHA-256. The independent raw receipt is `v3-pilot-r003-r008-audit.json` and
the production coverage union is `v3-pilot-r001-r008-union-coverage.json`.
HDFS startup JUnits overlapping this short Solr pilot completed in 76.110
and 42.202 seconds with exit 0 and same-actor targets, within their nearby
timing distribution. The node1 Solr tmux/JVM exited at the r008 boundary.
The full 80-effective campaign will resume from r009 after HBASE-32 releases
its five-effective completion window; no pilot trial will be replayed.

### Complete-boundary queue correction

At the r008 boundary, an offline queue audit found that old child mutation
counted a repeated I/O occurrence starting after the preceding fault,
whereas the runtime matcher counts from the same core's CREATE sender. The
already tested r001–r008 selectors and exact raw outcomes remain unchanged.
`repair_queue_v3.py` rebuilt **only untried mutated children** from their
archived parent traces using the corrected sender-relative ordinal; it also
avoids newly adding generated `/qn-<number>` queue-item paths. The 58
untried stable/exploratory single-fault plans retained their order. The old
queue had 66 plans (8 mutated children); the repaired queue has 67 plans
(9 mutated children). The historical r008 state SHA-256 is
`94bd51545a334a5b3e8c65afb5acd8c22398b0cafe0d39d7182ec4e32ea226e5`;
the repaired state SHA-256 is
`6293065e8a4f1d1eb7174380278411a5a265a0e062698cdd5406bab1838f49cd`.
The repair atomically replaced the paused node1 state after verifying the
old hash and equality of the entire attempts ledger, seen plans, coverage,
I/O feedback, budget, and no in-flight trial. Its machine-readable plan diff
and compressed repaired checkpoint are in
`v3-queue-ordinal-repair-receipt.json` and
`v3-repaired-checkpoint-r008.json.gz`.
