# SOLR-19 V3 campaign checkpoint: r009–r040

The workload is the unchanged Solr 8.11.4 embedded-cluster JUnit
`AddReplicaTest.testAddMultipleReplicas` on release commit `e27f44e`.
The selected target is `CoreContainer.create` at
`solr/core/src/java/org/apache/solr/core/CoreContainer.java:1329–1330`,
the `coreNodeName == null` guard. The fault controller injects
`KeeperException.ConnectionLossException` only at an ordered, exact
operation/path/caller/dynamic-actor/occurrence match. This checkpoint is a
continuation of the r001–r008 campaign; it does not reset its queue or budget.

The node1 `v3-campaign-r009-r040.tar.gz` archive has SHA-256
`b6822d1a7873c2f754cf120c6a4cc6d2e6b300ac52e6b915686f20d80c6a3384`
and 160 independently hashed original files: each trial's event trace, JUnit
log, JaCoCo execution data, manifest, and ledger. The manifest and archive
were copied to node0 with the same archive hash. `audit_archive_v3.py`
verified the archive and every file hash, then audited the raw same-run
ZooKeeper-client bind, CREATE sender, fault actor, exact I/O identity,
ordered match/application, and target guard's core and receiver node.
Its machine-readable receipt is `v3-campaign-r009-r040-audit.json`.

| r009–r040 measure | Value |
| --- | ---: |
| Original JUnit attempts | 32 |
| Ordered strict exact-actor injections | 20 |
| Strict injections with later same-core, same-sender target guard | 18 |
| Selected target exceptions | 0 |
| JUnit exit failures | 8 |
| Total JUnit elapsed time | 729.789 s |
| New production probe IDs reported to the scheduler | 68 |
| New normalized stable I/O families reported to the scheduler | 9 |
| Maximum ordered fault depth in this batch | 4 |
| Auditor strict identity or target actor-lineage issues | 0 |

The eight failed original JUnits are r013, r014, r015, r019, r032, r036,
r037, and r040. In r013/r014/r015/r019, the log reports a collection load
error from ZooKeeper after connection-loss injection. In r036/r037/r040,
the log reports an Overseer state-queue update error; r032 reports a failed
counter update followed by a 120-second replica-visibility wait. These are
faulted-workload outcomes, not the selected `coreNodeName == null` exception.
The 131.641-second r032 and 130.583-second r037 runs are the same
fault-specific wait family observed in r001/r002; nearby HDFS JUnits that
overlapped this Solr campaign remained in their own normal timing range.
No new bug is claimed from these eight failures.

The full campaign remains active in node1 tmux `solr19-v3-full`. At this
checkpoint, r001–r040 totals are **40 attempts, 27 strict injections,
23 effective target-retaining trials, and zero selected target exceptions**;
the first eight contributed five effective trials and 363.587 seconds.
The current 80-effective/max8 budget and later-novelty extension rule are
unchanged. This receipt is an intermediate audit, not a terminal case result.
