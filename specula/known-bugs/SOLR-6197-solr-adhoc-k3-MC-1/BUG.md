# SOLR-6197: detected by Specula (yes), finding MC-1

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `solr-adhoc-k3`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

With `legacyCloud=false`, CoreAdmin CREATE without a `coreNodeName` is rejected by `CoreAdminHandler.handleCreateAction`. `OverseerCollectionProcessor.migrateKey` (buggy) creates a temporary collection `split_<srcShard>_temp_<tgtShard>` (via createCollection, which in non-legacy mode pre-registers its replica correctly), splits the source into it, and then creates a second replica of the temp collection on the target leader's node with a plain CoreAdmin CREATE (name `<temp>_<shard>_replica2`, collection, shard, no coreNodeName). In non-legacy mode that CREATE fails with "non legacy mode coreNodeName missing" and MIGRATE fails ("MIGRATE failed to create replica of temporary collection in target leader node."). Trigger: set `legacyCloud=false` (CLUSTERPROP), then MIGRATE a split.key. Fix: create that replica through the Overseer's ADDREPLICA path (`addReplica`). (SOLR-6101, the same problem for SPLITSHARD, is already fixed in this tree.)

## What counted as detecting it (written before the run)

A finding must show: with `legacyCloud=false`, MIGRATE makes the Overseer (migrateKey) send a CoreAdmin CREATE for the temporary collection's replica on the target leader node without a coreNodeName, so `handleCreateAction` throws at line 563 and MIGRATE fails. Same root cause (migrateKey creates that replica by plain CoreAdmin CREATE) and same check.

## What Specula found

**Specula's finding MC-1:** MIGRATE's temp replica2 CoreAdmin CREATE omits coreNodeName, so it fails at CoreAdminHandler:563 when legacyCloud=false

- **Cause:** OverseerCollectionProcessor.migrateKey builds its own CoreAdmin CREATE for <temp>_shard1_replica2 with only ACTION/NAME/COLLECTION/SHARD. It does not go through ADDREPLICA or set coreNodeName, so in non-legacy mode CoreAdminHandler.handleCreateAction throws 'non legacy mode coreNodeName missing'.
- **Trigger:** CLUSTERPROP legacyCloud=false, then MIGRATE through the Collections API (MigrateRouteKeyTest workload). Deterministic; needs no fault or race.
- **Consequence:** MIGRATE always fails under legacyCloud=false. migrateKey aborts with no cleanup, leaving the temp collection, the routing rule on the source slice and the target leader's UpdateLog in BUFFERING (still the case 60s later).
- **Premises:** legacyCloud=false is a supported cluster property set via the public CLUSTERPROP API (KNOWN_CLUSTER_PROPS). Reproduced on pristine base_commit e75b9596; upstream fixed the same mechanism in SOLR-6197 (4.10/5.0).

**Operator's judgement:** yes. MIGRATE temp replica2 CREATE omits coreNodeName

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_S1_migrate.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-08: Invariant TargetSafe is violated.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 1h09m | 40.1M | $25.33 |

Time is active time; quota sleeps are excluded.
