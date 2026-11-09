# zk-adhoc-b4: ZooKeeperRetry.create re-sends a sequential create after a lost reply because exists() on the un-suffixed path is always null, creating duplicate znodes that use up hard count quota and make legitimate creates fail.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java:2201`, `ZooKeeperServer.checkQuota(String, long, long, String)`, throws `org.apache.zookeeper.KeeperException.QuotaExceededException` when `checkCountQuota && newCount > countLimit && isCountHardLimit   (newCount = currentStats.getCount() + countDiff)`
- Starting test: `org.apache.zookeeper.retry.TestAdhocWorkloadB4#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Through a TCP proxy, the server's reply to a committed PERSISTENT_SEQUENTIAL create from a ZooKeeperRetry (ZooInspector) client is lost and the connection drops; the client reconnects within the same session. A count hard quota is sized for the application's two creates.

**Why (root cause in the source):** ZooKeeperRetry.create (ZooKeeperRetry.java:76-93) handles ConnectionLoss by calling exists(path) on the requested path. For sequential modes that is never the real node name, so it always returns null, and the create is sent again, leaving a duplicate committed sequential node. The duplicate uses up the quota, so the application's next legitimate create is rejected at ZooKeeperServer.java:2201. The server check is correct; the client retry protocol produced the extra node. The orphan stays, so later creates keep failing until someone cleans it up, and sequential-node semantics (queues, locks) break.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The application asked for exactly two sequential children, and the quota was sized for exactly that. Losing one reply should not change the result. The quota is exceeded only because ZooKeeperRetry's retry protocol does not detect that the earlier create was already applied: it checks the requested path, which for sequential modes is never the real node name, and then sends the create again. The server's quota check thus rejects a legitimate request because a client-side retry left the server in a bad state. In a real deployment, any connection loss after a create has committed (network blip, server or proxy connection reset, GC pause past the socket timeout) makes ZooInspector leave orphan duplicate sequential znodes. These use up the count quota, so later legitimate creates fail with QuotaExceededException under a hard limit. The duplicates also break the semantics of sequential nodes, such as queues and lock or election recipes built on them.

**Execution (agent):** 1) One standalone server (setup as in TestAdhocWorkloadB4, quota enforcement on). An admin client creates /adhoc-workload-b4 and sets a count hard limit of 3 (the node itself plus 2 children). 2) A ZooInspector ZooKeeperRetry client connects through a TCP proxy (a stand-in for a lossy network link). 3) The client calls create('/adhoc-workload-b4/n-', PERSISTENT_SEQUENTIAL). The proxy passes the request on, and the server commits it as n-0000000000 (count 2). The proxy then drops the server's reply and closes the client's connection, which looks like a network glitch or a reset connection. 4) The client gets ConnectionLossException. ZooKeeperRetry.create checks exists('/adhoc-workload-b4/n-'), the path without the suffix. That node never exists for a sequential create, so the check returns null after the client reconnects within the same session. ZooKeeperRetry then sends the create again, and the server creates a duplicate n-0000000001 (count 3, limit reached). 5) The application makes its second create. The server computes newCount = 3 + 1 = 4 > countHardLimit 3 and throws QuotaExceededException at ZooKeeperServer.checkQuota:2201 (PrepRequestProcessor.pRequest2TxnCreate). The client receives it from ZooKeeperRetry.create. The test's ZooKeeperServer subclass only records the server-side exception and rethrows it unchanged, so the server stack trace appears as the cause of the test failure.

**Stack frame (agent):** at org.apache.zookeeper.server.ZooKeeperServer.checkQuota(ZooKeeperServer.java:2201)

## Reproduction

- Test: `org.apache.zookeeper.retry.TestAdhocWorkloadB4LostCreateReply#run`
- Command: `mvn -B -o test -Pfull-build -pl zookeeper-contrib/zookeeper-contrib-zooinspector -Dtest='org.apache.zookeeper.retry.TestAdhocWorkloadB4LostCreateReply#run' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-contrib/zookeeper-contrib-zooinspector/src/test/java/org/apache/zookeeper/retry/TestAdhocWorkloadB4LostCreateReply.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.zookeeper.KeeperException$QuotaExceededException: KeeperErrorCode = Quota has exceeded for /adhoc-workload-b4`, frame `at org.apache.zookeeper.server.ZooKeeperServer.checkQuota(ZooKeeperServer.java:2201)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h02m | 1 | 270,411 | 18 | 11,354 | 31,412 | 227,627 | $0.52 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
