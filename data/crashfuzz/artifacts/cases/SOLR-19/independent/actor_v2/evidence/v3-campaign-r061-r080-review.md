# SOLR-19 V3 campaign checkpoint: r061–r080

The unchanged Solr 8.11.4 `AddReplicaTest.testAddMultipleReplicas` cluster
JUnit continued from the r060 checkpoint on node1. The selected target is
`CoreContainer.create` at `CoreContainer.java:1329–1330`, specifically the
`coreNodeName == null` guard. Every attempted fault is an ordered
`KeeperException.ConnectionLossException` at an observed ZooKeeper I/O point
with exact operation, path, caller, dynamic actor, and occurrence identity.

The completed r061–r080 event traces, original JUnit logs, JaCoCo execution
data, runner manifests, and trial ledgers are in
`v3-campaign-r061-r080.tar.gz` (5,201,140 bytes; SHA-256
`3f8305f476e49a998e87012a58843961637f387254bfe6039cf7e06081a222fb`).
The manifest records 100 individual file hashes. Node1 and node0 archive
copies have the same hash. The independent `audit_archive_v3.py` receipt
`v3-campaign-r061-r080-audit.json` verified those bytes and each trial's
same-run CREATE sender, ZooKeeper-client bind, exact I/O identity, ordered
fault application, and same-core target actor lineage.

| r061–r080 measure | Value |
| --- | ---: |
| Original JUnit attempts | 20 |
| Strict ordered identity matches | 15 |
| Strict injections with later same-core, same-sender target | 15 |
| Selected target exceptions | 0 |
| Original JUnit failures | 12 |
| Total JUnit elapsed time | 917.747 s |
| New production probe IDs in scheduler feedback | 33 |
| New normalized stable I/O families | 0 |
| Maximum ordered fault depth | 8 |
| Independent strict identity/target lineage issues | 0 |

The failed JUnits include the previously observed 120-second asynchronous
status wait family and short `FAILED` status outcomes after ZooKeeper faults.
No selected target guard took the missing-value branch; the JUnit failures
are faulted-workload outcomes, not confirmed new bugs. Five attempts without
all ordered faults or a later target remain outside the effective budget.

At r080, the campaign had **80 attempts, 58 strict injections, 49 effective
target-retaining trials, zero selected target exceptions**, 2,933.701 seconds
of original-JUnit time, and 423 new production probe IDs above the two
healthy seeds. The node1 `solr19-v3-full` tmux continues at r081 toward the
80-effective/max8 budget; these are attempts, not a completed budget.

An independent union over healthy JaCoCo data plus all r001–r080 trials
covered 4,543 Solr production methods and 5,800 branches, up from 4,482
methods and 5,588 branches in the healthy union (+61/+212). Healthy plus only
the 49 effective trials covered 4,532 methods and 5,767 branches (+50/+179).
All executed production classes matched the release/overlay bytecode.
The entire selected `CoreContainer.create` **method** covered 15/24 branches
in the all-trial union and 7/24 in the effective union; these counts include
other conditions within that method. The archived traces contain 597 exact
`TARGET_GUARD` events in the 80 attempts and **zero** `missing` outcomes.
`v3-campaign-r001-r080-union-coverage.json` records both unions and the raw
guard count; method-level branch growth must not be reported as a target
exception.
