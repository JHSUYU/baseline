# solr-adhoc-13: A routed-alias update does not refresh TRA properties during a request (contrary to the ref guide), so a concurrent ALIASPROP router.interval change makes the Overseer create a different collection and the batch fails with 'After we attempted to create X it did not exist'.

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `solr/core/src/java/org/apache/solr/cloud/api/collections/RoutedAlias.java:350`, `RoutedAlias.doSynchronous(AddUpdateCommand, CandidateCollection, CoreContainer)`, throws `org.apache.solr.common.SolrException` when `!observedCols.contains(targetCollectionDesc.creationCollection)   (observedCols = zkController.zkStateReader.aliasesManager.getAliases().getCollectionAliasListMap().get(getAliasName()), after updateParsedCollectionAliases(zkController.zkStateReader, true))`
- Starting test: `org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** An update batch to a TRA is paused (TestInjection.directUpdateLatch, standing in for slow indexing) after its RoutedAliasUpdateProcessor was built with router.interval=+1DAY; meanwhile an admin runs ALIASPROP router.interval=+1HOUR, and then the batch's next document needs a new collection.

**Why (root cause in the source):** The triggers (a delayed request and a concurrent, documented ALIASPROP change) are realistic. RAUP keeps the TRA configuration it read at request start, although aliases.adoc:119-121 says it checks for property changes per document, so it asks MAINTAINROUTEDALIAS for myalias__TRA__2017-10-24. The Overseer rebuilds the TRA from the current props (MaintainRoutedAliasCmd.java:116) and calcAdd creates 'the next one' under the new interval (TimeRoutedAlias.java:601-603, whose own comment says it 'may or may not be the same as our target'). It returns success, and doSynchronous then bails with SERVER_ERROR because its stale target is absent (RoutedAlias.java:348-351) instead of recomputing the candidate as the surrounding loop is built to do. The whole valid batch is rejected with a 500. A client retry with a fresh processor should succeed, and the extra collection is legitimate under the new interval, so the impact is limited.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The requesting node and the Overseer coordinate which collection gets created, but each derives it from its own snapshot of the routed-alias configuration. RAUP takes its snapshot once per request and never refreshes it. That contradicts the ref guide (aliases.adoc: 'As it sees each document, it checks for changes to TRA properties, updates its cached configuration if needed'). The Overseer always uses the current configuration. Both the update request and the ALIASPROP change are valid and documented, and they can overlap in any live deployment: long streaming batches, or a node whose alias watch has not yet delivered the change. So the Overseer reports success for a create it did not do, and creates a different collection instead. Consequences: valid documents are rejected with a 500 server error, and the Overseer adds a collection nobody requested. MaintainRoutedAliasCmd's own comment says the result 'may or may not be the same as our target', and createAllRequiredCollections claims 'we'll ultimately retry'. Yet doSynchronous does not re-check against the current config. It bails out.

**Execution (agent):** 2-node MiniSolrCloudCluster. (1) Create TRA 'myalias' with start 2017-10-23T00:00:00Z, interval +1DAY, 1 shard x 1 replica; the alias holds [myalias__TRA__2017-10-23]. (2) A client sends ONE update batch to the alias with doc1 (2017-10-23T01:00Z, belongs to the existing collection) and doc2 (2017-10-24T01:00Z, needs synchronous creation of the next collection). RoutedAliasUpdateProcessor.wrap() builds the TimeRoutedAlias for this request from the alias properties as they are now (interval +1DAY). TestInjection.directUpdateLatch pauses the request while it indexes doc1 in DirectUpdateHandler2 (it stands in for an ordinary slow indexing step or a long streaming batch). (3) While the batch is in flight, an admin runs a concurrent, legal ALIASPROP router.interval=+1HOUR (the ref guide says these settings can be edited later with ALIASPROP). The Overseer writes it to aliases.json. (4) The batch continues with doc2. Its stale TimeRoutedAlias (+1DAY) computes creationCollection=myalias__TRA__2017-10-24 and sends MAINTAINROUTEDALIAS(target=...2017-10-24) to the Overseer. (5) MaintainRoutedAliasCmd rebuilds the TimeRoutedAlias from the CURRENT properties (+1HOUR). calcAdd sees the target is not in the alias and creates 'the next one' after the head, myalias__TRA__2017-10-23_01, adds it to the alias and returns success. (6) The requester runs aliasesManager.update() and reads the list [..2017-10-23_01, ..2017-10-23]. It does not contain ..2017-10-24, so RoutedAlias.doSynchronous throws SolrException('After we attempted to create myalias__TRA__2017-10-24 it did not exist') at RoutedAlias.java:350. The whole batch fails with HTTP 500.

**Stack frame (agent):** at org.apache.solr.cloud.api.collections.RoutedAlias.doSynchronous(RoutedAlias.java:350) ~[java/:?]

## Reproduction

- Test: `org.apache.solr.update.processor.TimeRoutedAliasConcurrentPropChangeTest#testIntervalChangeDuringUpdateBatch`
- Command: `source /bulk/codingagent/cases/solr-adhoc-13/agent/env.sh && cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=TimeRoutedAliasConcurrentPropChangeTest -Dtests.method=testIntervalChangeDuringUpdateBatch -Dtests.jvms=1 -Dtests.awaitsfix=true -Dargs='-XX:TieredStopAtLevel=1 -Dsolr.disableConfigSetsCreateAuthChecks=true' -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib -Dtests.showOutput=always`
- Test files (in `repro/`, paths relative to the system's tree): `solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasConcurrentPropChangeTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `[junit4]   2>           => org.apache.solr.common.SolrException: After we attempted to create myalias__TRA__2017-10-24 it did not exist`, frame `[junit4]   2> 	at org.apache.solr.cloud.api.collections.RoutedAlias.doSynchronous(RoutedAlias.java:350)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h10m | 1 | 2,386,988 | 62 | 50,119 | 117,074 | 2,219,733 | $2.38 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
