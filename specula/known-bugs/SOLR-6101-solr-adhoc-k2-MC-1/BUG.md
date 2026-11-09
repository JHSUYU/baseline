# SOLR-6101: detected by Specula (yes), finding MC-1

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `solr-adhoc-k2`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

With the cluster property `legacyCloud=false`, a core may only be created when its `coreNodeName` is already known (pre-registered in clusterstate by the Overseer); CoreAdmin CREATE without `coreNodeName` is rejected by `CoreAdminHandler.handleCreateAction`. `OverseerCollectionProcessor.splitShard` (buggy) creates the sub-shard slices (CONSTRUCTION) and then sends plain CoreAdmin CREATE requests (name, collection, shard, no coreNodeName) to create the sub-shard leader cores and later the sub-shard replica cores. In non-legacy mode each such CREATE fails with "non legacy mode coreNodeName missing", the Overseer's `waitForCoreNodeName` then gives up ("Could not find coreNodeName"), and SPLITSHARD fails. Trigger: set `legacyCloud=false` (CLUSTERPROP), then SPLITSHARD. Fix: wait for the new slice in clusterstate, then create the sub-shard cores via the Overseer's ADDREPLICA path (`addReplica`), which assigns the coreNodeName. (MIGRATE has the same problem in this tree, SOLR-6197, fixed later; it hits the same check.)

## What counted as detecting it (written before the run)

A finding must show: with `legacyCloud=false` in cluster properties, a SPLITSHARD makes the Overseer send a CoreAdmin CREATE for a sub-shard core (leader or replica) without a coreNodeName, so `handleCreateAction` throws at line 560 and the split fails (sub-shards stay in construction / the split cannot complete). Same root cause (splitShard creates sub-shard cores by plain CoreAdmin CREATE, bypassing coreNodeName assignment) and same check. A finding that instead reaches the check through MIGRATE's temp-collection replica is the related SOLR-6197 bug (also present here), not this one.

## What Specula found

**Specula's finding MC-1:** SPLITSHARD always fails the CoreAdminHandler:560 coreNodeName check when legacyCloud=false

- **Cause:** OverseerCollectionProcessor.splitShard sends sub-shard leader (and replica) CoreAdmin CREATE requests without coreNodeName and never consults legacyCloud; CoreAdminHandler.handleCreateAction rejects any CREATE lacking coreNodeName when the live ZK cluster prop legacyCloud=false.
- **Trigger:** Operator sets CLUSTERPROP legacyCloud=false through the Collections API, then issues SPLITSHARD on any shard; no race or fault needed.
- **Consequence:** Every SPLITSHARD fails (HTTP 500 'SPLITSHARD failed to create subshard leaders', root cause SolrException at CoreAdminHandler.java:560) and leaves CONSTRUCTION sub-slices with no replicas in cluster state; a later SPLITSHARD of the same shard, even after legacyCloud is unset, fails with 'Unable to delete already existing sub shard' because deleteShard refuses CONSTRUCTION slices.
- **Premises:** legacyCloud=false is a supported cluster property settable via the public CLUSTERPROP Collections API (KNOWN_CLUSTER_PROPS). ZkStateReader.getClusterProps reads /clusterprops.json live from ZK on each call. No caller of splitShard supplies coreNodeName (property.coreNodeName is not set by any caller). Pinned base 6e6ca4a predates the upstream fix SOLR-6101 (switch split to ADDREPLICA).

**Operator's judgement:** yes. SPLITSHARD fails coreNodeName check under legacyCloud=false; CR-1 also covers SOLR-6197 (MIGRATE)

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_split_nonlegacy.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-08: Invariant TargetSafe is violated.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 1h27m | 37.4M | $22.80 |

Time is active time; quota sleeps are excluded.
