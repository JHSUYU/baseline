# SOLR-6197 (Collection migration fails): detected

Case `solr-adhoc-k3`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `solr/core/src/java/org/apache/solr/handler/admin/CoreAdminHandler.java:563`, `CoreAdminHandler.handleCreateAction(SolrQueryRequest, SolrQueryResponse)`, throws `org.apache.solr.common.SolrException` when `coreContainer.getZkController() != null && !Overseer.isLegacy(coreContainer.getZkController().getZkStateReader().getClusterProps()) && dcore.getCloudDescriptor().getCoreNodeName() == null   (three nested ifs)`
- Starting test: `org.apache.solr.cloud.MigrateRouteKeyTest#testDistribSearch`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** yes

**What the agent found:** With legacyCloud=false set via the CLUSTERPROP API, MIGRATE fails because OverseerCollectionProcessor.migrateKey sends a raw core-admin CREATE for the temp collection's replica2 on the target leader node without coreNodeName, which CoreAdminHandler.handleCreateAction:563 rejects ('non legacy mode coreNodeName missing').

**Same root cause as SOLR-6197?** Same defect. In the buggy tree, OverseerCollectionProcessor.java:1897-1905 (migrateKey) builds a CoreAdminAction.CREATE with only name/collection/shard and sends it via sendShardRequest to the target leader, with no clusterstate registration and no coreNodeName; the validate log shows exactly that request (name=split_shard2_temp_shard1_shard1_replica2, no coreNodeName) rejected at CoreAdminHandler.java:563. The fix hunk @@ -1894,15 +1895,25 @@ replaces this raw CREATE with addReplica(...) using ADDREPLICA props, which registers the replica and passes coreNodeName.

**Realistic?** Yes. The test is MigrateRouteKeyTest's mini SolrCloud cluster with legacyCloud=false set through the supported Collections API CLUSTERPROP call (the same trigger the fix's own test change adds), then ordinary indexing, CREATE collection and MIGRATE calls. No reflection, mocks or fabricated arguments; the only test file is new and production sources are unmodified.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **NOT_REPRODUCED**. On the buggy tree plus the fix, all 4 runs no longer hit the check; the target node's CREATE now carries coreNodeName=core_node2 and succeeds, and MIGRATE completes (the test fails only on its own assertion 'MIGRATE unexpectedly succeeded in legacyCloud=false mode'), so the consequence goes away.

**Reason:** The agent's failing execution is exactly SOLR-6197: MIGRATE with legacyCloud=false creates the temporary collection's extra replica via core-admin CREATE without coreNodeName, and CoreAdminHandler rejects it, so the migration fails. The trigger is a valid cluster property set through the public API, the consequence (MIGRATE fails) matches the JIRA, and the fix removes the failure.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** legacyCloud=false is a documented, supported cluster mode that can be set through the CLUSTERPROP API. In this mode the Overseer and the node must agree that the Overseer registers each replica in clusterstate before it asks a node to create the core, and that it passes coreNodeName in the request. createCollection and addReplica (which SPLITSHARD uses) do this; the MIGRATE code path in OverseerCollectionProcessor.migrateKey does not. The request the check rejects comes from Solr's own Overseer, not from a user. As a result, MIGRATE always fails on any cluster running with legacyCloud=false. The failure comes after the source index has already been split into a temp collection, a routing rule has been added that forwards the route key's updates to the target collection, and the target leader has been put into update-buffering mode. A partially done migration is left behind: a temp collection, a routing rule that stays until it expires, and a target core whose buffering is never applied by this MIGRATE. The route key's documents are not moved.

**Execution (agent):** 1. Start the same mini SolrCloud cluster as MigrateRouteKeyTest: collection1 with 2 shards, plus a control node and the Overseer. 2. A client switches the cluster to non-legacy mode with the supported Collections API call CLUSTERPROP name=legacyCloud val=false; this writes /clusterprops.json in ZooKeeper. 3. Index documents with route key a/1!, then create the target collection migrate_nonlegacy_targetCollection (1 shard, 1 replica). In non-legacy mode createCollection first registers each replica in clusterstate through the Overseer (ADDREPLICA) and sends coreNodeName in the core CREATE, so this step succeeds. 4. The client calls MIGRATE collection=collection1 split.key=a/1! target.collection=migrate_nonlegacy_targetCollection. The Overseer (OverseerCollectionProcessor.migrateKey) asks the target leader to buffer updates and adds the routing rule. It then creates the temp collection split_shard2_temp_shard1 on the source leader node; that call goes through createCollection, which handles non-legacy mode, so it succeeds. It runs SPLIT into the temp core. 5. The Overseer then sends a raw core-admin CREATE for split_shard2_temp_shard1_shard1_replica2 to the target leader node with only name, collection and shard. Unlike createCollection and addReplica, migrateKey does not check legacyCloud: it does not first create the replica entry in clusterstate and does not pass coreNodeName. 6. On the target node, CoreAdminHandler.handleCreateAction reads the cluster props from ZooKeeper, sees legacyCloud=false and a null coreNodeName, and throws SolrException('non legacy mode coreNodeName missing ...') at CoreAdminHandler.java:563. The Overseer reports 'MIGRATE failed to create replica of temporary collection in target leader node.' and the MIGRATE fails. The test sees that error and rethrows it.

**Stack frame (agent):** at org.apache.solr.handler.admin.CoreAdminHandler.handleCreateAction(CoreAdminHandler.java:563)

## Reproduction

- Test: `org.apache.solr.cloud.MigrateRouteKeyNonLegacyTest#testDistribSearch`
- Command: `source /bulk/codingagent/cases/solr-adhoc-k3/agent/env.sh && cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=MigrateRouteKeyNonLegacyTest -Dtests.method=testDistribSearch -Dtests.jvms=1 -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib`
- Test files (in `repro/`, paths relative to the system's tree): `solr/core/src/test/org/apache/solr/cloud/MigrateRouteKeyNonLegacyTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `[junit4]   2> 	Caused by: org.apache.solr.common.SolrException: non legacy mode coreNodeName missing qt=/admin/cores&name=split_shard2_temp_shard1_shard1_replica2&action=CREATE&collection=split_shard2_temp_shard1&shard=shard1&wt=javabin&version=2`, frame `[junit4]   2> 		at org.apache.solr.handler.admin.CoreAdminHandler.handleCreateAction(CoreAdminHandler.java:563)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h03m | 1 | 399,964 | 24 | 8,156 | 36,406 | 355,378 | $0.53 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
