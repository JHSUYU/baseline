--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hdfs-adhoc-11).                    *)
(*                                                                         *)
(* Counter-bounded (time and faults; one counter per mechanism):           *)
(*   rolls[n] < MaxRolls  RollKeys: interval rolls, i.e. time    S1-S3, S5  *)
(*   safe   EnterSafeMode  manual/resource-low safe mode    S1, S5          *)
(*   lost   LoseResponse   heartbeat reply lost after build  S2 (S5 alt)    *)
(*   nnrst  NNRestart                                        S4             *)
(*   dnrst  DNRestart                                        S4             *)
(*   fo     Failover                                         S5             *)
(* Scope constants (they only remove behaviors):                           *)
(*   SafeModeRoles  HA role an NN must hold to enter safe mode: {"active"}  *)
(*                  for S1, {"standby"} for S5 (keeps S1's active-side      *)
(*                  path out of the S5 hunt)                                *)
(*   LossRoles      HA role of the NN that built a reply that may be lost   *)
(*   DekNeedsRegisteredDNs  TRUE: an NN issues a DEK only when every up DN  *)
(*                  is registered with its current incarnation. TRUE only   *)
(*                  for S5, so its hunt answers MC-5 (suppressed or lost    *)
(*                  pushes), not a DN-startup registration lag between two  *)
(*                  NNs. FALSE elsewhere; S4's forward case needs FALSE.    *)
(* Unbounded (deterministic, reactive, or ordinary client behavior):        *)
(*   Monitor first pass and sweep, heartbeat build/delivery, command        *)
(*   processing, registration steps, block reports, LeaveSafeMode, DNStart  *)
(*   (only LateDNs start down), client DEK fetch/drop/connect, DnTransfer   *)
(*   (only with DnTransferOn).                                              *)
(*                                                                         *)
(* Every wrapper is guarded by Live == ~targetFired, so a counterexample    *)
(* ends at the step that throws at BlockTokenSecretManager.java:559-561.    *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxRolls,           \* interval rolls per NN; each stands for one keyUpdateInterval
    MaxSafeModeEnter,   \* S1 / S5
    MaxLostResp,        \* S2 (S5 alternative)
    MaxNNRestart,       \* S4
    MaxDNRestart,       \* S4
    MaxFailover,        \* S5
    SafeModeRoles,      \* scope: HA roles in which EnterSafeMode may fire
    LossRoles,          \* scope: HA role (in the reply) of NNs whose replies may be lost
    DekNeedsRegisteredDNs, \* scope: DEKs only from an NN every up DN is registered with
    MaxQueue            \* state constraint: length of each command queue

ASSUME MaxRolls \in Nat /\ MaxSafeModeEnter \in Nat /\ MaxLostResp \in Nat
ASSUME MaxNNRestart \in Nat /\ MaxDNRestart \in Nat /\ MaxFailover \in Nat
ASSUME SafeModeRoles \subseteq {"active", "standby"}
ASSUME LossRoles \subseteq {"active", "standby"}
ASSUME DekNeedsRegisteredDNs \in BOOLEAN
ASSUME MaxQueue \in Nat \ {0}

VARIABLE faults

mcVars == <<vars, faults>>

Live == ~targetFired

-----------------------------------------------------------------------------
(* Counter-bounded wrappers                                                 *)

\* Time. rolls[n] (base.tla) counts n's interval rolls over all incarnations.
MCRollKeys(n) ==
    /\ Live
    /\ rolls[n] < MaxRolls
    /\ RollKeys(n)
    /\ UNCHANGED faults

MCEnterSafeMode(n) ==
    /\ Live
    /\ faults.safe < MaxSafeModeEnter
    /\ nnHA[n] \in SafeModeRoles
    /\ EnterSafeMode(n)
    /\ faults' = [faults EXCEPT !.safe = @ + 1]

MCLoseResponse(n, d) ==
    /\ Live
    /\ faults.lost < MaxLostResp
    /\ resp[n][d] # Null
    /\ resp[n][d].ha \in LossRoles
    /\ LoseResponse(n, d)
    /\ faults' = [faults EXCEPT !.lost = @ + 1]

MCNNRestart(n) ==
    /\ Live
    /\ faults.nnrst < MaxNNRestart
    /\ NNRestart(n)
    /\ faults' = [faults EXCEPT !.nnrst = @ + 1]

MCDNRestart(d) ==
    /\ Live
    /\ faults.dnrst < MaxDNRestart
    /\ DNRestart(d)
    /\ faults' = [faults EXCEPT !.dnrst = @ + 1]

MCFailover(n, m) ==
    /\ Live
    /\ faults.fo < MaxFailover
    /\ Failover(n, m)
    /\ faults' = [faults EXCEPT !.fo = @ + 1]

-----------------------------------------------------------------------------
(* Unbounded wrappers (named, so TLC labels counterexample steps)           *)

MCMonitorFirstPass(n)          == Live /\ MonitorFirstPass(n)          /\ UNCHANGED faults
MCSweepNeedKeyUpdate(n)        == Live /\ SweepNeedKeyUpdate(n)        /\ UNCHANGED faults
MCLeaveSafeMode(n)             == Live /\ LeaveSafeMode(n)             /\ UNCHANGED faults
\* Scope (only removes behaviors): with DekNeedsRegisteredDNs, the issuer's key
\* stream has reached every up DN through registration (DM:1209; BPOS:436-440).
MCDekIssuerKnown(n) ==
    IF DekNeedsRegisteredDNs
      THEN \A d \in DNs : IF dnUp[d] THEN actor[n][d] = "reg" /\ d \in hbSet[n] ELSE TRUE
      ELSE TRUE

MCClientGetDek(n) == Live /\ MCDekIssuerKnown(n) /\ ClientGetDek(n) /\ UNCHANGED faults
MCNNHandleHeartbeat(n, d)      == Live /\ NNHandleHeartbeat(n, d)      /\ UNCHANGED faults
MCDNReceiveResponse(n, d)      == Live /\ DNReceiveResponse(n, d)      /\ UNCHANGED faults
MCDNProcessKeyCommand(n, d)    == Live /\ DNProcessKeyCommand(n, d)    /\ UNCHANGED faults
MCDNTakeRegisterCommand(n, d)  == Live /\ DNTakeRegisterCommand(n, d)  /\ UNCHANGED faults
MCDNBlockReport(n, d)          == Live /\ DNBlockReport(n, d)          /\ UNCHANGED faults
MCNNRegisterDatanode(n, d)     == Live /\ NNRegisterDatanode(n, d)     /\ UNCHANGED faults
MCNNRegJoin(n, d)              == Live /\ NNRegJoin(n, d)              /\ UNCHANGED faults
MCDNRegistrationSucceeded(n, d) == Live /\ DNRegistrationSucceeded(n, d) /\ UNCHANGED faults
MCDNStart(d)                   == Live /\ DNStart(d)                   /\ UNCHANGED faults
MCClientConnect(d)             == Live /\ ClientConnect(d)             /\ UNCHANGED faults
MCDnTransfer(s, d)             == Live /\ DnTransfer(s, d)             /\ UNCHANGED faults
MCClientDropDek                == Live /\ ClientDropDek                /\ UNCHANGED faults

-----------------------------------------------------------------------------
(* Specification                                                            *)

MCInit ==
    /\ Init
    /\ faults = [safe |-> 0, lost |-> 0, nnrst |-> 0, dnrst |-> 0, fo |-> 0]

MCNext ==
    \/ \E n \in NNs :
         \/ MCMonitorFirstPass(n)
         \/ MCRollKeys(n)
         \/ MCSweepNeedKeyUpdate(n)
         \/ MCNNRestart(n)
         \/ MCEnterSafeMode(n)
         \/ MCLeaveSafeMode(n)
         \/ MCClientGetDek(n)
    \/ \E n, m \in NNs : MCFailover(n, m)
    \/ \E n \in NNs, d \in DNs :
         \/ MCNNHandleHeartbeat(n, d)
         \/ MCDNReceiveResponse(n, d)
         \/ MCLoseResponse(n, d)
         \/ MCDNProcessKeyCommand(n, d)
         \/ MCDNTakeRegisterCommand(n, d)
         \/ MCDNBlockReport(n, d)
         \/ MCNNRegisterDatanode(n, d)
         \/ MCNNRegJoin(n, d)
         \/ MCDNRegistrationSucceeded(n, d)
    \/ \E d \in DNs :
         \/ MCDNRestart(d)
         \/ MCDNStart(d)
         \/ MCClientConnect(d)
    \/ \E s, d \in DNs : MCDnTransfer(s, d)
    \/ MCClientDropDek

MCSpec == MCInit /\ [][MCNext]_mcVars

-----------------------------------------------------------------------------
(* State constraint and MC-level invariants                                 *)

\* A DN's actor keeps heartbeating while its command thread is busy, so
\* duplicate REGISTER commands can pile up (BPSA:745-756, 1519-1524).
\* Extra duplicates only re-register again (keys only grow); the bound keeps
\* the state space finite.
QueueBound == \A n \in NNs, d \in DNs : Len(dnQ[n][d]) <= MaxQueue

FaultsBounded ==
    /\ faults.safe <= MaxSafeModeEnter
    /\ faults.lost <= MaxLostResp
    /\ faults.nnrst <= MaxNNRestart
    /\ faults.dnrst <= MaxDNRestart
    /\ faults.fo <= MaxFailover
    /\ \A n \in NNs : rolls[n] <= MaxRolls

=============================================================================
