# zk-adhoc-b2: The LeaderElectionSupport recipe fails permanently (FAILED, no leader elected) when a competing candidate's ephemeral offer disappears between getChildren and getData, which happens exactly when a leader crashes.

Severity (reviewer): **outage**

## The ad hoc check (the prompt's only target)

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/FinalRequestProcessor.java:674`, `FinalRequestProcessor.handleGetDataRequest(Record, ServerCnxn, List<Id>)`, throws `org.apache.zookeeper.KeeperException.NoNodeException` when `n == null   (n = zks.getZKDatabase().getNode(path))`
- Starting test: `org.apache.zookeeper.recipes.leader.LeaderElectionSupportTest#testNodes3`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Two LeaderElectionSupport candidates, each with its own session. Leader A's session closes (process crash) just after candidate B's getChildren on the election root and before B's per-child getData calls.

**Why (root cause in the source):** LeaderElectionSupport.toLeaderOffers calls getData for every child returned by getChildren (LeaderElectionSupport.java:199, 309-310) and does not handle offers that disappear in between. The server correctly returns NoNode (FinalRequestProcessor.java:673-674), but start() catches the exception and calls becomeFailed (LeaderElectionSupport.java:135-140, 270-275). B ends in the terminal FAILED state with its offer still registered. Candidate failure is exactly what the recipe's documented algorithm promises to handle (class javadoc), and becomeReady already tolerates the same race for exists(). Here no leader is elected, and later candidates, which watch only their predecessor, never take over.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The election recipe's own coordination is wrong. It reads the offer set non-atomically: getChildren, then one getData per child. It assumes every listed offer still exists, but offers are ephemeral and are deleted whenever a candidate crashes, loses its session or calls stop(). That is exactly the event the recipe exists to handle, and becomeReady() already tolerates the same race for exists(). The server's check is correct (the znode really is gone); what goes wrong is the client-side coordination, which turns the crash of the current leader into a fatal NoNodeException for the follower that should succeed it. In a real deployment, a leader crash (or a concurrent stop()/restart of any other candidate) that lands between a contender's getChildren and getData puts that contender in the terminal FAILED state. Its offer stays registered but it never watches a predecessor or re-runs the election. If it was the next in line, the service is left with no elected leader, and the other contenders, who watch only their own predecessors, will never notice. The same race makes getLeaderHostName() throw spuriously. Correct behavior would be to skip offers that vanished (catch NoNodeException per child) and continue the determination.

**Execution (agent):** Standalone ZooKeeper server (ClientBase) with the election root znode. (1) Candidate A, a LeaderElectionSupport with its own client session, calls start(): it creates the EPHEMERAL_SEQUENTIAL offer root/n_0000000000 and is ELECTED. (2) Candidate B, with its own session, calls start(): makeOffer() creates root/n_0000000001, then determineElectionStatus() -> toLeaderOffers(zk.getChildren(root)) returns [n_..0, n_..1]. (3) Right after that getChildren reply and before B's per-child getData calls, A's process crashes. The test closes A's session from another thread; the effect is the same as a session expiring after a crash, and the server deletes A's ephemeral offer n_..0. The window is opened deterministically by a test-only ZooKeeper subclass that runs a hook after getChildren() returns. (4) B calls getData(root/n_..0). The server's FinalRequestProcessor.handleGetDataRequest finds getNode(path)==null and throws KeeperException.NoNodeException at line 674. The client gets NONODE, toLeaderOffers propagates it, and determineElectionStatus/start() catch it and call becomeFailed(): B's events are START, OFFER_START, OFFER_COMPLETE, DETERMINE_START, FAILED. B never becomes leader, and no other candidate is left. The server-side stack is recorded with JFR (jdk.JavaExceptionThrow, started through the standard DiagnosticCommand MBean and decoded with $JAVA_HOME/bin/jfr) and attached as the cause of the test's AssertionFailedError. Note on the command: the module's test classpath lacks hamcrest, which the zookeeper test-jar's ClientBase needs. Surefire's JUnit launcher 1.3.1 silently discovers 0 tests in that case, so the given starting command runs nothing (it also reports 0 tests for LeaderElectionSupportTest#testNodes3). Adding the cached hamcrest-2.2.jar via -Dmaven.test.additionalClasspath fixes discovery without changing any build file. With it, testNodes3 runs and passes, and the new test fails reproducibly (3/3 runs).

**Stack frame (agent):** at org.apache.zookeeper.server.FinalRequestProcessor.handleGetDataRequest(FinalRequestProcessor.java:674)

## Reproduction

- Test: `org.apache.zookeeper.recipes.leader.LeaderElectionSupportCrashRaceTest#testLeaderCrashBetweenGetChildrenAndGetData`
- Command: `source /bulk/codingagent/cases/zk-adhoc-b2/agent/env.sh && mvn -B -o test -pl zookeeper-recipes/zookeeper-recipes-election -Dtest='org.apache.zookeeper.recipes.leader.LeaderElectionSupportCrashRaceTest#testLeaderCrashBetweenGetChildrenAndGetData' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false -Dmaven.test.additionalClasspath=/bulk/codingagent/cases/zk-adhoc-b2/agent/deps/org/hamcrest/hamcrest/2.2/hamcrest-2.2.jar`
- Test files (in `repro/`, paths relative to the system's tree): `zookeeper-recipes/zookeeper-recipes-election/src/test/java/org/apache/zookeeper/recipes/leader/LeaderElectionSupportCrashRaceTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.zookeeper.KeeperException$NoNodeException: KeeperErrorCode = NoNode`, frame `at org.apache.zookeeper.server.FinalRequestProcessor.handleGetDataRequest(FinalRequestProcessor.java:674)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h08m | 1 | 2,178,168 | 74 | 30,667 | 75,434 | 2,071,993 | $1.63 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
