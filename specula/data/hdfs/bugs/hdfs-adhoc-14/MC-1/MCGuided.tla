------------------------------ MODULE MCGuided ------------------------------
(***************************************************************************)
(* Pruning-only scheduling guides for the hdfs-adhoc-14 hunts (Phase 3).   *)
(* base.tla and MC.tla in this directory are byte-identical copies of      *)
(* spec/base.tla and spec/MC.tla.  Each guide is used as an                *)
(* ACTION_CONSTRAINT: it only removes transitions, so every violation      *)
(* found under it is a violation of the parent hunt configuration.         *)
(***************************************************************************)
EXTENDS MC

\* HeartbeatManager.Monitor (HBM:552-557): when shouldUpdateBlockKey returns
\* true, the same thread runs the mark loop at once.  The model splits the two
\* statements (NNRotate, NNMarkKeyUpdate), so it can schedule arbitrarily many
\* other steps in a gap that lasts microseconds in the code.  This guide lets
\* only the mark (or a restart) follow a rotation.
GuideMarkFollowsRotate == \A n \in NN : markPending[n] => ~markPending'[n]

\* Excludes window W4: no rotation while a registration has exported its keys
\* (DM:1209) but has not joined the live list yet (DM:1300 / DM:1337).
GuideNoRotateInRegGap ==
    mc'.rot > mc.rot => \A n \in NN, d \in DN : reg[n][d].st # "exported"

\* Reachability probe (not a guide): the StartRegistered = TRUE initial state
\* (every DN registered with the active NN's first current key, the NN's ACTIVE
\* claim acknowledged, nothing in flight, no rotation yet) is reachable from the
\* StartRegistered = FALSE initial state.  TLC must report it violated.
ProbeSteadyStateNotReached ==
    ~( /\ mc.rot = 0
       /\ \A n \in NN : live[n] = DN /\ known[n] = DN /\ needKU[n] = {}
       /\ \A d \in DN :
             /\ dnCur[d] = InitKeyIds[InitActive].cur
             /\ dnKeys[d] = UNION {{InitKeyIds[n].cur, InitKeyIds[n].next} : n \in NN}
             /\ bpActive[d] = InitActive
             /\ lastClaim[d] = 1
             /\ \A n \in NN : /\ act[d][n] = "run"
                              /\ astate[d][n] = (IF n = InitActive THEN "active" ELSE "standby")
                              /\ cmdQ[d][n] = <<>>
                              /\ hb[n][d] = HBIdle
                              /\ reg[n][d] = RegNone
       /\ ops = {} )

\* Refinement of TargetSafe (violated only where TargetSafe is): the firing
\* token is OLDER than the secret it was re-signed with, i.e. a pre-rotation
\* token re-signed by a DN that had already applied the key update.
TargetSafeOldToken == ~(targetFired /\ fireInfo.kid < fireInfo.sk)
=============================================================================
