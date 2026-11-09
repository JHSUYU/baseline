# zk-adhoc-b1: A crash or connection loss between the two creates in SetQuotaCommand.createQuota leaves zookeeper_limits without zookeeper_stats: setquota then fails with NoNode for good, and the hard quota is silently not enforced.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/FinalRequestProcessor.java:674`, `FinalRequestProcessor.handleGetDataRequest(Record, ServerCnxn, List<Id>)`, throws `org.apache.zookeeper.KeeperException.NoNodeException` when `n == null   (n = zks.getZKDatabase().getNode(path))`
- Starting test: `org.apache.zookeeper.test.TestAdhocWorkloadB1#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Standalone server with quota enforcement. The server crashes right after committing the client's create of zookeeper_limits and before the create of zookeeper_stats. After the restart the client retries SetQuotaCommand.createQuota on ConnectionLoss.

**Why (root cause in the source):** SetQuotaCommand.createQuota creates the limit and stat nodes with two separate, non-atomic creates (SetQuotaCommand.java:235-244). On retry it treats an existing limit node as a complete quota and calls getData(statPath) (SetQuotaCommand.java:253-270), which fails at FinalRequestProcessor.java:673-674 because the stat node was never created. The server's check is correct; the client-side quota protocol produced a half-built quota. The damage lasts: every later setquota on the path fails with NoNode until an admin deletes the nodes by hand. ZooKeeperServer.checkQuota then finds no stat node, logs 'Missing node for stat' and returns (ZooKeeperServer.java:2181-2184), so the hard limit is silently not enforced (5 children created under a limit of 2).

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The quota is coordinated through two znodes (zookeeper_limits and zookeeper_stats). The client-side protocol in SetQuotaCommand.createQuota creates them with two separate, non-atomic create calls (it does not use multi), and on a retry it treats 'zookeeper_limits exists' as 'quota fully set up'. A server crash, a failover or a lost connection between the two creates is ordinary in a real deployment. It leaves zookeeper_limits without zookeeper_stats, a state a correct quota setup should never produce. The getData check then rejects it with NoNode even though the user's request is valid (the path exists, and the user is retrying a quota call exactly as ZooKeeper clients are expected to after ConnectionLoss). Consequences: (a) setquota on that path fails with NoNode from then on and cannot repair itself (an admin has to delete the quota nodes manually); (b) the server's quota enforcement (ZooKeeperServer.checkQuota) finds no stat node, only logs 'Missing node for stat' and returns, so the hard count limit is silently not enforced. The test creates 5 children under a hard limit of 2, which defeats a quota meant to protect the ensemble.

**Execution (agent):** Standalone ZooKeeper server (ClientBase, zookeeper.enforceQuota=true), one client session. 1) Client creates /adhoc-workload-b1 and calls SetQuotaCommand.createQuota(path, countHardLimit=2) (the same quota call as TestAdhocWorkloadB1, retried on ConnectionLossException). 2) createQuota creates /zookeeper, /zookeeper/quota/adhoc-workload-b1, then /zookeeper/quota/adhoc-workload-b1/zookeeper_limits; that create is committed and logged to the txn log. 3) The server crashes right after it commits that create, before the client sends its create of .../zookeeper_stats. In the test, a ZooKeeper subclass calls ClientBase.stopServer() right after create(zookeeper_limits) returns. 4) The client's create(zookeeper_stats) fails with ConnectionLossException, so the first quota attempt fails. 5) The server restarts on the same data dir (startServer), restores zookeeper_limits from its txn log, and the client reconnects with the same session. 6) The client retries createQuota. exists(zookeeper_limits) is now non-null, so it takes the 'update existing quota' branch and calls getData(.../zookeeper_stats). 7) On the server, FinalRequestProcessor.handleGetDataRequest finds getNode(statPath) == null and throws KeeperException.NoNodeException at line 674. The server sends only the error code back. The test records the real server-side exception with a pass-through JMockit observer on the NoNodeException constructor (the constructor runs unchanged; the observer only saves the instance) and attaches it to the test failure. 8) Afterwards every later setquota on the path (e.g. raising the limit to 3, as the workload does) also fails with NoNode. The server logs 'Missing node for stat' and skips quota checking: 5 children are created under a hard count limit of 2.

**Stack frame (agent):** at org.apache.zookeeper.server.FinalRequestProcessor.handleGetDataRequest(FinalRequestProcessor.java:674)

## Reproduction

- Test: `org.apache.zookeeper.test.TestAdhocWorkloadB1CrashTest#run`
- Command: `source ../env.sh && mvn -B -o test -pl zookeeper-server -Dtest='org.apache.zookeeper.test.TestAdhocWorkloadB1CrashTest#run' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-server/src/test/java/org/apache/zookeeper/test/TestAdhocWorkloadB1CrashTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Suppressed: org.apache.zookeeper.KeeperException$NoNodeException: KeeperErrorCode = NoNode`, frame `at org.apache.zookeeper.server.FinalRequestProcessor.handleGetDataRequest(FinalRequestProcessor.java:674)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h04m | 1 | 537,184 | 32 | 14,797 | 39,519 | 482,836 | $0.71 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
