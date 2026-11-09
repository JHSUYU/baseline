# MC-1 investigation (evidence only; verdict is decided after Phase 2)

Pinned tree: 1312ae0187 (worktree `confirmation/MC-1/worktree`, clean).
LES = zookeeper-recipes/zookeeper-recipes-election/.../recipes/leader/LeaderElectionSupport.java
FRP = zookeeper-server/.../server/FinalRequestProcessor.java

## Step 1: code audit
Target: FRP:672-674 `n = getNode(path); if (n == null) throw new NoNodeException()` in handleGetDataRequest.
The KeeperException is swallowed into `err` at FRP:604-605 and sent to the client as NONODE.

Client side call chains that reach FRP:674 through LES:310 (`toLeaderOffers` getData, no NoNode tolerance):
- start() LES:119 -> determineElectionStatus LES:137 -> LES:199 getChildren -> LES:310 getData; KeeperException caught at LES:138 -> becomeFailed LES:139
- process() watch callback LES:327 -> determineElectionStatus LES:335; caught at LES:336 -> becomeFailed LES:337 (S1-ii, EventThread)
- becomeReady LES:256 -> determineElectionStatus (retry path, same site)
- public getLeaderHostName LES:289 -> LES:291 -> LES:310; exception propagates to the caller

Peer action that removes the listed child: public stop() LES:147 -> delete LES:155. Documented as always permitted:
class Javadoc "A process may revoke its offer to be the leader at any time by calling stop()".

Counterexample `spec/output/MC_hunt_s1_bfs.out` (28 states, firedBy="peerStop", no fault, expiries=0):
- s13 offers={0,1,2}; s16 p1 ELECTED; s23 p2 READY (exists watch on 0)
- s19 p3 getChildren -> {0,1,2}
- s24-25 p1 stop, delete(0) queued; s26 p3 getData(0) queued behind it
- s27 delete served, offers={1,2}; s28 getData(0) -> NONODE, targetFired=TRUE

Reachability: all steps are public-API calls from ordinary threads. Trigger needs only a start() overlapping a peer's stop().

Safeguards recorded (Phase 2 must prove whether they fire):
- becomeReady LES:248-256 retries when `exists` finds the neighbor gone. It is reached only AFTER toLeaderOffers succeeds, so it does not cover LES:310.
- becomeFailed LES:270-275 only sets state=FAILED and dispatches FAILED. No retry, offer not deleted, no watch registered (the only watch registration is LES:239).
- process() LES:327 would re-determine, but only if a watch fires, and a participant failing in its first determination has none.
- Application-level: class Javadoc says it is up to the user to ensure any failure to become leader results in stop(). A listener may react to FAILED; the workload's does not. That revokes the offer but does not rejoin.
- Workload blindness: runElectionSupportThread's failureCounter (test:258-260) only counts exceptions thrown by start()/stop(); becomeFailed swallows them, so testNodes3's assertEquals(0, failureCounter) cannot see FAILED.

## Step 2: developer evidence (in-tree only; tracker/history search deferred until the verdict is settled, per adhoc Shared Rule 2)
- LES:249-252 comment: "If the stat fails, the node has gone missing between the call to getChildren() and exists(). We need to try and become the leader." The same race is explicitly handled one call later.
- LES:115-116 Javadoc: "Any (anticipated) failures result in a failed event being sent to all listeners."
- Class Javadoc caveat, LES:81-86: "best effort to detect catastrophic failures".
- LES:278-283 getLeaderHostName Javadoc: "by the time this method returns, state could have changed ... If there are no leader offers this method returns null." NoNode from a racing stop is not mentioned.
- Tests: no existing test asserts FAILED on overlap. testReadyOffer stops the leader from a DETERMINE_COMPLETE listener, i.e. after toLeaderOffers, and asserts re-election.

## Step 3: known-status
Source is MC with an actual counterexample, so no pre-filter applies; proceed to Phase 2. Novelty search runs after the verdict (see below).

## Build / artifact provenance
- `mvn -B -o test -pl zookeeper-recipes/zookeeper-recipes-election -Dtest=LeaderElectionSupportTest#testNodes3`: BUILD SUCCESS.
- deps zookeeper-3.10.0-SNAPSHOT.jar FRP class is byte-identical to the case tree's target jar (HEAD 1312ae01, status clean); 0 "specula" references in FRP, ZooKeeperServer or LES bytecode. handleGetDataRequest LineNumberTable has line 674 at bci 32. Uninstrumented.
- No SLF4J binding on this module's test classpath, so becomeFailed's LOG.error is discarded. Throw-site frames are captured by an external read-only JDI watcher.

## Novelty search (run only after the reproduction verdict was settled; sets the Novelty field only)
Date 2026-11-04. Read-only queries:
- git (pinned tree): `git log -- LeaderElectionSupport.java`; `git log --all -i --grep=LeaderElectionSupport`; `--grep='leader election recipe\|election recipe\|recipes.*election'`
- JIRA JQL: `project=ZOOKEEPER AND text ~ "LeaderElectionSupport"` (11); `text ~ "toLeaderOffers"` (0); `summary ~ "leader election recipe"` (5); `component = recipes AND text ~ "NoNode"` (0)
- GitHub search/issues API (`gh` not installed), open and closed, sorted by update: `LeaderElectionSupport repo:apache/zookeeper` (2: #1128 open "Various code clean-ups", #764 closed 2019 Spotbugs); `toLeaderOffers` (0); `election recipe NoNode` (0); `recipes election getData is:pr` (0)
- GitHub commits API for LES on upstream default branch: newest 837f86cc 2024-10-18 ZOOKEEPER-4877 "Fix typos in comments", already in the pinned tree. No later change, so no fix landed.
- Web: "ZooKeeper LeaderElectionSupport toLeaderOffers getData NoNodeException leader offer deleted between getChildren and getData FAILED": no report of this failure.
Nearest reports, read in full, NOT the same mechanism:
- ZOOKEEPER-1219 (Fixed): READY_START dispatched before the exists() check. Order of events at LES:239-247, not getData at LES:310.
- ZOOKEEPER-1225 (Patch Available): repeated start() by one caller yields no ELECTED node. Same symptom class, different trigger.
- ZOOKEEPER-1405 (Open): dispatchEvent ordering, process() vs start().
- ZOOKEEPER-1209 (Patch Available): network partition, two ELECTED.
Result: Novelty NEW. The search did not change the reproduction or verdict.
Persistent registry: persistent-findings-context.json has previous=null and inherited_records={}, so no history is available; `lookup` not run, also honoring the task's rule against reading other findings.
