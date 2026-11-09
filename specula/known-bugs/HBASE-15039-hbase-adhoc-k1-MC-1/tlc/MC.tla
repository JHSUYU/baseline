-------------------------------- MODULE MC --------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hbase-adhoc-k1).                   *)
(*                                                                         *)
(* - Fault-injection actions and the actions that introduce               *)
(*   nondeterminism from outside (new tokens, time) are counter-bounded.   *)
(* - Reactive actions (start-up steps, election, leader loop, rolls, ZK    *)
(*   event handling, validation) are not bounded.                          *)
(* - QuiescentTick (MC only) forbids a tick while a split window is open   *)
(*   (createPassword between :128 and :129, rollCurrentKey between :249    *)
(*   and its end) or while a ZK event is undelivered.  TRUE closes S1      *)
(*   and models "ZK delivery is faster than one tick"; FALSE opens them.   *)
(* - TargetFilter (MC only) restricts which failing TargetChecks count, so *)
(*   each hunt reports only its own Scenario's mechanism.  TargetCheck     *)
(*   changes nothing but targetFired, so the filter prunes no other        *)
(*   behavior.                                                             *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxTime,        \* bound on gtime
    MaxTokens,      \* bound on createPassword calls
    MaxCrash,       \* process crashes            (S4, S6 control)
    MaxExpire,      \* ZK session expiries of a running node (S4, S6 control)
    MaxZkFail,      \* ZK calls failing after retries (S4 publish, S5 start)
    MaxStop,        \* graceful LeaderElector/RpcServer stops (S4 interrupt, S6)
    MaxRestart,     \* restarts of a dead server  (S5 variant)
    QuiescentTick,  \* BOOLEAN, see above
    TargetFilter    \* "any" | "S1S2" | "S3" | "S4" | "S5" | "S6"

VARIABLE faults

mcVars == <<vars, faults>>

(***************************************************************************)
(* Scenario classification of a failing check at v for token t.            *)
(***************************************************************************)
\* v had the key at some point in this incarnation: it was removed (S1, S2).
Removed(v, t) == t.keyId \in everHeld[v]

\* The minting node is still about to run ATSM:256 for this key, and can
\* (an expired session cannot write: RollPublish needs session).
PublishPending(t) ==
    /\ t.sec \in Node
    /\ alive[t.sec] /\ session[t.sec] /\ lpc[t.sec] = "rollPublish"
    /\ currentKey[t.sec].id = t.keyId /\ currentKey[t.sec].sec = t.sec

\* The key was installed and signed with but never reached ZK, and never will.
Lost(t) == <<t.keyId, t.sec>> \notin published /\ ~PublishPending(t)

\* The token's key is in ZK now.
InZK(t) == t.keyId \in DOMAIN zkKeys /\ zkKeys[t.keyId].sec = t.sec

\* v has a key event queued that will (re)read the keys from ZK.
DeliveryQueued(v) == \E i \in DOMAIN evq[v] : evq[v][i].type \in {"Children", "Data"}

\* Each class names the mechanism that keeps the key from v.  A key that
\* is not yet in ZK but still will be, or one whose event is still queued
\* at a subscribed non-master, is propagation lag (S3) whatever else holds.
Class(v, t) ==
    IF Removed(v, t) THEN "S1S2"
    ELSE IF startFailed[v] /\ InZK(t) /\ ~DeliveryQueued(v) THEN "S5"  \* never subscribed
    ELSE IF Lost(t) THEN "S4"                                         \* never published
    ELSE IF isMaster[v] /\ InZK(t) THEN "S6"                           \* master ignores ZK
    ELSE "S3"

InFilter(v, t) == TargetFilter = "any" \/ Class(v, t) = TargetFilter

(***************************************************************************)
(* Bounded wrappers                                                        *)
(***************************************************************************)
Quiet ==
    \A n \in Node :
        /\ cpPC[n] = "idle"
        /\ lpc[n] \notin {"rollInstall", "rollPublish", "rollUpdatePrev"}
        /\ Live(n) => evq[n] = <<>>

MCTick ==
    /\ gtime < MaxTime
    /\ QuiescentTick => Quiet
    /\ Tick
    /\ UNCHANGED faults

MCIssueReadClock(n) ==
    /\ faults.tokens < MaxTokens
    /\ IssueReadClock(n)
    /\ faults' = [faults EXCEPT !.tokens = @ + 1]

MCCrash(n) ==
    /\ faults.crash < MaxCrash
    /\ Crash(n)
    /\ faults' = [faults EXCEPT !.crash = @ + 1]

MCSessionExpire(n) ==
    /\ faults.expire < MaxExpire
    /\ SessionExpire(n)
    /\ faults' = [faults EXCEPT !.expire = @ + 1]

MCStartZkFail(n) ==
    /\ faults.zkFail < MaxZkFail
    /\ StartZkFail(n)
    /\ faults' = [faults EXCEPT !.zkFail = @ + 1]

MCZkWriteFail(n) ==
    /\ faults.zkFail < MaxZkFail
    /\ ZkWriteFail(n)
    /\ faults' = [faults EXCEPT !.zkFail = @ + 1]

MCNodeStop(n) ==
    /\ faults.stop < MaxStop
    /\ NodeStop(n)
    /\ faults' = [faults EXCEPT !.stop = @ + 1]

MCRestart(n) ==
    /\ faults.restart < MaxRestart
    /\ Restart(n)
    /\ faults' = [faults EXCEPT !.restart = @ + 1]

MCTargetCheck(v, t) ==
    /\ TargetCheck(v, t)
    /\ targetFired' => InFilter(v, t)
    /\ UNCHANGED faults

\* Reactive actions: not bounded.
MCReactive(n) ==
    /\ \/ StartCreateParents(n) \/ StartWatchExists(n)
       \/ StartListChildren(n)  \/ StartReadChildren(n)
       \/ ElectorAttemptClaim(n) \/ ElectorAttemptWait(n) \/ BecomeMaster(n)
       \/ LeaderLoopTop(n) \/ LeaderRemoveExpired(n)
       \/ RollReadClock(n) \/ RollInstall(n) \/ RollPublish(n) \/ RollUpdatePrev(n)
       \/ HandleEvent(n)
       \/ IssueReadKey(n)
       \/ NodeExit(n) \/ Abort(n) \/ SessionClose(n)
    /\ UNCHANGED faults

MCInit ==
    /\ Init
    /\ faults = [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0,
                 stop |-> 0, restart |-> 0]

MCNext ==
    /\ ~targetFired
    /\ \/ MCTick
       \/ \E n \in Node :
            \/ MCReactive(n)
            \/ MCIssueReadClock(n)
            \/ MCCrash(n) \/ MCSessionExpire(n)
            \/ MCStartZkFail(n) \/ MCZkWriteFail(n)
            \/ MCNodeStop(n) \/ MCRestart(n)
       \/ \E v \in Node, t \in tokens : MCTargetCheck(v, t)

MCSpec == MCInit /\ [][MCNext]_mcVars

Symmetry == Permutations(Node)

(***************************************************************************)
(* Sanity (adhoc tla-patterns.md section 2): TLC must VIOLATE this, which  *)
(* shows the code path to the check (a token presented to a listening      *)
(* server, RPCS:1453 -> ATSM:139) is reachable.                            *)
(***************************************************************************)
TargetReached == ~(\E v \in Node, t \in tokens : alive[v] /\ listening[v])

MCTypeOK ==
    /\ TypeOK
    /\ faults.tokens <= MaxTokens /\ faults.crash <= MaxCrash
    /\ faults.expire <= MaxExpire /\ faults.zkFail <= MaxZkFail
    /\ faults.stop <= MaxStop /\ faults.restart <= MaxRestart

=============================================================================
