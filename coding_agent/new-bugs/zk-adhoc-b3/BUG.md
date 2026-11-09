# zk-adhoc-b3: A stale ContainerManager deleteContainer request deletes a PERSISTENT node re-created at the same path, because deleteContainer does not re-check that the target is still a container or TTL node.

Severity (reviewer): **data-loss**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/FinalRequestProcessor.java:674`, `FinalRequestProcessor.handleGetDataRequest(Record, ServerCnxn, List<Id>)`, throws `org.apache.zookeeper.KeeperException.NoNodeException` when `n == null   (n = zks.getZKDatabase().getNode(path))`
- Starting test: `org.apache.zookeeper.server.TestAdhocWorkloadB3#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** ContainerManager scans and picks an empty container as a candidate; its deleteContainer request is posted late (a delay in postDeleteRequest standing in for pacing, GC or a queue backlog). Meanwhile the client deletes the container and re-creates the same path as a PERSISTENT node with data.

**Why (root cause in the source):** ContainerManager.checkContainers builds deleteContainer requests from a candidate list computed earlier and paced over time (ContainerManager.java:140-159). When the request is processed, PrepRequestProcessor checks only childCount==0 and that the node is not a session ephemeral (PrepRequestProcessor.java:326-338). It never checks that the node is still a container or TTL node, or that it is the same node (czxid). The stale request therefore deletes the user's new PERSISTENT node, and the client's later getData on a node it never deleted fails at FinalRequestProcessor.java:673-674. This is silent loss of user data caused by a server-initiated request.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The container manager is supposed to delete only empty CONTAINER (or expired TTL) nodes. Its scan and its delete are not atomic. When the deleteContainer request is processed, PrepRequestProcessor does not re-check that the node at the path is still a container (or TTL), or that it is the same node the scan saw (e.g. same czxid). A legitimate client sequence (delete the container, re-create the path as PERSISTENT) racing with a pending cleanup therefore silently deletes a persistent node the user created. No client issued that delete. The user's later reads fail with NoNodeException, here at the ad hoc check in handleGetDataRequest, for a node that by ZooKeeper's semantics must exist. In a real deployment this is silent loss of persistent data and the znode's metadata. Recipes that turn a container into a persistent node, or reuse paths, break unpredictably. The window grows with the number of container candidates (deletions are paced by znode.container.maxPerMinute), load and GC pauses. The same race exists on a quorum leader, whose ContainerManager posts to the leader's request pipeline.

**Execution (agent):** Standalone ZooKeeper server (ClientBase), one client session, and a ContainerManager like the starting test's: it checks once 100 ms after start, with a delay between its scan and posting the deleteContainer request. That delay stands in for the gap between scan and processing in a real deployment: maxPerMinute pacing across many candidates, a GC pause, or a long request queue. 1) The client creates CONTAINER /adhoc-workload-b3, creates and deletes a child, which leaves the container empty with cversion>0. 2) The ContainerManager scans (getCandidates), picks /adhoc-workload-b3 as a candidate and builds DeleteContainerRequest(path), but has not posted it yet. 3) The client deletes the container itself, then creates a PERSISTENT node at the same path with data, and getData succeeds. 4) The ContainerManager's stale deleteContainer request now reaches PrepRequestProcessor. Its validation only checks childCount==0 and that the node is not a session ephemeral (EphemeralType != NORMAL). The new persistent node passes both checks (ephemeralOwner 0 -> VOID), so a DeleteTxn is generated and applied: the client's persistent node is removed. 5) The client calls exists('/') to wait for the deletion to be applied, then calls getData on the persistent node it created and never deleted. In FinalRequestProcessor.handleGetDataRequest, zks.getZKDatabase().getNode(path) returns null, and NoNodeException is thrown at FinalRequestProcessor.java:674. The server swallows the exception and only returns the NONODE code to the client. The test therefore records the server-side throw through a JFR jdk.JavaExceptionThrow stream, which only observes, and prints its stack trace as the cause of the assertion failure.

**Stack frame (agent):** at org.apache.zookeeper.server.FinalRequestProcessor.handleGetDataRequest(FinalRequestProcessor.java:674)

## Reproduction

- Test: `org.apache.zookeeper.server.TestAdhocWorkloadB3Repro#run`
- Command: `mvn -B -o test -pl zookeeper-server -Dtest='org.apache.zookeeper.server.TestAdhocWorkloadB3Repro#run' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-server/src/test/java/org/apache/zookeeper/server/TestAdhocWorkloadB3Repro.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.zookeeper.KeeperException$NoNodeException: KeeperErrorCode = NoNode`, frame `at org.apache.zookeeper.server.FinalRequestProcessor.handleGetDataRequest(FinalRequestProcessor.java:674)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h03m | 1 | 363,782 | 22 | 15,333 | 36,525 | 311,902 | $0.66 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
