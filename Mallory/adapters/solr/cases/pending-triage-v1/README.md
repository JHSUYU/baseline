# Pending Solr source triage, 2026-10-09

This directory stages eight bounded **healthy-only** configurations. It does not
record new healthy runs, injected faults, completed checks, or bugs. Dispatch
must admit a configuration, reserve a Solr lane, and inspect its fresh JUnit,
exact target, runtime actor, and causal-path receipts before any fault campaign.
The pinned source is Solr 8.11.4 commit
`e27f44e3d78dfcec230c97e0a1240e3751daeff9` in the clean
`.graphchecker-sources/solr-8.11.4` checkout. `stage.py` checks that commit,
the runtime artifact hashes, and the copied configuration hashes. It only
writes files in this directory.

| Case | Existing cluster JUnit | Source-backed operation | Prior healthy evidence | Remaining gate |
| --- | --- | --- | --- | --- |
| SOLR-01 | `CloudHttp2SolrClientTest#testAliasHandling` | Creates aliases and queries through the HTTP client | Passing JUnit; 15 exact client checks in v4 | Verify a causal I/O door on the **client** actor before faulting all alias providers. |
| SOLR-09 | `DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup` | Deletes an existing leader replica on the synchronous command path | Passing JUnit; one exact `node1` check in v10 | Existing trace had no named door in the target closure; repair request-to-Overseer lineage. |
| SOLR-13 | `TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation` | Calls `addOneDocSynchCreation`, which synchronously creates future time buckets | Old JUnit failed during ConfigSet creation, before target | Run the staged ConfigSet auth overlay; require a passing exact target hit. |
| SOLR-14 | `SplitShardTest#doTest` | Splits a valid shard after finding its leader | Passing JUnit; three exact `node1` checks, eight named closure doors in v10 | Revalidate event-time path on the current agent and exact source. |
| SOLR-18 | `AliasIntegrationTest#testDeleteAliasWithExistingCollectionName` | Changes aliases and waits for ZK versions | Passing JUnit; 51 exact `node2` checks in v10 | Verify assertions are enabled and connect the ZK update to the target; old closure has zero named doors. |
| SOLR-37 | `ShardSplitTest#test` | Sends parent-to-subshard updates during split scenarios | v14a passed JUnit and hit target 108 times, but trace was truncated | `solr_adapter` owns compact-coverage v29 admission. No duplicate config here. |
| SOLR-38 | `CloudHttp2SolrClientTest#testAliasHandling` | Sends distributed updates during alias work | Passing JUnit and named target in v24; 4/4 later faults applied, none reached target afterward | Improve fault placement or select a shorter leader transition test before a full campaign. |
| SOLR-39 | `TimeRoutedAliasUpdateProcessorTest#test` | Creates a time-routed alias and adds routed documents | Old JUnit failed during ConfigSet creation, before target | Run the staged ConfigSet auth overlay; require a passing exact target hit. |
| SOLR-40 | `TimeRoutedAliasUpdateProcessorTest#test` | Creates a time-routed alias and adds routed documents | Old JUnit failed during ConfigSet creation, before target | Run the staged ConfigSet auth overlay; require a passing exact target hit. |

All nine have a source-backed cluster test candidate. Therefore none is marked
`no_suitable_cluster_test` based on the older failed calibrations. SOLR-13,
39, and 40 have **unverified** fixed healthy configs: the older failures were
Solr's ConfigSet 401 guard, and the overlay sets
`-Dsolr.disableConfigSetsCreateAuthChecks=true`, a flag present in the pinned
source. That setup flag is only for reaching the unchanged JUnit workload; it
is not evidence that the selected target is reached. SOLR-37 is excluded from
the generated configs because another agent already owns its v29 calibration.

Every staged config has one healthy trial, a 900 s wall limit, a 480 s trial
timeout, `calibration_only: true`, and `auto_promote_if_healthy: false`.
`triage.json` records source/test/result SHA-256 values and exact source
locations. Historical calibrations remain in `data/mallory`; this directory
does not alter the 102-row canonical checklist.

These configs inherit older Solr release wrappers and agent JARs from their
source configs. Their purpose is to re-establish JUnit/target reachability.
Strict event-time causal admission needs a separately pinned runner and
thread-ID-capable agent; a passing staged healthy run alone is insufficient.
