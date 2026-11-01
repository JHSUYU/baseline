---------------------------------- MODULE MC ----------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hdfs-adhoc-07).                     *)
(*                                                                          *)
(* Counter-bounded (they introduce nondeterminism outside normal operation):*)
(*   JNCrash               MaxJNCrash       JN process crash (restart free) *)
(*   RpcDrop               MaxDrop          call lost before the JN         *)
(*   RpcLate               MaxLate          writer sees failure, JN runs    *)
(*                                          the call later                  *)
(*   JN handler, lose=TRUE MaxLoseReply     JN ran it, writer sees failure  *)
(*   ChReject              MaxReject        sendEdits refused while earlier *)
(*                                          edits are queued (ILC 345-349)  *)
(*   JNAcceptRecoveryCrash MaxAcceptCrash   crash at J 977 (Scenario 3)     *)
(*   WCrash                MaxWCrash        writer process death / timeout  *)
(*   WPurgeLogsOlderThan   MaxPurge         checkpoint purge (Scenario 1)   *)
(* Writer failover is bounded by NW (number of QJM instances).              *)
(*                                                                          *)
(* Unbounded (reactive / normal operation): dispatch, every JN handler      *)
(* run, TargetCheck, connection refused to a down JN, JN restart, every     *)
(* writer quorum step, writes up to MaxTxId, the heartbeat throttle         *)
(* (1 s; time is free).                                                     *)
(*                                                                          *)
(* NameNode-usage realism (FSEditLog), applied here and not in base.tla so  *)
(* that trace validation can replay the workload test, which drives the    *)
(* QJM API directly:                                                        *)
(*   StartOk        writers start in order; optionally only after every    *)
(*                  older writer is dead                                    *)
(*   OpenForWriteOk FSEditLog.openForWrite 333-345 readable-stream check    *)
(*   SendOk         header txn synced alone (FSEditLog 1453-1460)           *)
(*   PurgeOk        FSEditLog.purgeLogsOlderThan 1519-1542                  *)
(*   RejectOk       ILC.reserveQueueSpace 448-458                           *)
(*   AllowRoll      log rolls (finalize by the active writer) on/off        *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxJNCrash, MaxDrop, MaxLate, MaxLoseReply, MaxReject, MaxAcceptCrash,
    MaxWCrash, MaxPurge,
    MaxBatch,            \* largest batch (txns per sendEdits)
    ConcurrentWriters,   \* a new writer may start while older ones are alive
    AllowRoll,           \* the active writer may finalize its segment
    RecoveryCallsCarryNoC
        \* Scenario-isolation filter (removes behaviors, adds none): a
        \* prepareRecovery / acceptRecovery task may only be dispatched while
        \* its writer's committedTxId is still INVALID, i.e. before the new
        \* writer's first write quorum.  This is the assumption of brief
        \* sec. 2 / analysis-report 4.1 ("prepareRecovery / acceptRecovery
        \* never carry a C").  The code does not guarantee it: createReqInfo
        \* runs when the task starts (ILC 287-291, 541-546) and
        \* setCommittedTxId updates every channel, including one whose
        \* recovery tasks are still queued behind a slow call (ALS 75-79).
        \* TRUE in the brief's Scenario hunts, FALSE in MC_hunt_late_accept.

VARIABLE fc              \* fault counters

mcVars == <<vars, fc>>

FcInit == [crash |-> 0, drop |-> 0, late |-> 0, lose |-> 0, reject |-> 0,
           acrash |-> 0, wcrash |-> 0, purge |-> 0]

MCInit == Init /\ fc = FcInit

Bump(k) == fc' = [fc EXCEPT ![k] = @ + 1]

-----------------------------------------------------------------------------
(***************************************************************************)
(* NameNode-usage realism                                                   *)
(***************************************************************************)

\* Writer w is the w-th NameNode incarnation to try to become active.
StartOk(w) ==
    /\ IF w = 1 THEN TRUE ELSE wr[w - 1].pc # "init"
    /\ ConcurrentWriters \/ \A v \in W : v < w => wr[v].pc = "dead"

\* FSEditLog.openForWrite 333-345: refuse to start segment t if a stream
\* containing t is readable.  The manifest comes from a quorum of JNs
\* (QJM.selectInputStreams -> getEditLogManifest, waitForWriteQuorum), so
\* the NameNode proceeds if some majority of up JNs shows no non-empty
\* segment containing t.  Only the first segment of a writer is checked
\* (rollEditLog does not call openForWrite).
ShowsTxn(j, t) ==
    \E s \in Seg : /\ jn[j].files[s].ex
                   /\ jn[j].files[s].end >= 1
                   /\ s <= t /\ t <= jn[j].files[s].end
OpenForWriteOk(w) ==
    \/ wr[w].opened
    \/ \E Q \in SUBSET JN :
         /\ Cardinality(Q) >= Majority
         /\ \A j \in Q : jn[j].up /\ ~ShowsTxn(j, wr[w].last + 1)

\* FSEditLog.startLogSegmentAndWriteHeaderTxn 1453-1460: the header txn
\* (OP_START_LOG_SEGMENT) is the first txid of a segment and is synced alone.
SendOk(w, n) ==
    /\ n <= MaxBatch
    /\ wr[w].last < wr[w].seg => n = 1

\* FSEditLog.purgeLogsOlderThan 1519-1542 (synchronized): only with the edit
\* log open, minTxIdToKeep <= curSegmentTxId (1526-1530), min = 0 is a no-op
\* (1531-1533).  It cannot interleave with startLogSegmentAndWriteHeaderTxn
\* (synchronized, header synced inside), but it can run while a later
\* batch waits for its quorum: logSync flushes outside the monitor (733-738).
\* The NameNode computes min = max(0, imageTxId + 1 - extraRetained)
\* (NNStorageRetentionManager 135-136, 171); any 1 <= min <= current
\* segment start is possible.
PurgeOk(w, m) ==
    /\ wr[w].pc \in {"act", "send"}
    /\ wr[w].seg # 0
    /\ wr[w].last >= wr[w].seg
    /\ m <= wr[w].seg

\* See RecoveryCallsCarryNoC.
LateRecoveryCallOk(w, j) ==
    IF ~RecoveryCallsCarryNoC \/ ch[w][j].q = <<>> THEN TRUE
    ELSE Head(ch[w][j].q).op \notin {"prep", "acc"} \/ wr[w].c = 0

\* ILC.reserveQueueSpace 448-458: a sendEdits is refused only while earlier
\* edits to that JN are still queued (queuedEditsSizeBytes > 0).
RejectOk(w, j) ==
    LET q == ch[w][j].q IN
    /\ q # <<>>
    /\ q[Len(q)].op = "jrnl"
    /\ \/ \E i \in 1..(Len(q) - 1) : q[i].op = "jrnl"
       \/ ch[w][j].inf.op = "jrnl"

-----------------------------------------------------------------------------
(***************************************************************************)
(* Wrapped next-state relation                                              *)
(***************************************************************************)

MCWriterNext(w) ==
    \/ /\ StartOk(w)
       /\ WRecoverUnfinalizedSegments(w)
       /\ UNCHANGED fc
    \/ /\ \E R \in SUBSET JN :
            \/ WCreateNewUniqueEpoch(w, R)
            \/ WRecoverPrepare(w, R)
            \/ WRecoverDecide(w, R)
       /\ UNCHANGED fc
    \/ /\ \/ WRecoverFinalize(w)
          \/ WRecoveryDone(w)
          \/ WStartLogSegmentDone(w)
          \/ WSendEditsDone(w)
          \/ WFinalizeLogSegmentDone(w)
          \/ WQuorumFail(w)
          \/ WQuorumAssertRethrow(w)
       /\ UNCHANGED fc
    \/ /\ OpenForWriteOk(w)
       /\ WStartLogSegment(w)
       /\ UNCHANGED fc
    \/ /\ \E n \in 1..MaxTxId : SendOk(w, n) /\ WSendEdits(w, n)
       /\ UNCHANGED fc
    \/ /\ AllowRoll
       /\ WFinalizeLogSegment(w)
       /\ UNCHANGED fc
    \/ /\ fc.purge < MaxPurge
       /\ \E m \in Seg : PurgeOk(w, m) /\ WPurgeLogsOlderThan(w, m)
       /\ Bump("purge")
    \/ /\ fc.wcrash < MaxWCrash
       /\ WCrash(w)
       /\ Bump("wcrash")

MCChannelNext(w, j) ==
    \/ /\ \/ LateRecoveryCallOk(w, j) /\ ChDispatch(w, j)
          \/ ChHeartbeat(w, j)
          \/ ChOutOfSync(w, j)
          \/ RpcConnectFail(w, j)
       /\ UNCHANGED fc
    \/ /\ fc.reject < MaxReject
       /\ RejectOk(w, j)
       /\ ChReject(w, j)
       /\ Bump("reject")
    \/ /\ fc.drop < MaxDrop
       /\ RpcDrop(w, j)
       /\ Bump("drop")
    \/ /\ fc.late < MaxLate
       /\ RpcLate(w, j)
       /\ Bump("late")

MCJNNext(j, w, src) ==
    \/ /\ JNHandle(j, w, src, FALSE)
       /\ UNCHANGED fc
    \/ /\ fc.lose < MaxLoseReply
       /\ JNHandle(j, w, src, TRUE)
       /\ Bump("lose")
    \/ /\ TargetCheck(j, w, src)
       /\ UNCHANGED fc
    \/ /\ fc.acrash < MaxAcceptCrash
       /\ JNAcceptRecoveryCrash(j, w, src)
       /\ Bump("acrash")

MCNext ==
    /\ ~targetFired                    \* stop once the target has thrown
    /\ \/ \E w \in W : MCWriterNext(w)
       \/ \E w \in W, j \in JN : MCChannelNext(w, j)
       \/ \E j \in JN, w \in W, src \in {"in", "zb"} : MCJNNext(j, w, src)
       \/ \E j \in JN :
            \/ /\ fc.crash < MaxJNCrash
               /\ JNCrash(j)
               /\ Bump("crash")
            \/ /\ JNRestart(j)
               /\ UNCHANGED fc

MCSpec == MCInit /\ [][MCNext]_mcVars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Symmetry, invariants                                                     *)
(***************************************************************************)

\* JournalNodes are interchangeable: every quantifier over JN is symmetric
\* and ties (Best) are nondeterministic.  Writers are not (StartOk orders them).
JNSymmetry == Permutations(JN)

MCTypeOK ==
    /\ TypeOK
    /\ fc \in [{"crash", "drop", "late", "lose", "reject", "acrash", "wcrash",
                "purge"} -> Nat]

\* Hunting target (base.tla): TargetSafe.  Sanity: TargetReached (base.tla),
\* TypeOK, ReqCarriesSenderC.
=============================================================================
