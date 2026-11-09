# SOLR-9440 (Client caches stale state): not detected

Case `solr-adhoc-k1`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `solr/test-framework/src/java/org/apache/solr/cloud/AbstractDistribZkTestBase.java:185`, `AbstractDistribZkTestBase.waitForRecoveriesToFinish(String, ZkStateReader, boolean, boolean, int)`, throws `java.lang.AssertionError` when `sawLiveRecovering && cnt == timeoutSeconds && failOnTimeout   (sawLiveRecovering: a slice of zkStateReader.getClusterState().getCollectionOrNull(collection) is in CONSTRUCTION, or a replica on a live node is RECOVERING, DOWN or RECOVERY_FAILED; fail(...) from org.junit.Assert)`
- Starting test: `org.apache.solr.cloud.TestCloudRecovery#leaderRecoverFromLogOnStartupTest`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** no

**What the agent found:** A SPLITSHARD that fails because the parent-leader node is stopped right after CREATESHARD leaves sub-shard shard1_0 in CONSTRUCTION in state.json for good (SplitShardCmd does no rollback), so waitForRecoveriesToFinish sees a CONSTRUCTION slice on every poll and times out at AbstractDistribZkTestBase.java:185.

**Same root cause as SOLR-9440?** No. The agent's failure comes from SplitShardCmd (solr/core/src/java/org/apache/solr/cloud/SplitShardCmd.java:266 creates the sub-shard as CONSTRUCTION; the later addReplica at :298 throws 'At least one of the node(s) specified are not currently active' and the command rethrows with no cleanup). The CONSTRUCTION slice really is in ZooKeeper: the printLayoutToStdOut dump in logs/validate-1.log (around line 4099) shows "state":"construction" in state.json. So the client is not seeing stale cached state. SOLR-9440's defect is in ZkStateReader.removeCollectionStateWatcher (solr/solrj/.../ZkStateReader.java, hunk @@ -1340): when the last watcher is removed, the entry is dropped from collectionWatches but the DocCollection stays in watchedCollectionStates and is never replaced by a LazyCollectionRef, so the client's ClusterState stays frozen. The fix adds watchedCollectionStates.remove, lazyCollectionStates.put(new LazyCollectionRef) and constructState. The agent's test never relies on a watcher being removed and then on the client's view going stale; its waitForState calls only feed correct data.

**Realistic?** Yes, as a trigger for its own bug: an ordinary async SPLITSHARD plus stopping and restarting a node with ChaosMonkey in a MiniSolrCloudCluster. The TestInjection core-creation delay never fired. It is a plausible different bug (no cleanup of sub-shards after a failed split, which later Solr versions addressed), not SOLR-9440.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **REPRODUCED**. Still reproduces on the fixed tree: logs/validate-fixed-1.log shows shard1_0 state=construction and the same AssertionError at AbstractDistribZkTestBase.java:185. That fits a defect the SOLR-9440 fix does not touch, and this fix prevents the stale state rather than handling the exception.

**Reason:** The check fails because a failed split leaves a real CONSTRUCTION slice in ZooKeeper, not because ZkStateReader serves a stale cached DocCollection after removeCollectionStateWatcher. The root cause is in SplitShardCmd's missing failure cleanup, which the SOLR-9440 fix does not change, and the failure persists on the fixed version. So it does not detect SOLR-9440.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Slice state CONSTRUCTION is ad hoc coordination between the Overseer's SplitShardCmd and the update path. It means 'this sub-shard is being built and the parent leader must forward updates to it'. The split protocol is supposed to move the slice on to ACTIVE (or RECOVERY then ACTIVE), or mark it RECOVERY_FAILED; the code already does the latter only when it notices a parent-leader change just before replica creation. A crash or restart of the parent leader's node, or any single failed core-admin request, between CREATESHARD and the end of the split makes SplitShardCmd throw without rolling back. The sub-shard is then left in CONSTRUCTION for good, even after the node is back and healthy. That is a state the coordination should never leave behind once the operation that owned it has ended (as FAILED). A node going down during a long split is an ordinary event in production. Consequences: the collection never reports 'recovered' to tooling that waits on slice and replica states; ghost sub-slices stay in state.json; DistributedUpdateProcessor keeps treating them as sub-shards under construction and forwards parent updates to any leader they get (for example, when the sub-shard leader core was created before the crash, it comes back after restart and keeps receiving and indexing parent documents forever); and DELETESHARD or another SPLITSHARD attempt is the only way out, which nobody triggers automatically. As far as I recall (not checked against this tree), later Solr versions added cleanup of sub-shards after a failed split (SOLR-11665), which would acknowledge this as a bug.

**Execution (agent):** Cluster: 2 Solr nodes plus ZK (same setup as TestCloudRecovery: StandardDirectoryFactory, ulog.numRecordsToKeep=1000, cloud-minimal config). Node O is the Overseer; node D is the other node. (1) Create collection 'splitcrash' with 1 shard and 1 NRT replica on D. waitForRecoveriesToFinish passes. Index 20 docs and commit. (2) A client sends SPLITSHARD shard1 (async). The Overseer on O runs SplitShardCmd. It enqueues CREATESHARD for sub-shard shard1_0 with state CONSTRUCTION, waits for it to appear in state.json, then calls addReplica to create the sub-shard leader on the parent leader's node D. (3) As soon as shard1_0 shows up in CONSTRUCTION, node D (which hosts the parent shard leader) goes down (ChaosMonkey.stop). (4) The split's next step fails: in these runs it was addReplica -> Assign.getNodeNameVsShardCount -> 'At least one of the node(s) specified are not currently active'. Had D gone down slightly later, the same thing would happen at the sub-shard core CREATE, WaitForState, SPLIT or REQUESTAPPLYUPDATES request. SplitShardCmd rethrows the exception with no cleanup, and the async request ends FAILED. (5) Node D restarts. The parent shard1 is ACTIVE with an ACTIVE live leader, and all 20 docs can be queried. (6) Nothing is recovering and no faults remain, yet state.json still has slice shard1_0 in state 'construction' (with no replicas) and nothing ever removes it. waitForRecoveriesToFinish(splitcrash, ..., failOnTimeout=true, 60) sees a CONSTRUCTION slice on every poll (sawLiveRecovering=true) and fails at AbstractDistribZkTestBase.java:185 with 'There are still nodes recoverying - waited for 60 seconds'. Reproduced on 3 of 3 runs with different seeds (DDD67597EEC30B07, 67A63FD5BF89958B, A645C9A0E6E105DD). TestInjection.randomDelayInCoreCreation is set to widen the window, but it never fired in these runs because the split failed before any sub-shard core was created.

**Stack frame (agent):** at org.apache.solr.cloud.AbstractDistribZkTestBase.waitForRecoveriesToFinish(AbstractDistribZkTestBase.java:185)

## Reproduction

- Test: `org.apache.solr.cloud.TestCloudRecoverySplitCrash#parentLeaderNodeRestartDuringSplitTest`
- Command: `source /bulk/codingagent/cases/solr-adhoc-k1/agent/env.sh && cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=TestCloudRecoverySplitCrash -Dtests.method=parentLeaderNodeRestartDuringSplitTest -Dtests.jvms=1 -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib`
- Test files (in `repro/`, paths relative to the system's tree): `solr/core/src/test/org/apache/solr/cloud/TestCloudRecoverySplitCrash.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `[junit4]    > Throwable #1: java.lang.AssertionError: There are still nodes recoverying - waited for 60 seconds`, frame `[junit4]    > 	at org.apache.solr.cloud.AbstractDistribZkTestBase.waitForRecoveriesToFinish(AbstractDistribZkTestBase.java:185)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h17m | 1 | 8,292,408 | 142 | 64,975 | 174,788 | 8,052,503 | $4.31 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
