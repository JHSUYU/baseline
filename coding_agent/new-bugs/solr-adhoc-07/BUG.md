# solr-adhoc-07: One lost REQUESTSTATUS poll makes the Overseer report ADDREPLICA FAILED and release the collection lock while the core is still being created, so a cleanup DELETEREPLICA races the registration (register aborts, instance dir is left behind).

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `solr/core/src/java/org/apache/solr/cloud/ZkController.java:1326`, `ZkController.register(String, CoreDescriptor, boolean, boolean, boolean)`, throws `org.apache.solr.common.SolrException` when `core == null   (core = cc.getCore(desc.getName()), in try (SolrCore core = ...))`
- Starting test: `org.apache.solr.cloud.AddReplicaTest#testAddMultipleReplicas`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** During an async ADDREPLICA, one CoreAdmin REQUESTSTATUS poll from the Overseer to the target node fails with HTTP 503 while the core's registration is still running (held by a latch until it is unloaded); the Overseer reports the ADDREPLICA FAILED and releases the collection lock, and the client's follow-up DELETEREPLICA unloads the core mid-register.

**Why (root cause in the source):** A single failed status poll is turned straight into STATUS=failed with no retry (OverseerCollectionMessageHandler.java:867-870), so ADDREPLICA is reported FAILED and the per-collection lock is released while the async CREATE/registration is still running on the node. A later collection operation (DELETEREPLICA) then overlaps the unfinished registration, which the Overseer's serialization is supposed to prevent, and register finds the core gone at ZkController.java:1325-1326. The triggers (one failed RPC, a slow registration, an ordinary client cleanup) are realistic. The consequences are an ADDREPLICA wrongly reported as failed (without cleanup it silently yields a working replica), an ERROR/DOWN publish, and an UNLOAD that cannot delete the core's instance dir (validate-1.log:2642). The check's own abort is benign; the defect is the premature FAILED and lock release it exposes, and it is recoverable by retrying.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The check rejects state that the coordination should never produce: a core whose registration is in progress gets unloaded by a collection operation that the Overseer serializes per collection. The Overseer guarantees that collection operations on one collection don't overlap: ADDREPLICA holds the collection lock until the core is created and registered. One failed REQUESTSTATUS HTTP request, a transient network error or a 503 from a busy node, is enough for the Overseer to declare the replica creation failed while the CREATE is still running on the target node. The lock is released and a follow-up operation (DELETEREPLICA, DELETE collection, or a retry) runs concurrently with the unfinished registration. In a real deployment a lost status poll and slow core registration (ZK latency, GC, leader waits) both happen. The client is told the ADDREPLICA failed even though the core was created. Cleaning up as the API invites then races with the registration: register() throws, the node publishes a DOWN state for a replica that is being deleted, its shard term and election node are recreated and torn down again, and the UNLOAD cannot delete the core's instance directory, which the log shows. From the code, CoreContainer.create also goes on to call coresLocator.persist for the core after the failed registration; I did not verify this in the log. Without the cleanup, the 'failed' operation silently produces a working replica, so the result the client got is wrong either way. The check fails because of the Overseer's async-status coordination, not because a user request was invalid: the DELETEREPLICA is a valid request against a replica that the Overseer reported as belonging to a finished, failed operation.

**Execution (agent):** Cluster: 3 Solr nodes (MiniSolrCloudCluster, same setup as AddReplicaTest). The collection has 1 shard and 2 replicas on nodes N1 (leader) and N2. Node N3 is empty. 1) The client sends an async ADDREPLICA (processAndWait, as in AddReplicaTest) for shard1 with node=N3. The Overseer adds core_node6 to the cluster state and sends an async CoreAdmin CREATE to N3. 2) On N3 the core is built and put into the CoreContainer, and CoreContainer.registerCore -> ZkContainer.registerInZk starts the synchronous ZK registration. An ordering latch (ZkContainer.testing_beforeRegisterInZk) models a registration that runs slower than the Overseer's polling: it holds the registration until the core starts being unloaded. 3) The Overseer polls N3 with CoreAdmin REQUESTSTATUS. One poll fails: a test servlet filter returns HTTP 503, a single failed or lost request. In OverseerCollectionMessageHandler.waitForCoreAdminAsyncCallToComplete, a poll without a response is not retried. It is turned straight into STATUS=failed, so the ADDREPLICA finishes as FAILED and the collection lock is released, although the CREATE is still running on N3. 4) The client sees FAILED and cleans up the replica left by the failed operation with DELETEREPLICA core_node6. The Overseer sends UNLOAD to N3, and CoreContainer.unload removes the core from the container and closes it. 5) The register() for the same core continues on N3. The replica is still in N3's view of the cluster state, so register re-adds its shard term, joins the leader election and finds the leader N1. It then calls cc.getCore(name), which returns null, and throws SolrException 'SolrCore is no longer available to register' at ZkController.java:1326. registerInZk logs the exception and publishes the deleted replica as DOWN. In the log, the concurrent UNLOAD also reports 'Failed to delete instance dir' for the core. The test captures the logged exception and fails with it as the cause. It reproduced in 3 of 3 runs.

**Stack frame (agent):** at org.apache.solr.cloud.ZkController.register(ZkController.java:1326)

## Reproduction

- Test: `org.apache.solr.cloud.AddReplicaLostStatusRegisterTest#testLostRequestStatusDuringAddReplica`
- Command: `source /bulk/codingagent/cases/solr-adhoc-07/agent/env.sh && cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=AddReplicaLostStatusRegisterTest -Dtests.method=testLostRequestStatusDuringAddReplica -Dtests.jvms=1 -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib`
- Test files (in `repro/`, paths relative to the system's tree): `solr/core/src/test/org/apache/solr/cloud/AddReplicaLostStatusRegisterTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `[junit4]   2>           => org.apache.solr.common.SolrException: SolrCore is no longer available to register`, frame `[junit4]   2> 	at org.apache.solr.cloud.ZkController.register(ZkController.java:1326)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h12m | 1 | 3,806,307 | 100 | 47,503 | 124,777 | 3,633,927 | $2.68 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
