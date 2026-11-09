# SOLR-6101 (Shard splitting fails): detected

Case `solr-adhoc-k2`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `solr/core/src/java/org/apache/solr/handler/admin/CoreAdminHandler.java:560`, `CoreAdminHandler.handleCreateAction(SolrQueryRequest, SolrQueryResponse)`, throws `org.apache.solr.common.SolrException` when `coreContainer.getZkController() != null && !Overseer.isLegacy(coreContainer.getZkController().getZkStateReader().getClusterProps()) && dcore.getCloudDescriptor().getCoreNodeName() == null   (three nested ifs)`
- Starting test: `org.apache.solr.cloud.ShardSplitTest#testDistribSearch`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** yes

**What the agent found:** Once legacyCloud=false is set through CLUSTERPROP, a plain SPLITSHARD of shard1 fails every time. The Overseer sends the sub-shard leader core-admin CREATE without a coreNodeName, and CoreAdminHandler rejects it ('non legacy mode coreNodeName missing'), so the split aborts with 'SPLITSHARD failed to create subshard leaders'.

**Same root cause as SOLR-6101?** Yes. In the buggy OverseerCollectionProcessor.splitShard (OverseerCollectionProcessor.java:1335-1347) the Overseer queues the createshard message and then sends a bare CoreAdmin CREATE (name/collection/shard only) through sendShardRequest. It never registers a replica in cluster state and never sets a coreNodeName. The sub-shard replica CREATE at :1468-1486 has the same gap. The CREATE lands in CoreAdminHandler.java:557-560 (ZkController present, !isLegacy, coreNodeName==null) and throws. The fix hunks @@ -1332 and @@ -1463 remove exactly these bare CREATE requests: they wait for the new slice (waitForNewShard) and then go through addReplica, which registers the replica and passes its coreNodeName. validate-1.log line 2650 shows the rejected CREATE for collection1_shard1_0_replica1 coming from the Overseer's splitshard.

**Realistic?** Yes. The trigger is ordinary: a mini cluster (ShardSplitTest's setup), an admin setting the supported cluster property legacyCloud=false through the Collections API, and a normal SPLITSHARD request. There is no reflection, no mocking and no fault injection. The fix's own test change in ShardSplitTest sets the same property in the same way.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **NOT_REPRODUCED**. On the buggy tree plus the fix's production changes, the same test passed in 4 of 4 runs (BUILD SUCCESSFUL), and 'coreNodeName missing' appears in none of the fixed logs. On the buggy tree it reproduced on the first run (the check's exception at CoreAdminHandler.java:560).

**Reason:** The agent's test hits the exact defect SOLR-6101 fixes: with legacyCloud=false, SPLITSHARD creates sub-shard cores through a core-admin CREATE that has no coreNodeName, because the Overseer has not registered the replica first. The trigger is realistic, and the consequence matches the JIRA (shard splitting does not work with legacyCloud=false). The fixed version no longer fails.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The CREATE request that the check rejects is not user input. The Overseer builds it during its own coordination of SPLITSHARD. In non-legacy ('ZooKeeper is the truth') mode the protocol says the Overseer must create the replica entry in clusterstate first, then pass its coreNodeName in the CoreAdmin CREATE. createCollection and addReplica do this, but the sub-shard leader and sub-shard replica CREATE requests in splitShard do not. So the check correctly enforces the invariant, and the Overseer's split coordination breaks it. Consequence in a real deployment: once an operator turns on legacyCloud=false, a supported cluster property, SPLITSHARD always fails. Shards can no longer be split to scale out. Every attempt also leaves the empty sub-shard slices (shard1_0/shard1_1) in 'construction' state in clusterstate until the next attempt deletes them. That next attempt (OverseerCollectionProcessor.splitShard deletes existing construction sub-shards) then fails again at the same check, so with legacyCloud=false a shard can never be split.

**Execution (agent):** 1) Start the same SolrCloud as ShardSplitTest (ZK, control node and the jetty nodes holding collection1, with shard1 and shard2), and wait for it to level out. 2) An admin sets the supported cluster property legacyCloud=false through the Collections API (CLUSTERPROP). The Overseer writes it to /clusterprops.json, so from now on every node's Overseer.isLegacy(clusterProps) returns false. 3) A client sends SPLITSHARD collection=collection1 shard=shard1. 4) The Overseer Collection Processor (OverseerCollectionProcessor.splitShard) puts a 'createshard' message for shard1_0 and shard1_1 (state=construction) on the Overseer queue. It then sends a CoreAdmin CREATE (name=collection1_shard1_X_replica1, collection, shard) to the parent leader's node. In non-legacy mode it never first registers the replica in clusterstate (no ADDREPLICA message, no waitToSeeReplicasInState) and never sets coreNodeName. The CREATE paths for CREATE collection and ADDREPLICA do both. 5) On the receiving node, CoreAdminHandler.handleCreateAction sees a ZkController, legacyCloud=false and cloudDescriptor.getCoreNodeName()==null, so it throws SolrException('non legacy mode coreNodeName missing ...') at CoreAdminHandler.java:560. That exception is wrapped as 'Error CREATEing SolrCore' and returned to the Overseer. 6) The Overseer fails the split with 'SPLITSHARD failed to create subshard leaders', and the client gets a RemoteSolrException. No fault injection or special timing is needed: it happens on every run, for every seed tried. The same request split shard1 successfully in ShardSplitTest, where legacyCloud is unset.

**Stack frame (agent):** at org.apache.solr.handler.admin.CoreAdminHandler.handleCreateAction(CoreAdminHandler.java:560)

## Reproduction

- Test: `org.apache.solr.cloud.ShardSplitNonLegacyCloudTest#testDistribSearch`
- Command: `source /bulk/codingagent/cases/solr-adhoc-k2/agent/env.sh && cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=ShardSplitNonLegacyCloudTest -Dtests.method=testDistribSearch -Dtests.jvms=1 -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib`
- Test files (in `repro/`, paths relative to the system's tree): `solr/core/src/test/org/apache/solr/cloud/ShardSplitNonLegacyCloudTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `[junit4]   2> 	Caused by: org.apache.solr.common.SolrException: non legacy mode coreNodeName missing shard=shard1_0&version=2&name=collection1_shard1_0_replica1&action=CREATE&qt=/admin/cores&collection=collection1&wt=javabin`, frame `[junit4]   2> 		at org.apache.solr.handler.admin.CoreAdminHandler.handleCreateAction(CoreAdminHandler.java:560)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h06m | 1 | 533,866 | 30 | 8,861 | 41,429 | 483,546 | $0.61 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
