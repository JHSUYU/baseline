# ZOOKEEPER-2886 (Multi-op session-moved errors): not detected

Case `zk-adhoc-k2`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `src/java/main/org/apache/zookeeper/server/SessionTrackerImpl.java:310`, `SessionTrackerImpl.checkSession(long, Object)`, throws `org.apache.zookeeper.KeeperException.SessionMovedException` when `session.owner != owner   (session = sessionsById.get(sessionId); taken when session.owner is already set)`
- Starting test: `org.apache.zookeeper.test.SessionUpgradeTest#testUpgradeWithEphemeralOnFollower`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** no

**What the agent found:** A delayed REVALIDATE from a slow follower A (for a reconnect the client already abandoned) reaches the leader after the client reconnected to the leader, sets the session owner back to LearnerHandler(A), and the client's next plain setData on its live leader connection fails SessionTrackerImpl.checkSession:310 with SessionMovedException; the leader then closes the connection and the client sees ConnectionLoss.

**Same root cause as ZOOKEEPER-2886?** The agent's failing execution is the ZOOKEEPER-710 owner divergence (unconditional owner reassignment on REVALIDATE in LearnerHandler/leader.zk.setOwner), exercised through a non-multi setData. The ZOOKEEPER-2886 defect is in FinalRequestProcessor.processRequest: at agent/zookeeper/src/java/main/org/apache/zookeeper/server/FinalRequestProcessor.java:173 (`if (ke != null && request.type != OpCode.multi) throw ke;`) a SessionMovedException on a multi is not rethrown, and in the multi OpCode.error branch a SESSIONMOVED sub-result is returned as an ErrorResult, so the catch at :423 (cnxn.sendCloseSession) is never reached. The fix hunks add `if (ke instanceof SessionMovedException) throw ke;` and throw SessionMovedException for a SESSIONMOVED sub-result. The agent's request is setData, which already takes the :173 throw path and the :423 teardown, so it never touches the code the fix changes. The owner divergence it produces is shared background with ZOOKEEPER-710, which CRITERIA.md lists as a separate case (zk-adhoc-k1).

**Realistic?** Mostly realistic: a 3-server ensemble, a follower crash (B shutdown), and a follower whose REVALIDATE to the leader is held behind a latch (a slow quorum link or a GC pause), with the client's 4s connect timeout causing it to give up on A and reconnect to the leader. The latch is in a Follower subclass at the validateSession send boundary, which counts as an allowed message delay. The leader-side processTxn override only records the exception. The trigger does not include multi operations, though, and multi is what this bug is about.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **REPRODUCED**. REPRODUCED on the fixed tree too (same exception at SessionTrackerImpl.java:310). That is expected: the fix only changes how FinalRequestProcessor handles SessionMoved for multi and does not stop the owner divergence or the check from firing. On both trees the consequence is the same (the connection is torn down and the client gets ConnectionLoss), so the fixed version tells nothing apart for this non-multi execution.

**Reason:** CRITERIA.md requires a connection that sends only multi operations, where SessionMoved comes back inside the multi result and the client keeps getting it forever, and it states that a finding whose connection is torn down and recovers is not this bug. The agent's test uses setData, whose SessionMovedException goes through FinalRequestProcessor's existing teardown path (the client sees ConnectionLoss in the log), so it never exercises the multi handling that the ZOOKEEPER-2886 fix changes. It reproduces the ZOOKEEPER-710 owner divergence, not ZOOKEEPER-2886.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The owner check is meant to reject stale requests that arrive through a server the client has already left (ZOOKEEPER-417/710). Here the coordination of the owner field itself goes wrong: ownership is assigned by whichever REVALIDATE (or leader-side revalidation) reaches the leader last, not by the connection the client actually completed. A revalidation for a connection attempt the client already abandoned, delayed only by a slow follower or quorum link (an ordinary event once a client's connect timeout, sessionTimeout/#servers, is shorter than the follower's revalidation round trip), overwrites the owner set for the client's live connection. The check then rejects a legitimate write from the client's current connection, which is exactly the 'invalid SESSION MOVED' the FinalRequestProcessor comment for ZOOKEEPER-710 describes, and which the code only mitigates by dropping the connection. Consequences in a deployment: the client's writes fail and its connection to a healthy server is torn down after a server crash or failover, it must reconnect again (possibly landing on the slow server), and applications see SessionMoved/ConnectionLoss errors and spurious disconnects. Where the error is not converted into a connection close (e.g. inside multi-op results, cf. ZOOKEEPER-2886), the client can keep getting SessionMoved on a perfectly valid connection.

**Execution (agent):** 3-server ensemble (leader L, followers A and B) configured like SessionUpgradeTest (localSessionsEnabled=true, localSessionsUpgradingEnabled=true), tickTime 4000. One ZooKeeper client (session timeout 12s, so a 4s connect timeout per server) tries servers in the order B, A, L. (1) The client connects to follower B and creates an EPHEMERAL znode. B upgrades the local session to a global one, and the leader's global SessionTrackerImpl sets session.owner = LearnerHandler(B). (2) Fault: follower A becomes slow at forwarding session revalidations, i.e. its REVALIDATE quorum packet to the leader is delayed (test-side Follower subclass holding the packet behind a latch, which models a slow quorum link or a GC-paused follower). (3) Crash: follower B is shut down. The client reconnects to A, and A sends (delayed) REVALIDATE for the session. (4) A does not answer within the 4s connect timeout. The client closes that socket and connects to the leader L. L's LeaderZooKeeperServer.revalidateSession touches the session and sets owner = ServerCnxn.me. The client is now legitimately attached to L (exists(/eph) succeeds). (5) A's delayed REVALIDATE for the abandoned attempt reaches the leader. LearnerHandler(A) handles REVALIDATE: checkIfValidGlobalSession is true, so it calls leader.zk.setOwner(id, LearnerHandler(A)) unconditionally and moves ownership back to A, although the client is no longer connected there. (6) The client sends setData(/eph) on its current, valid connection to L. PrepRequestProcessor -> LeaderSessionTracker.checkSession -> SessionTrackerImpl.checkSession finds session.owner (LearnerHandler A) != ServerCnxn.me and throws SessionMovedException at SessionTrackerImpl.java:310. The leader's FinalRequestProcessor then tears down the client's connection, so the client sees ConnectionLossException for the write. The test captures the exception attached to the leader's Request (observation-only override of processTxn) and prints its stack trace.

**Stack frame (agent):** at org.apache.zookeeper.server.SessionTrackerImpl.checkSession(SessionTrackerImpl.java:310)

## Reproduction

- Test: `org.apache.zookeeper.server.quorum.SessionMovedStaleRevalidateTest#testStaleRevalidateFromSlowFollowerFailsOwnerCheck`
- Command: `source /bulk/codingagent/cases/zk-adhoc-k2/agent/env.sh && ant -Dtestcase=SessionMovedStaleRevalidateTest test-core-java`
- Test files (in `repro/`, paths relative to the system's tree): `src/java/test/org/apache/zookeeper/server/quorum/SessionMovedStaleRevalidateTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.zookeeper.KeeperException$SessionMovedException: KeeperErrorCode = Session moved`, frame `at org.apache.zookeeper.server.SessionTrackerImpl.checkSession(SessionTrackerImpl.java:310)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h09m | 1 | 2,129,143 | 60 | 48,004 | 108,728 | 1,972,351 | $2.22 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
