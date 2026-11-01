------------------------------- MODULE MCGated -------------------------------
(***************************************************************************)
(* Pruning-only guides for the hunts of MC.tla (hdfs-adhoc-11, Phase 3).    *)
(* base.tla and MC.tla in this directory are byte-identical copies of       *)
(* spec/base.tla and spec/MC.tla. Each G_*.cfg keeps SPECIFICATION MCSpec   *)
(* and the constants of its parent hunt config, and adds                    *)
(*  - an ACTION_CONSTRAINT built from the guides below. Each guide only     *)
(*    restricts steps that never fire the target (a roll, a safe-mode       *)
(*    entry, an NN restart, a client DEK fetch), so it only removes         *)
(*    behaviors; TLC checks invariants before it applies the constraint,    *)
(*    which is harmless here because no restricted step fires the target;  *)
(*  - optionally an invariant whose violation implies a TargetSafe          *)
(*    violation, to select how the target fires.                            *)
(* A violation found here is therefore a TargetSafe violation of the        *)
(* parent hunt config, in a narrower shape.                                 *)
(***************************************************************************)
EXTENDS MC

\* An interval roll never falls inside a registration RPC at that NN: no
\* roll while a registerDatanode export is in flight or its reply is not yet
\* processed by the DN (reg[n][d] # Null). An NNRestart is not a roll.
NoRollDuringReg ==
    \A n \in NNs :
        IF nnInc'[n] = nnInc[n] /\ nnTop'[n] > nnTop[n]
          THEN \A d \in DNs : reg[n][d] = Null
          ELSE TRUE

\* Manual / resource-low safe mode starts while every DN is in sync with that
\* NN: no roll waiting for its sweep, no flag set, no push in flight or queued.
SafeEntrySynced ==
    \A n \in NNs :
        IF nnSafe[n] = "off" /\ nnSafe'[n] = "manual"
          THEN /\ ~sweepPending[n]
               /\ \A d \in DNs : /\ ~needKU[n][d]
                                 /\ ~RespHasKey(resp[n][d])
                                 /\ ~HasKeyCmd(dnQ[n][d])
          ELSE TRUE

\* An NN restart happens in steady state: every up DN is registered with the
\* NN's current incarnation.
RestartAfterReg ==
    \A n \in NNs :
        IF nnInc'[n] > nnInc[n]
          THEN \A d \in DNs : IF dnUp[d] THEN actor[n][d] = "reg" /\ d \in hbSet[n]
                                         ELSE TRUE
          ELSE TRUE

\* The client never fetches a DEK, so only a DN->DN transfer can reach the
\* lookup with a key id.
NoClientDek == cDek' = cDek

GuideSynced     == NoRollDuringReg /\ SafeEntrySynced
GuideSteady     == RestartAfterReg
GuideDnTransfer == RestartAfterReg /\ NoClientDek

\* Target fired by a client whose DEK is from an older incarnation of its
\* issuer (Scenario 4a, backward). Use with DnTransferOn = FALSE.
TargetSafeBackward ==
    ~(targetFired /\ cDek # Null /\ cDek.key[2] < nnInc[cDek.iss])

\* ... from the issuer's current incarnation (Scenario 4b, forward).
TargetSafeForward ==
    ~(targetFired /\ cDek # Null /\ cDek.key[2] = nnInc[cDek.iss])

=============================================================================
