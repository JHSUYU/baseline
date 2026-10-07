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
