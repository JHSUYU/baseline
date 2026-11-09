---------------------------------- MODULE MC ----------------------------------
(***************************************************************************)
(* Model-checking wrapper for zk-adhoc-b2 (ad hoc check FRP:674).           *)
(*                                                                         *)
(* base.tla allows every interleaving the code allows. The workload's      *)
(* passing runs rely on two timing facts that no synchronization enforces  *)
(* (modeling-brief.md 3.1; analysis-report 5.7):                           *)
(*  T1 start before stop: a participant begins stop() only after every     *)
(*     participant returned from start() (LEST:253-255: an 18-20 ms start  *)
(*     phase vs. a 3000 ms sleep).                                         *)
(*  T2 near-simultaneous stops: once any participant began stop(), the     *)
(*     EventThread runs process() (ETCheckOffer, LES:329) for instance p   *)
(*     only after p began stop() too (stop spread 3-4 ms < first delete    *)
(*     completion 5-7 ms).                                                 *)
(* With every counter at 0 they encode the observed workload; each hunt    *)
(* relaxes exactly one of them, or injects the one fault (session expiry): *)
(*  MaxLateStart -- how many participants may still be before/inside       *)
(*                  start() when another begins stop()        (Scenario S1)*)
(*  MaxStopSkew  -- how many ETCheckOffer steps may run in the stop phase  *)
(*                  for an instance that has not begun stop() (Scenario S2;*)
(*                  also realization S1-ii)                                *)
(*  MaxExpire    -- ExpireSession steps on ExpirableSessions  (Scenario S3)*)
(* All other actions are reactive and unbounded.                           *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    s1, s2,             \* handles: s1 = the workload's shared handle (LEST:52);
                        \* s2 = a second client (the S3 variant's handle)
    SecondClient,       \* instances that use s2 (S3: one participant)
    ExpirableSessions,  \* handles the expiry fault may hit (brief 3.1: non-shared)
    MaxLateStart,
    MaxStopSkew,
    MaxExpire

ASSUME SecondClient \subseteq Participants
ASSUME ExpirableSessions \subseteq Sessions
ASSUME s1 \in Sessions /\ (SecondClient /= {} => s2 \in Sessions)
ASSUME MaxLateStart \in Nat /\ MaxStopSkew \in Nat /\ MaxExpire \in Nat

\* SessionOf for the model (cfg: SessionOf <- MCSessionOf).
MCSessionOf == [p \in Participants |-> IF p \in SecondClient THEN s2 ELSE s1]

VARIABLES
    lateStarts,  \* participants seen before/inside start() when another began stop() (T1)
    stopSkew,    \* stop-phase ETCheckOffer steps for an instance not yet in stop() (T2)
    expiries     \* ExpireSession steps taken (fault)

mcVars == <<lateStarts, stopSkew, expiries>>

\* start() has returned (LES:141) -- or the thread died with its session.
StartReturned(q) == pc[W(q)] \in {"sleep", "w_stop", "w_delete", "done", "dead"}
\* stop() has begun (LES:147-148).
StopBegun(q) == pc[W(q)] \in {"w_stop", "w_delete", "done"}

-----------------------------------------------------------------------------
(* Timing rule T1, relaxed by MaxLateStart (Scenario S1). *)
MCWStopBegin(p) ==
    LET late == {q \in Participants \ {p} : ~StartReturned(q)} IN
    /\ Cardinality(lateStarts \cup late) <= MaxLateStart
    /\ WStopBegin(p)
    /\ lateStarts' = lateStarts \cup late
    /\ UNCHANGED <<stopSkew, expiries>>

(* Timing rule T2, relaxed by MaxStopSkew (Scenario S2; S1-ii). *)
MCETCheckOffer(s, p) ==
    LET skew == (\E q \in Participants : StopBegun(q)) /\ ~StopBegun(p) IN
    /\ skew => stopSkew < MaxStopSkew
    /\ ETCheckOffer(s, p)
    /\ stopSkew' = IF skew THEN stopSkew + 1 ELSE stopSkew
    /\ UNCHANGED <<lateStarts, expiries>>

(* Fault: session expiry / close, bounded by MaxExpire (Scenario S3). *)
MCExpireSession(s) ==
    /\ s \in ExpirableSessions
    /\ expiries < MaxExpire
    /\ ExpireSession(s)
    /\ expiries' = expiries + 1
    /\ UNCHANGED <<lateStarts, stopSkew>>

-----------------------------------------------------------------------------
MCInit ==
    /\ Init
    /\ lateStarts = {}
    /\ stopSkew = 0
    /\ expiries = 0

MCNext ==
    \/ /\ ~targetFired
       /\ \/ /\ ReactiveNext
             /\ UNCHANGED mcVars
          \/ \E p \in Participants : MCWStopBegin(p)
          \/ \E s \in Sessions, p \in Participants : MCETCheckOffer(s, p)
          \/ \E s \in Sessions : MCExpireSession(s)
    \/ /\ targetFired \/ Quiescent
       /\ UNCHANGED <<vars, mcVars>>

MCSpec == MCInit /\ [][MCNext]_<<vars, mcVars>>

\* Participants on the same handle are interchangeable (ids are not
\* permuted: they are handed out in server order).
MCSymmetry == Permutations(Participants \ SecondClient)

-----------------------------------------------------------------------------
(* Attribution probes (optional, brief 3.1 `firedBy`): TargetSafe restricted *)
(* to one removal kind. A firing of another kind ends that branch (Next     *)
(* stops after targetFired) without violating the probe, so a hunt can be   *)
(* re-run with a probe to ask whether a specific realization is reachable.  *)
TargetSafePeerStop == ~(targetFired /\ firedBy = "peerStop")
TargetSafeSelfStop == ~(targetFired /\ firedBy = "selfStop")
TargetSafeExpiry   == ~(targetFired /\ firedBy = "expiry")

(* Fault-setup liveness probes (brief-coverage.md): each must be VIOLATED   *)
(* under its hunt cfg's bounds, showing the hunt's counter is actually used. *)
LateStartUnused == lateStarts = {}
StopSkewUnused  == stopSkew = 0
ExpiryUnused    == expiries = 0

===============================================================================
