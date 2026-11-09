# solr-adhoc-31: In perReplicaState collections, a crashed leader's PRS entry stays 'active, leader' because the clear-leader message does not change PRS entries, so FORCELEADER on the leaderless shard is rejected with 'already has an active leader'.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `solr/core/src/java/org/apache/solr/handler/admin/CollectionsHandler.java:1477`, `CollectionsHandler.forceLeaderElection(SolrQueryRequest, CollectionsHandler)`, throws `org.apache.solr.common.SolrException` when `leader != null && leader.getState() == State.ACTIVE   (leader = slice.getLeader(); slice = zkController.getClusterState().getCollection(collectionName).getSlice(sliceId))`
- Starting test: `org.apache.solr.cloud.ForceLeaderTest#testReplicasInLowerTerms`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** perReplicaState collection, 1 shard x 3 replicas. A network partition leaves the followers in a lower term, then the leader node crashes (ZK session closed, process stopped without publishing DOWN). With the production leaderVoteWait the shard is leaderless, and the operator issues FORCELEADER.

**Why (root cause in the source):** The election candidate's 'clear leader' message (ShardLeaderElectionContext.java:115-119) is applied by SliceMutator.setShardLeader through the two-argument ZkWriteCommand constructor (SliceMutator.java:177-178). For PRS collections that constructor only attaches PerReplicaStatesOps.touchChildren() (ZkWriteCommand.java:44-47), which adds and removes a dummy entry. Replica.isLeader()/getState() for PRS read the per-replica entries (Replica.java:218,241-244), so the dead node's entry stays active+leader. CollectionsHandler.forceLeaderElection then sees slice.getLeader() active and refuses (CollectionsHandler.java:1475-1478) without checking live nodes. The same scenario on a state.json collection clears the leader and FORCELEADER proceeds. As a result the documented remedy for a leaderless shard cannot be used on PRS collections, and the shard stays without a live leader (writes fail) until leaderVoteWait expires or the dead node returns.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The check is supposed to reject FORCELEADER only when the shard really has a working active leader. Here the 'active leader' is a replica whose node is dead (not in live_nodes), and only stale coordination state says it is active. Two coordination paths fail to remove that state. First, a crashed node cannot publish its replicas DOWN. Second, for perReplicaState collections, the 'clear leader' message from the next election candidate is a no-op on the PRS entries, which are the source of Replica.getState()/isLeader(). The check also never looks at liveNodes. A correct coordination would have cleared the leader flag, as it does for state.json collections in the same execution. Consequence in a real deployment: after a leader node crashes while its followers are behind (lower term, e.g. after a network blip), a PRS collection's shard has no leader on any live node and rejects all updates for up to leaderVoteWait (3 min by default, often set higher). FORCELEADER, the documented remedy for a leaderless shard, refuses to run, and the 'active leader' stays on a dead node until the lower-term replica takes over after the timeout or the crashed node returns. Meanwhile clients reading the PRS state keep routing updates to the dead leader.

**Execution (agent):** Setup is the same as ForceLeaderTest (HttpPartitionTest, 4 jettys behind SocketProxies) plus leaderVoteWait=180000, the production default (CloudConfig.DEFAULT_LEADER_VOTE_WAIT), instead of the 15s test value. (1) Create collection 1 shard x 3 NRT replicas with perReplicaState=true; leader A, followers B and C. (2) Index doc 1. (3) HTTP partition: close the SocketProxies of A, B and C. Doc 2 is sent directly to A. A cannot forward it, raises its term above B's and C's (ZkShardTerms), and B and C go DOWN. (4) Node A crashes: its ZK session ends (SolrZkClient closed, so A's live_node and election ephemerals disappear) and the process stops without publishing DOWN. ZkController.preClose -> publishNodeAsDown fails with SessionExpired ('Error publishing nodes as down'), exactly as with kill -9 or power loss. (5) The partition heals. B, then C, becomes head of the shard election. ShardLeaderElectionContext.runLeaderProcess sends the Overseer 'LEADER' message that should clear the old leader. For a PRS collection, SliceMutator.setShardLeader yields a ZkWriteCommand whose PRS ops are only touchChildren(), so A's per-replica entry stays 'core_nodeA:1:A:L' (active + leader). B and C have lower terms, so they wait up to leaderVoteWait and do not become leader. The shard is leaderless and has no leader on a live node. Observed state ~11s after the crash: live nodes exclude A's node, yet the PRS states are [core_node5:1:D, core_node4:1:A:L, core_node6:1:D] with core_node4 = the crashed A. (6) The operator sends FORCELEADER for shard1 to a live node. forceLeaderElection reads slice.getLeader() = A with getState()==ACTIVE (from PRS) and throws SolrException 'The shard already has an active leader. Force leader is not applicable' at CollectionsHandler.java:1477. The client gets a RemoteSolrException and the test fails with it. Contrast: testForceLeaderAfterLeaderCrash runs the same execution with a regular (state.json) collection. There the election's LEADER message clears A's leader flag, slice.getLeader() is null, and FORCELEADER passes the check (that test passes).

**Stack frame (agent):** at org.apache.solr.handler.admin.CollectionsHandler.forceLeaderElection(CollectionsHandler.java:1477) ~[java/:?]

## Reproduction

- Test: `org.apache.solr.cloud.ForceLeaderCrashedLeaderTest#testForceLeaderAfterLeaderCrashPerReplicaState`
- Command: `source /bulk/codingagent/cases/solr-adhoc-31/agent/env.sh && cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=ForceLeaderCrashedLeaderTest -Dtests.method=testForceLeaderAfterLeaderCrashPerReplicaState -Dtests.jvms=1 -Dtests.nightly=true -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib`
- Test files (in `repro/`, paths relative to the system's tree): `solr/core/src/test/org/apache/solr/cloud/ForceLeaderCrashedLeaderTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `[junit4]   2> org.apache.solr.common.SolrException: The shard already has an active leader. Force leader is not applicable. State: shard1:{`, frame `[junit4]   2> 	at org.apache.solr.handler.admin.CollectionsHandler.forceLeaderElection(CollectionsHandler.java:1477) ~[java/:?]`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h19m | 1 | 2,012,308 | 66 | 32,413 | 88,733 | 1,891,096 | $1.74 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
