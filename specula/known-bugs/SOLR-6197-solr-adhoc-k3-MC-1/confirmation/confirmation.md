# MC-1 confirmation

Verdict: REPRODUCED (Level 0). Novelty: KNOWN (SOLR-6197, fixed upstream in 4.10/5.0).
Reproduction: repro/test_bugMC-1_run.sh, which runs repro/test_bugMC-1_SpeculaReproMC1MigrateRouteKeyTest.java.
It ran on the pristine base_commit e75b9596 with the harness instrumentation stashed and then restored.
Logs: repro/MC-1.bug.log, repro/MC-1.control.log, repro/MC-1.run.out.

Bug run (CLUSTERPROP legacyCloud=false, then the workload's CREATE target + MIGRATE a/1!):
- Node side: SolrException "non legacy mode coreNodeName missing ... name=split_shard2_temp_shard1_shard1_replica2&action=CREATE..."
  at org.apache.solr.handler.admin.CoreAdminHandler.handleCreateAction(CoreAdminHandler.java:563)
- Overseer: "MIGRATE failed to create replica of temporary collection in target leader node."
  at OverseerCollectionProcessor.migrateKey(OverseerCollectionProcessor.java:1906)
- The client's MIGRATE gets a RemoteSolrException.
- Left behind, still present after 60s: temp collection split_shard2_temp_shard1, routing rule a! on collection1/shard2,
  and the target leader UpdateLog in BUFFERING.

Control run (legacyCloud unset, i.e. the original workload): MIGRATE SUCCESS, target leader UpdateLog ACTIVE, no temp collection left.
