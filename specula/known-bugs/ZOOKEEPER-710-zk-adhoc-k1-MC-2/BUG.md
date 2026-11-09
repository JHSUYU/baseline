# ZOOKEEPER-710: detected by Specula (yes), finding MC-2

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `zk-adhoc-k1`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

A client attached to a slow follower F1 loses its connection (packet loss) and reconnects. F1 forwards a session revalidation to the leader; before it completes the client times out and reconnects to another, fast server S2 (the leader or another follower), whose revalidation completes first and makes S2 the session owner at the leader. Then F1's late revalidation is processed by the leader (`LearnerHandler` REVALIDATE -> `leader.zk.setOwner(id, this)`), so the leader now records F1 as the owner while the client is attached to S2. Every write the client sends through S2 hits `SessionTrackerImpl.checkSession` on the leader, where `session.owner != owner` throws `SessionMovedException`. The buggy `FinalRequestProcessor` just returns the error code (ZSESSIONMOVED) on the same live connection, so the client never reconnects and ownership is never re-established: all later requests fail permanently until the application makes a new session. Fix: `FinalRequestProcessor` catches `SessionMovedException` and calls `cnxn.sendCloseSession()`, tearing down the connection, so the client reconnects and revalidates.

## What counted as detecting it (written before the run)

A Specula finding must show: a live session whose owner recorded at the leader is a server the client has already left, because a stale/late revalidation (or other owner update) from the old server is applied after the client re-attached elsewhere; the client's requests on its *current* connection then make `checkSession` throw `SessionMovedException` at line 246, and the condition persists (the connection is not closed / the client is not forced to reconnect, so every later request fails the same way). A SessionMoved caused only by deliberately using two handles on one session (designed behaviour, as in `QuorumTest#testSessionMoved`) does not count.

## What Specula found

**Specula's finding MC-2:** Stale REVALIDATE from an abandoned follower handshake overwrites session owner; live leader connection gets SessionMovedException

- **Cause:** LearnerHandler REVALIDATE handling runs leader.zk.setOwner(id, this) whenever touch succeeds, with no check that the follower handshake is still the client's current connection; it overwrites the owner ServerCnxn.me set by LeaderZooKeeperServer.revalidateSession.
- **Trigger:** Client reopens its session at follower F (server list {F, L}); F's REVALIDATE is delayed on the F->L link beyond connectTimeout (sessionTimeout/#hosts); client abandons F and reopens at leader L; the delayed REVALIDATE then reaches L.
- **Consequence:** Every request from the client on its only live connection (to L) fails checkSession with SessionMovedException at SessionTrackerImpl.java:246 (setData/exists/create/getChildren and pings), persistently while connected.
- **Premises:** Pinned tree 31794056e6 (3.3.0 trunk) lacks the ZOOKEEPER-710 mitigation (FinalRequestProcessor closing the connection on SessionMovedException). A follower->leader delay shorter than syncLimit*tickTime but longer than the client connectTimeout; no peer fails. Client server list contains the follower and the leader.

**Operator's judgement:** yes. stale REVALIDATE overwrites session owner; permanent SessionMoved on the live connection (JIRA found only after reproduction)

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_s2_stale_open.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-08: Invariant TargetSafe is violated.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 1h13m | 28.6M | $22.01 |

Time is active time; quota sleeps are excluded.
