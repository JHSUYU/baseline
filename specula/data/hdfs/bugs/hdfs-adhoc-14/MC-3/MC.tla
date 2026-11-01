--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hdfs-adhoc-14, BTSM:418).           *)
(*                                                                         *)
(* Bounded: actions that introduce nondeterminism -- the Monitor's key     *)
(* rotation timer, HA failover, NN restart, dead-node removal, and the     *)
(* workload's client operations and NN-scheduled replications.            *)
(* Unbounded: every reactive step (heartbeat handling, registration,      *)
(* command processing, the DataTransferProtocol steps, TargetCheck).      *)
(*                                                                         *)
(* Each wrapper is a named action guarded by Live == ~targetFired, so     *)
(* TLC labels counterexample steps with these names and stops after the   *)
(* target fires.                                                           *)
(***************************************************************************)
EXTENDS base, TLC

CONSTANTS
    MaxRotations,   \* NNRotate: HeartbeatManager.Monitor key rotation (CLOCK)
    MaxFailovers,   \* NNFailover (HA, Scenario 3)
    MaxRestarts,    \* NNRestart (Scenario 4)
    MaxDeadNodes,   \* NNRemoveDeadDatanode: dead-node removal => REGISTER (Scenario 3, W6)
    MaxWrites,      \* ClientAddBlock: client write pipelines
    MaxReads,       \* ClientGetBlockLocations: reads / checksums (workload, sanity)
    MaxXfers        \* NNScheduleReplication: multi-target replication (Scenario 2)

\* Key expiry (BTSM:210-219 removeExpiredKeys) is not modeled.  With the
\* default I = L = 600 min (DFSConfigKeys:1092-1095) no key expires before the
\* third rotation of an NN process, so at most two rotations are allowed.
ASSUME MaxRotations \in 0..2
ASSUME \A c \in {MaxFailovers, MaxRestarts, MaxDeadNodes, MaxWrites, MaxReads, MaxXfers} :
          c \in Nat

VARIABLES
    mc,                 \* fault / operation counters
    regCurFromStandby   \* [DN -> BOOLEAN] history for Scenario 3 (W6): the DN's
                        \*   current key was last installed by a registration with
                        \*   an NN that was standby at that moment (BPOS:436-440
                        \*   with a stale ACTIVE actor state)

mcVars == <<mc, regCurFromStandby>>

\* Operation ids are 1..MaxOps: every operation is created by a bounded action.
MaxOps == MaxWrites + MaxReads + MaxXfers
allVars == <<vars, mcVars>>

MCInit ==
    /\ Init
    /\ mc = [rot |-> 0, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 0, r |-> 0, x |-> 0]
    /\ regCurFromStandby = [d \in DN |-> FALSE]

Live == ~targetFired

-----------------------------------------------------------------------------
(* Bounded actions *)
MCNNRotate(n) ==
    /\ Live /\ mc.rot < MaxRotations
    /\ NNRotate(n)
    /\ mc' = [mc EXCEPT !.rot = @ + 1]
    /\ UNCHANGED regCurFromStandby

MCNNFailover(a, b) ==
    /\ Live /\ mc.fo < MaxFailovers
    /\ NNFailover(a, b)
    /\ mc' = [mc EXCEPT !.fo = @ + 1]
    /\ UNCHANGED regCurFromStandby

MCNNRestart(n) ==
    /\ Live /\ mc.rs < MaxRestarts
    /\ NNRestart(n)
    /\ mc' = [mc EXCEPT !.rs = @ + 1]
    /\ UNCHANGED regCurFromStandby

MCNNRemoveDeadDatanode(n, d) ==
    /\ Live /\ mc.dead < MaxDeadNodes
    /\ NNRemoveDeadDatanode(n, d)
    /\ mc' = [mc EXCEPT !.dead = @ + 1]
    /\ UNCHANGED regCurFromStandby

MCClientAddBlock(n, p) ==
    /\ Live /\ mc.w < MaxWrites
    /\ ClientAddBlock(n, p)
    /\ mc' = [mc EXCEPT !.w = @ + 1]
    /\ UNCHANGED regCurFromStandby

MCClientGetBlockLocations(n) ==
    /\ Live /\ mc.r < MaxReads
    /\ ClientGetBlockLocations(n)
    /\ mc' = [mc EXCEPT !.r = @ + 1]
    /\ UNCHANGED regCurFromStandby

MCNNScheduleReplication(n, s, g) ==
    /\ Live /\ mc.x < MaxXfers
    /\ NNScheduleReplication(n, s, g)
    /\ mc' = [mc EXCEPT !.x = @ + 1]
    /\ UNCHANGED regCurFromStandby

-----------------------------------------------------------------------------
(* Reactive actions (unbounded) *)
MCNNMarkKeyUpdate(n) == Live /\ NNMarkKeyUpdate(n) /\ UNCHANGED mcVars
MCNNHandleHeartbeat(n, d) == Live /\ NNHandleHeartbeat(n, d) /\ UNCHANGED mcVars
MCNNHeartbeatClearKeyUpdate(n, d) ==
    Live /\ NNHeartbeatClearKeyUpdate(n, d) /\ UNCHANGED mcVars
MCNNRegisterExport(n, d) == Live /\ NNRegisterExport(n, d) /\ UNCHANGED mcVars
MCNNRegisterJoin(n, d) == Live /\ NNRegisterJoin(n, d) /\ UNCHANGED mcVars
MCDNHandshake(d, n) == Live /\ DNHandshake(d, n) /\ UNCHANGED mcVars

MCDNRegistrationSucceeded(d, n) ==
    /\ Live
    /\ DNRegistrationSucceeded(d, n)
    /\ UNCHANGED mc
    /\ regCurFromStandby' = [regCurFromStandby EXCEPT ![d] =
                                IF dnCur'[d] # dnCur[d] THEN role[n] = "standby" ELSE @]

MCDNHandleHeartbeatResponse(d, n) ==
    Live /\ DNHandleHeartbeatResponse(d, n) /\ UNCHANGED mcVars

MCDNProcessCommand(d, n) ==
    /\ Live
    /\ DNProcessCommand(d, n)
    /\ UNCHANGED mc
    /\ regCurFromStandby' = [regCurFromStandby EXCEPT ![d] =
                                IF dnCur'[d] # dnCur[d] THEN FALSE ELSE @]

MCClientFetchDEK(n) == Live /\ ClientFetchDEK(n) /\ UNCHANGED mcVars
MCClientConnect(i, d) == Live /\ ClientConnect(i, d) /\ UNCHANGED mcVars
MCDNTransferCreateToken(i) == Live /\ DNTransferCreateToken(i) /\ UNCHANGED mcVars
MCDNSaslSendEncrypted(i) == Live /\ DNSaslSendEncrypted(i) /\ UNCHANGED mcVars
MCDNSaslReceiveEncrypted(i) == Live /\ DNSaslReceiveEncrypted(i) /\ UNCHANGED mcVars
MCTargetCheck(i) == Live /\ TargetCheck(i) /\ UNCHANGED mcVars
MCDNWriteBlockMirrorSecret(i) == Live /\ DNWriteBlockMirrorSecret(i) /\ UNCHANGED mcVars

-----------------------------------------------------------------------------
MCNext ==
    \/ \E n \in NN : MCNNRotate(n)
    \/ \E n \in NN : MCNNMarkKeyUpdate(n)
    \/ \E n \in NN, d \in DN : MCNNHandleHeartbeat(n, d)
    \/ \E n \in NN, d \in DN : MCNNHeartbeatClearKeyUpdate(n, d)
    \/ \E n \in NN, d \in DN : MCNNRegisterExport(n, d)
    \/ \E n \in NN, d \in DN : MCNNRegisterJoin(n, d)
    \/ \E d \in DN, n \in NN : MCDNHandshake(d, n)
    \/ \E d \in DN, n \in NN : MCDNRegistrationSucceeded(d, n)
    \/ \E d \in DN, n \in NN : MCDNHandleHeartbeatResponse(d, n)
    \/ \E d \in DN, n \in NN : MCDNProcessCommand(d, n)
    \/ \E n \in NN : MCClientFetchDEK(n)
    \/ \E i \in 1..MaxOps, d \in DN : MCClientConnect(i, d)
    \/ \E i \in 1..MaxOps : MCDNTransferCreateToken(i)
    \/ \E i \in 1..MaxOps : MCDNSaslSendEncrypted(i)
    \/ \E i \in 1..MaxOps : MCDNSaslReceiveEncrypted(i)
    \/ \E i \in 1..MaxOps : MCTargetCheck(i)
    \/ \E i \in 1..MaxOps : MCDNWriteBlockMirrorSecret(i)
    \/ \E n \in NN : \E p \in AllPipelines : MCClientAddBlock(n, p)
    \/ \E n \in NN : MCClientGetBlockLocations(n)
    \/ \E n \in NN, s \in DN : \E g \in AllXferTargets : MCNNScheduleReplication(n, s, g)
    \/ \E a, b \in NN : MCNNFailover(a, b)
    \/ \E n \in NN : MCNNRestart(n)
    \/ \E n \in NN, d \in DN : MCNNRemoveDeadDatanode(n, d)

MCSpec == MCInit /\ [][MCNext]_allVars

\* DataNodes are interchangeable (model values; Init is uniform over DN).
DNSymmetry == Permutations(DN)

-----------------------------------------------------------------------------
(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)
\* TargetSafe, TypeOK and TokenProvenance come from base.tla.

\* Sanity probe (tla-patterns 2): TargetCheck is enabled in some reachable
\* state.  Enable it alone in MC_sanity_reach.cfg; TLC must report it violated.
TargetReached == ~(\E op \in ops : op.ph = "check" /\ Ready(op.pipe[op.pos]))

\* ---- Refinements of TargetSafe that select HOW the target fires.  Each is
\* violated only in states where TargetSafe is violated too; a hunt that
\* enables one of them alone keeps searching past shorter firings of other
\* windows.  (TargetCheck leaves every NN/DN variable unchanged and nothing
\* runs after it, so they read the state at the firing.)

\* Scenario 1, windows W3/W4 (brief 2): the token carries the active NN's
\* current key, the re-signing DN r used (and still holds) an older current
\* key, and no push that would install the token's key as r's current key is
\* pending anywhere.  r then re-signs every current token wrongly until the next
\* rotation: the rotation's push to r was lost (W3: BM:1675-1676 vs
\* HBM:552-557) or never made (W4: DM:1209 vs DM:1300/1337).  A firing through
\* an ordinary in-flight push (W1), or with an older token, does not satisfy this.
PendingPushOf(n, r, k) ==
    \* the NN's next export to r will carry k as current
    \/ /\ k = nnCur[n]
       /\ \/ r \in needKU[n]
          \/ markPending[n] /\ r \in live[n]
          \/ reg[n][r].st = "want"
    \* an export with current key k is on its way to r or queued at r
    \/ hb[n][r].ku # NoEx /\ hb[n][r].ku.cur = k
    \/ \E i \in 1..Len(cmdQ[r][n]) :
          cmdQ[r][n][i].t = "ku" /\ cmdQ[r][n][i].ex.cur = k
    \/ reg[n][r].st \in {"exported", "joined"} /\ reg[n][r].ex.cur = k

FiredOnLostPush ==
    /\ targetFired
    /\ fireInfo.rsr # None
    /\ \E n \in NN :
          /\ role[n] = "active"
          /\ fireInfo.kid = nnCur[n]
          /\ dnCur[fireInfo.rsr] = fireInfo.sk
          /\ ~PendingPushOf(n, fireInfo.rsr, fireInfo.kid)

TargetSafeLostPush == ~FiredOnLostPush

\* Scenario 3, window W6 (brief 2): the secret the re-signing DN used is its
\* current key, and that key was installed by a registration whose actor state
\* said ACTIVE while that NN was standby.  A firing through the failover lag
\* (W5), or with a secret snapshotted before such an install, does not
\* satisfy this.
FiredOnStaleReg ==
    /\ targetFired
    /\ fireInfo.rsr # None
    /\ regCurFromStandby[fireInfo.rsr]
    /\ dnCur[fireInfo.rsr] = fireInfo.sk

TargetSafeStaleReg == ~FiredOnStaleReg

\* Scenario 4 analysis helper (not enabled in any cfg; MC_hunt_s4_nn_restart.cfg
\* is isolated by MaxRotations = 0 instead): the firing token was issued by an
\* earlier NN process than the one running now (an in-flight old-incarnation
\* token).  Evaluate it on the final state of a counterexample to classify it.
FiredOnOldIncarnation ==
    /\ targetFired
    /\ \E op \in ops :
          /\ op.ph = "check"
          /\ op.tok.iss # None
          /\ op.tok.inc < nnInc[op.tok.iss]
          /\ op.pipe[op.pos] = fireInfo.dn
          /\ op.tok.kid = fireInfo.kid
          /\ op.tok.sk = fireInfo.sk

=============================================================================
