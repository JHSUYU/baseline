# ZOOKEEPER-710 (Permanent session-moved errors): detected

Case `zk-adhoc-k1`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `src/java/main/org/apache/zookeeper/server/SessionTrackerImpl.java:246`, `SessionTrackerImpl.checkSession(long, Object)`, throws `org.apache.zookeeper.KeeperException.SessionMovedException` when `session.owner != owner   (session = sessionsById.get(sessionId); taken when session.owner is already set)`
- Starting test: `org.apache.zookeeper.test.TestAdhocWorkloadK1#run`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** yes

**What the agent found:** A client's reconnect (session renew) to slow follower F1 is delayed on the network; the client times out, re-establishes the session on F2, and works there. The late ConnectRequest then reaches F1, F1 sends REVALIDATE to the leader, and the leader sets the session owner to F1's LearnerHandler. Every later request from the client over its only live connection (F2) is then rejected with SessionMovedException at SessionTrackerImpl.java:246, and the connection stays open (3/3 setData failures).

**Same root cause as ZOOKEEPER-710?** Yes, same defect. The stale revalidation path is LearnerHandler.java:403-409 (touch, then an unconditional leader.zk.setOwner(id, this)), which makes the owner diverge from the client's real server. PrepRequestProcessor.pRequest:308 -> SessionTrackerImpl.checkSession:244-246 then throws SessionMovedException, and the buggy FinalRequestProcessor (catch KeeperException at :330) returns it to the client as an ordinary error code without closing the connection, so the error is permanent. The fix's FinalRequestProcessor hunk (catch SessionMovedException -> cnxn.sendCloseSession()) targets exactly this sequence; its own comment describes it ('client on slow follower starts to renew session, fails before this completes, then tries the fast follower ... the initial renew is then successfully fwd/processed by the leader ... client and leader disagree').

**Realistic?** Yes. It uses a real 3-server QuorumPeer ensemble and the real client. The only intervention is a TCP proxy in front of F1 that holds the client's bytes until the client has timed out and moved to F2, then delivers them: a network delay. The leader's SessionTrackerImpl subclass calls super and only records the exception. Shuffling the server list until F1 is tried first is ordinary client behaviour. No reflection, no fabricated arguments, no protocol shortcut.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **REPRODUCED**. This is a handle-not-prevent fix, so the check still fires once at SessionTrackerImpl.java:246 on the fixed tree. But the server now closes the client's F2 connection (log: 'Closed socket connection ... 11224', client 'attempting reconnect'), and the first setData gets ConnectionLossException instead of SessionMovedException. Only one server-side rejection is logged, against 3 on the buggy tree. So the permanent SESSIONMOVED consequence is gone, as the fix intends.

**Reason:** The agent reproduced the exact interleaving in the ZOOKEEPER-710 fix comment: a stale renew from a slow follower is processed by the leader after the client has moved, and the session owner diverges. On the buggy code the client's live connection gets SessionMovedException on every request without being torn down, which is the JIRA's consequence. The trigger is a realistic network delay, and the fixed version turns the permanent error into a connection loss the client recovers from.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The owner check is meant to reject requests a client sent through the server it has left (ZOOKEEPER-417). Here the client never moved away from F2. Its only live connection is F2, and it ordered its own actions correctly: it gave up on F1 and then connected to F2. The coordination is still wrong because the leader applies REVALIDATEs in arrival order, and the last-arriving REVALIDATE takes ownership even when it comes from a stale, abandoned connect attempt. Nothing (no connection epoch, no check that the newer revalidation wins, no rejection of revalidations for a session that already has a live owner) stops a late connect request from stealing the session. A connect attempt that times out and is then delivered late is ordinary in production: network delay or retransmission, a GC pause or overloaded NIO thread on F1, or a slow F1-to-leader link, combined with the client's short connectTimeout = sessionTimeout/#servers. Consequence: a healthy client connected to a healthy server has every write and sync-path request (create, delete, setData, setACL, setWatches) rejected with SESSIONMOVED. The client library does not reconnect on SESSIONMOVED, so the error persists until the connection happens to drop. Applications see failures that look as if they used the session from two places, while the session, its ephemeral nodes and heartbeats stay alive, so locks and leader znodes held by that session can no longer be updated or released.

**Execution (agent):** 3-server ensemble (leader L, followers F1, F2), using the real QuorumPeer/Leader/LeaderZooKeeperServer. The only test change is that the leader's SessionTrackerImpl is an anonymous subclass whose checkSession calls super and records the SessionMovedException it throws, so the server-side stack can be printed. 1) A client creates session S on F2 and creates /w (the leader sets S.owner = LearnerHandler(F2)). 2) The client's TCP connection drops (DisconnectableZooKeeper.disconnect, no closeSession). The client reconnects with server list {F1, F2}. The path to F1 goes through a test TCP proxy that holds the client's bytes, standing in for a slow or lossy network. The client opens TCP to F1 and sends ConnectRequest(S, passwd). It gets no answer within connectTimeout, so it closes that socket and moves on to F2. F2 sends REVALIDATE(S) and the leader sets S.owner = LearnerHandler(F2). The client is now connected to F2 only, and setData and create succeed. 3) The client's delayed ConnectRequest then reaches F1 (data the client sent before its close() is still delivered). F1 runs reopenSession -> Learner.validateSession, which sends REVALIDATE(S) to the leader. LearnerHandler(F1) calls touch() and then unconditionally leader.zk.setOwner(S, LearnerHandler(F1)). F1 answers on a connection the client has already given up on, then that connection closes. 4) The client, still connected only to F2, calls setData(/w). F2 forwards it, PrepRequestProcessor calls checkSession(S, LearnerHandler(F2)), and since session.owner (F1's handler) != owner it throws SessionMovedException at SessionTrackerImpl.java:246. Every later request from the client fails the same way (3/3 in the test). Because the client library shuffles the server list, the test repeats the disconnect/reconnect until the client tries F1 first. The test then fails with an AssertionError whose cause is the server-side SessionMovedException. Passed reliably in 3/3 runs.

**Stack frame (agent):** at org.apache.zookeeper.server.SessionTrackerImpl.checkSession(SessionTrackerImpl.java:246)

## Reproduction

- Test: `org.apache.zookeeper.server.quorum.StaleRevalidateSessionMovedTest#testStaleReconnectStealsSession`
- Command: `source ../env.sh && ant -Dtestcase=StaleRevalidateSessionMovedTest test-core-java   (output: build/test/logs/TEST-org.apache.zookeeper.server.quorum.StaleRevalidateSessionMovedTest.txt)`
- Test files (in `repro/`, paths relative to the system's tree): `src/java/test/org/apache/zookeeper/server/quorum/StaleRevalidateSessionMovedTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/4 tries hit the check); exception `org.apache.zookeeper.KeeperException$SessionMovedException: KeeperErrorCode = Session moved`, frame `at org.apache.zookeeper.server.SessionTrackerImpl.checkSession(SessionTrackerImpl.java:246)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h06m | 1 | 1,110,379 | 46 | 28,945 | 67,000 | 1,014,388 | $1.32 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
