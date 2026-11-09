------------------------------- MODULE MC -------------------------------
(***************************************************************************)
(* Model checking wrapper for hdfs-adhoc-k1.                               *)
(*                                                                         *)
(* Bounded (they introduce nondeterminism):                                *)
(*   Tick (MaxTime), connection starts (MaxInFlight, actor switches),      *)
(*   heartbeat-response loss (S2a), declare-dead (S2b), safe-mode entry    *)
(*   (S3), NN restart and DN restart (S4).                                 *)
(* Not bounded (reactive): roll update/mark, registration steps, heartbeat *)
(* handling and receipt, Balancer start/poll, TargetCheck, LeaveSafeMode.  *)
(* BalancerClose is left out of MCNext: closing only discards the cached  *)
(* DEK (it can only remove S1 behaviors); it exists for trace validation. *)
(*                                                                         *)
(* Scenario -> counters:                                                   *)
(*   S1 stale Balancer DEK      : none (time only)                         *)
(*   S2 missed key update       : LossLimit, DeadLimit, InitLastRoll range *)
(*   S3 safe mode               : SafeModeLimit                            *)
(*   S4 NN key set not persistent: NNRestartLimit, DNRestartLimit          *)
(***************************************************************************)
EXTENDS base

B == INSTANCE base

CONSTANTS
    MaxTime,            \* bound on the clock
    MaxInFlight,        \* bound on concurrently open SASL connections
    BalancerEnabled,    \* a Balancer/Mover run exists in this model
    ClientEnabled,      \* a DFSClient doing encrypted reads/writes exists
    DNTransferEnabled,  \* DN->DN encrypted transfers happen
    LossLimit,          \* S2(a) lost heartbeat responses
    DeadLimit,          \* S2(b) declare-dead + re-register
    SafeModeLimit,      \* S3 safe-mode entries
    NNRestartLimit,     \* S4
    DNRestartLimit      \* S4

ASSUME MaxTime \in Nat /\ MaxInFlight \in Nat
ASSUME {BalancerEnabled, ClientEnabled, DNTransferEnabled} \subseteq BOOLEAN
ASSUME {LossLimit, DeadLimit, SafeModeLimit, NNRestartLimit, DNRestartLimit} \subseteq Nat

VARIABLE faults
faultVars == <<faults>>

\* Every Monitor phase for the first roll: lastBlockKeyUpdate in -(I+1)..0
\* makes the first roll due at any time in 0..I+1 (HBM:427,434,439).
\* Used as `InitLastRoll <- MCInitLastRollAll` (cfg files cannot hold
\* negative literals).
MCInitLastRollAll == (-(I + 1))..0

(***************************************************************************)
(* Constrained wrappers                                                    *)
(***************************************************************************)
MCTick ==
    /\ now < MaxTime
    /\ B!Tick
    /\ UNCHANGED faultVars

MCBalancerStart ==
    /\ BalancerEnabled
    /\ B!BalancerStart
    /\ UNCHANGED faultVars

MCBalancerConnect(d) ==
    /\ BalancerEnabled
    /\ InFlight < MaxInFlight
    /\ B!BalancerConnect(d)
    /\ UNCHANGED faultVars

MCClientConnect(c, d) ==
    /\ ClientEnabled
    /\ InFlight < MaxInFlight
    /\ B!ClientConnect(c, d)
    /\ UNCHANGED faultVars

MCDNTransfer(s, t) ==
    /\ DNTransferEnabled
    /\ InFlight < MaxInFlight
    /\ B!DNTransfer(s, t)
    /\ UNCHANGED faultVars

MCLoseHeartbeatResp(d) ==
    /\ faults.loss < LossLimit
    /\ B!LoseHeartbeatResp(d)
    /\ faults' = [faults EXCEPT !.loss = @ + 1]

MCNNDeclareDead(d) ==
    /\ faults.dead < DeadLimit
    /\ B!NNDeclareDead(d)
    /\ faults' = [faults EXCEPT !.dead = @ + 1]

MCEnterSafeMode ==
    /\ faults.safeMode < SafeModeLimit
    /\ B!EnterSafeMode
    /\ faults' = [faults EXCEPT !.safeMode = @ + 1]

MCNNRestart ==
    /\ faults.nnRestart < NNRestartLimit
    /\ B!NNRestart
    /\ faults' = [faults EXCEPT !.nnRestart = @ + 1]

MCDNRestart(d) ==
    /\ faults.dnRestart < DNRestartLimit
    /\ B!DNRestart(d)
    /\ faults' = [faults EXCEPT !.dnRestart = @ + 1]

(***************************************************************************)
(* Init / Next                                                             *)
(***************************************************************************)
MCInit ==
    /\ B!Init
    /\ faults = [loss |-> 0, dead |-> 0, safeMode |-> 0,
                 nnRestart |-> 0, dnRestart |-> 0]

MCNextReactive ==
    \/ B!NNRollUpdate
    \/ B!NNRollMark
    \/ \E d \in DNs :
         \/ B!RegSnapshot(d)
         \/ B!RegAddToList(d)
         \/ B!DNRegistrationSucceeded(d)
         \/ B!DNRegAddKeys(d)
         \/ B!NNHandleHeartbeat(d)
         \/ B!DNRecvHeartbeat(d)
    \/ (BalancerEnabled /\ B!BalancerPoll)
    \/ \E c \in BagToSet(conns) : B!TargetCheck(c)
    \/ B!LeaveSafeMode

MCNext ==
    /\ ~targetFired
    /\ \/ MCTick
       \/ (MCNextReactive /\ UNCHANGED faultVars)
       \/ MCBalancerStart
       \/ \E d \in DNs :
            \/ MCBalancerConnect(d)
            \/ \E c \in Clients : MCClientConnect(c, d)
            \/ MCLoseHeartbeatResp(d)
            \/ MCNNDeclareDead(d)
            \/ MCDNRestart(d)
       \/ \E s, t \in DNs : MCDNTransfer(s, t)
       \/ MCEnterSafeMode
       \/ MCNNRestart

mcVars == <<vars, faultVars>>

MCSpec == MCInit /\ [][MCNext]_mcVars

(***************************************************************************)
(* Symmetry, invariants                                                    *)
(***************************************************************************)
DNSymmetry == Permutations(DNs)

MCTypeOK ==
    /\ TypeOK
    /\ faults.loss <= LossLimit
    /\ faults.dead <= DeadLimit
    /\ faults.safeMode <= SafeModeLimit
    /\ faults.nnRestart <= NNRestartLimit
    /\ faults.dnRestart <= DNRestartLimit
    /\ now <= MaxTime

\* Sanity (tla-patterns 2): TEMPORARY invariant that TLC must VIOLATE.  A
\* state where TargetCheck is enabled and reaches retrieveDataEncryptionKey
\* (the DN's pool manager exists, so BPTSM:142 calls BTSM:476).
TargetNotReached == ~(\E c \in BagToSet(conns) : dnMgr[c.dst])

\* Extra sanity used only by MC_sanity_reach.cfg: some guard evaluation
\* happens after at least one key roll (the model exercises rolls).
TargetNotReachedAfterRoll ==
    ~(\E c \in BagToSet(conns) : dnMgr[c.dst] /\ nnSerial > nnInc * KeyIdBase + 2)

=============================================================================
