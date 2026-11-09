# MC-2 investigation (Phase 1: evidence only)

Finding: stale REVALIDATE from an abandoned follower handshake overwrites the
session owner set for the client's live connection; TargetSafe
(SessionTrackerImpl.checkSession:246 throws SessionMovedException).
Source: MC (counterexample spec/output/MC_hunt_s2_bfs.out, config
MC_hunt_s2_stale_open.cfg). Not read in this phase beyond the finding JSON
(per "Do NOT" list).

Tree: base_commit 31794056e6 (worktree HEAD `3179405 base`). The worktree and
the case source tree carry Specula trace instrumentation (uncommitted, adds
`synchronized (SpeculaTrace.LOCK)` around owner writes). Reproduction uses a
pristine copy (`git archive HEAD` -> `confirmation/MC-2/clean`).

## Step 1: code audit

Owner writers / readers (pinned tree):
- `SessionTrackerImpl.java:238-248` checkSession: `session.owner == null` ->
  adopt; `session.owner != owner` -> `throw new SessionMovedException()` (L246).
- `SessionTrackerImpl.java:250-256` setOwner: unconditional `session.owner = owner`.
- `NIOServerCnxn.java:664-665`: requests from a client connected directly to
  the leader carry owner `ServerCnxn.me`.
- `LearnerHandler.java:433-435`: requests forwarded by a follower carry owner =
  that follower's LearnerHandler.
- `LeaderZooKeeperServer.java:165-171` revalidateSession (client reopens at the
  leader): `super.revalidateSession` (touch + `cnxn.finishSessionInit`) then
  `setOwner(sessionId, ServerCnxn.me)`.
- `Learner.java:93-110` validateSession (client reopens at follower, via
  `LearnerZooKeeperServer.java:79-81`): `pendingRevalidations.put`, then
  `writePacket(REVALIDATE)` (`Learner.java:120-128`, synchronized on `leaderOs`).
- `LearnerHandler.java:395-421` REVALIDATE at leader: `valid = touch(id,to)`;
  if valid, `leader.zk.setOwner(id, this)` (L409) unconditionally; reply queued.
  No check that the handshake is still current (no connection id / epoch).
- `PrepRequestProcessor.java:212,274,308,330,396`: every write and read op
  calls `checkSession(request.sessionId, request.getOwner())`.

Client side: `ClientCnxn.java:389` `connectTimeout = sessionTimeout / #hosts`;
`ClientCnxn.java:1043-1051` when not CONNECTED and `connectTimeout - idleRecv
<= 0` throws SessionTimeoutException -> cleanup -> `startConnect` next host
(random sleep < 1 s, `ClientCnxn.java:972-990`). So a slow revalidation at a
follower makes the client abandon that handshake and reopen at the next host
while the REVALIDATE is still in flight.

Call chain (reachable in normal usage): `new ZooKeeper(hosts, to, w, sid, pw)`
-> ClientCnxn.SendThread.primeConnection -> NIOServerCnxn.readConnectRequest ->
ZooKeeperServer.reopenSession (L529-536) -> LearnerZooKeeperServer.revalidateSession
-> Learner.validateSession -> [network] -> LearnerHandler.run REVALIDATE ->
setOwner(id, LearnerHandler). Then client op on leader -> NIOServerCnxn
(owner `me`) -> PrepRequestProcessor -> checkSession -> L246.

Trigger scenario: (1) session S exists, client disconnected; (2) client
reopens S with server list {F, L}, lands on F; F sends REVALIDATE; (3) the
F->L link delays it > connectTimeout (and < syncLimit*tickTime so F stays a
follower); (4) client abandons F, reopens at L; L sets owner `me`, client
CONNECTED; (5) delayed REVALIDATE arrives: touch true (session alive),
owner := F's LearnerHandler; (6) every op from the client on L fails
checkSession -> SessionMovedException.

Safeguards noted (to be tested in Phase 2): F's reply to the stale REVALIDATE
goes to a cnxn the client already closed (does not restore owner); nothing
else resets owner except a later reopen/createSession (PrepRequestProcessor
L360). Client does not reconnect on SESSIONMOVED (error code returned to the
caller), so the condition persists on the live connection.

## Step 2: developer knowledge

- Comment `LeaderZooKeeperServer.java:169-170`: "setowner as the leader
  itself, unless updated via the follower handlers" — owner is designed as
  "last revalidation wins"; no comment about stale/late revalidations.
- Comment `LearnerHandler.java:406-408`: "set the session owner as the
  follower that owns the session".
- Existing tests: `SessionTest.java` (session moved tests are about two
  handles; not this scenario). The workload TestAdhocWorkloadK1 moves the
  session across servers one handle at a time, and asserts success.
- Git history/tracker search: deferred until after the reproduction verdict
  (adhoc Shared Rule 2); queries recorded below.

## Step 3: known-status

Source = MC with a counterexample -> proceeds to Phase 2 regardless.
Novelty search recorded below (after the verdict).

## Phase 2 result (recorded before the novelty search)

Level 1 (timing only, pristine tree): REPRODUCED. 1 Ant run + 3/3 direct runs.
JDI frame: SessionTrackerImpl.checkSession(SessionTrackerImpl.java:246) <-
PrepRequestProcessor.pRequest(:308/:212/:396) <- PrepRequestProcessor.run(:114).
Logs: repro/MC-2.log, repro/MC-2.jdi.log, repro/MC-2.ant-report.txt.

## Novelty search (run after the verdict; sets Novelty only)

Queries:
1. WebSearch "ZooKeeper JIRA permanent ZSESSIONMOVED after client reconnects follower revalidate"
   -> ZOOKEEPER-2219 (open, different: in-flight request), ZOOKEEPER-2886 (follow-up, multi-op), ZOOKEEPER-484 (fixed, owner on follower->leader move; already in CHANGES.txt L56 of pinned tree).
2. WebSearch "ZOOKEEPER-710 session moved revalidate LearnerHandler setOwner"
   -> ZOOKEEPER-710 fix commit d052fc781e22baa5c0ac3f7a34ba2fd6de9ca5a7.
3. Fetched https://issues.apache.org/jira/browse/ZOOKEEPER-710 and the commit. The fix comment
   in FinalRequestProcessor: "client on slow follower starts to renew session, fails before this
   completes / then tries the fast follower (leader) and is successful / the initial renew is then
   successfully fwd/processed by the leader / the client and leader disagree on where the client is
   most recently attached (and therefore invalid SESSION MOVED generated)". Same mechanism.
   Fix: FinalRequestProcessor closes the connection on SessionMovedException (mitigation; the
   unfenced setOwner in LearnerHandler stays). Fix version 3.2.3/3.3.0. Pinned tree (version 3.3.0
   trunk, base 31794056e6) does NOT contain it: `grep SessionMoved` in
   server/FinalRequestProcessor.java is empty, and CHANGES.txt has no ZOOKEEPER-710 entry.
4. Local: grep CHANGES.txt for ZOOKEEPER-710/484/2219/2886 -> only ZOOKEEPER-484.

Novelty: KNOWN (ZOOKEEPER-710; fixed upstream, unfixed in pinned tree).
