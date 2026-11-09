# solr-adhoc-10: TimeRoutedAlias.validateRouteValue writes router.start from a stale Aliases snapshot onto whatever the alias currently is, so it corrupts a replacement plain alias (and can overwrite concurrent alias changes); MAINTAINROUTEDALIAS then fails with 'called on non-routed alias'.

Severity (reviewer): **data-loss**

## The ad hoc check (the prompt's only target)

- `solr/core/src/java/org/apache/solr/cloud/api/collections/MaintainRoutedAliasCmd.java:117`, `MaintainRoutedAliasCmd.call(ClusterState, ZkNodeProps, NamedList)`, throws `org.apache.solr.common.SolrException` when `ra == null   (ra = RoutedAlias.fromProps(aliasName, aliasMetadata); aliasMetadata = ocmh.zkStateReader.aliasesManager.getAliases().getCollectionAliasProperties(aliasName), non-empty)`
- Starting test: `org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#test`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** A streaming (chunked) update to a time routed alias with a date-math router.start is in flight when an admin replaces the TRA with a plain alias of the same name (DELETEALIAS + CREATEALIAS); the next documents of that request are still processed with the stale RoutedAlias.

**Why (root cause in the source):** Ordinary concurrent client and admin operations are enough. On the first document, TimeRoutedAlias.validateRouteValue (TimeRoutedAlias.java:376-387) copies the alias's current props, adds router.start, and asynchronously writes them with a lambda that ignores the fresh Aliases argument and applies the change to a captured snapshot. So Solr itself writes router.start onto the user's new plain alias (validate-1.log:2636/2786 show collectionAliasProperties={myalias={router.start=...}} persisting), and the same stale-snapshot write can revert any concurrent aliases.json change. The plain alias now has non-empty props but no router.name, so MaintainRoutedAliasCmd passes the empty check and RoutedAlias.fromProps returns null, throwing at MaintainRoutedAliasCmd.java:116-117. The lasting damage is the corrupt alias metadata, which also makes Aliases.isRoutedAlias (Aliases.java:216, prefix match on router.) report the plain alias as routed and changes later CREATEALIAS/CollectionsHandler behaviour (CreateAliasCmd.java:144, CollectionsHandler.java:667).

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The node's update processor and the Overseer coordinate the alias's type and properties only through aliases.json. The node keeps a RoutedAlias built at request start and never re-checks that the alias is still routed. Worse, TimeRoutedAlias.validateRouteValue writes router.start back onto whatever the alias currently is, using a stale snapshot (it ignores the fresh Aliases passed to applyModificationAndExportToZk). So Solr itself turns a user-created plain alias into a corrupt hybrid: a plain alias carrying a router.* property but no router.name. A correct coordination would leave the plain alias with no properties. Even a node acting on stale state would then get the clean BAD_REQUEST 'does not exist or is not a routed alias' (line 112). Instead the check at line 117 fires with a SERVER_ERROR that claims an internal inconsistency. Consequences in a real deployment: an admin who converts or replaces a TRA while a client streams or batches updates finds that (a) documents in the in-flight request fail with a 500-class 'MaintainRoutedAlias called on non-routed alias' error, and (b) the new plain alias permanently carries a stray router.start property they never set. That property shows up in LISTALIASES, and because the write is a stale-snapshot overwrite, it can also silently revert any other aliases.json changes made in between (a lost update).

**Execution (agent):** 2-node MiniSolrCloudCluster (one node is Overseer). (1) Admin creates a time routed alias 'myalias' with router.start=NOW/DAY (date math, which Solr resolves lazily on the first document), router.interval=+1DAY, router.maxFutureMs=2 days; initial collection myalias__TRA__<today> (1 shard, 1 replica on node A). (2) A slow/streaming client opens a chunked JSON update POST /solr/myalias__TRA__<today>/update on node A and sends only '['. Jetty dispatches it: ContentStreamHandlerBase creates the update chain, and RoutedAliasUpdateProcessor.wrap() builds a TimeRoutedAlias from the alias props that are current at that moment (routed, start=NOW/DAY). The JSON loader then blocks waiting for the rest of the body. (3) Concurrently an admin replaces the TRA with a plain alias of the same name: DELETEALIAS myalias (this removes all alias properties), then CREATEALIAS myalias collections=myalias__TRA__<today>. All nodes now see a plain alias with no properties. (4) The first document (timestamp=now) arrives. TimeRoutedAlias.validateRouteValue, still using the stale routed RoutedAlias, sees the date-math start, copies the CURRENT alias props from zkStateReader ({} for the plain alias), adds router.start=<today>T00:00:00Z, and core.runAsync() writes that into aliases.json. The lambda ignores its argument and applies the change to a snapshot. The plain alias is now {router.start=...}: non-empty properties but no router.name. (5) The second document (timestamp=now+1 day) belongs to a collection that does not exist yet, so the stale RoutedAlias picks SYNCHRONOUS creation and RoutedAlias.ensureCollection sends MAINTAINROUTEDALIAS(myalias, myalias__TRA__<tomorrow>) to the Overseer. (6) In the Overseer, MaintainRoutedAliasCmd.call reads aliasMetadata={router.start=...}. That is non-empty, so the line-111 check passes, but RoutedAlias.fromProps returns null because router.name is missing, so the code throws SolrException(SERVER_ERROR, 'MaintainRoutedAlias called on non-routed alias') at MaintainRoutedAliasCmd.java:117. Document 2 is rejected with that message. The test passed in 4 out of 4 runs.

**Stack frame (agent):** at org.apache.solr.cloud.api.collections.MaintainRoutedAliasCmd.call(MaintainRoutedAliasCmd.java:117)

## Reproduction

- Test: `org.apache.solr.update.processor.TimeRoutedAliasReplacedByPlainAliasTest#testStaleRoutedAliasWritesStartOntoPlainAlias`
- Command: `source /bulk/codingagent/cases/solr-adhoc-10/agent/env.sh && cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=TimeRoutedAliasReplacedByPlainAliasTest -Dtests.method=testStaleRoutedAliasWritesStartOntoPlainAlias -Dtests.jvms=1 -Dtests.awaitsfix=true -Dargs='-XX:TieredStopAtLevel=1 -Dsolr.disableConfigSetsCreateAuthChecks=true' -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib`
- Test files (in `repro/`, paths relative to the system's tree): `solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasReplacedByPlainAliasTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `[junit4]   2>           => org.apache.solr.common.SolrException: MaintainRoutedAlias called on non-routed alias`, frame `[junit4]   2> 	at org.apache.solr.cloud.api.collections.MaintainRoutedAliasCmd.call(MaintainRoutedAliasCmd.java:117)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h10m | 1 | 2,166,838 | 68 | 33,380 | 90,302 | 2,043,088 | $1.80 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
