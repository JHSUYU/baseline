------------------------------ MODULE Trace ------------------------------
(***************************************************************************)
(* Trace validation for base (hdfs-adhoc-k7).  Category B timebox pattern: *)
(* every event carries a logical-clock interval [start, end] taken from   *)
(* one global AtomicLong immediately before / after the traced access, and *)
(* the EXACT value the access read or wrote (taken from the props object or *)
(* the constant written, never from a racy re-read of the shared field).   *)
(* Events are grouped per logical thread; ViablePIDs enforces real-time    *)
(* order between non-overlapping intervals and lets TLC search the order   *)
(* of overlapping ones.  See instrumentation-spec.md for the event schema. *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, SequencesExt, FiniteSets, TLC

----------------------------------------------------------------------------
(* Trace loading *)

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == SelectSeq(ndJsonDeserialize(JsonFile), LAMBDA x : x.tag = "trace")

\* First line: {"name":"Init", "nid":"test", "state":{...}} (instrumentation-spec §1.3)
InitRec == TraceLog[1].event.state

Events == SelectSeq(TraceLog, LAMBDA x : x.event.name /= "Init")

ASSUME TraceLog[1].event.name = "Init"

----------------------------------------------------------------------------
(* Value mapping: implementation values -> model encodings *)

\* LVs are JSON integers (e.g. -57).  0 is the field's initial value.
LVOf(x) == CASE x = InitRec.dnlv -> DNLV
             [] x = 0            -> INITLV
             [] x > InitRec.dnlv -> OLDLV
             [] OTHER            -> "badLV"

\* cTimes are JSON strings (epoch millis do not fit TLC's 32-bit ints).
InitOldCTs == { r.ct : r \in {q \in ToSet(InitRec.vols) : q.ver /\ q.ct /= InitRec.nsCTime} }
ASSUME Cardinality(InitOldCTs) <= 1     \* the model has one old cTime C0

CTOf(s) == CASE s = InitRec.nsCTime -> NsCT
             [] s \in InitOldCTs    -> OldCT
             [] OTHER               -> "badCT"

----------------------------------------------------------------------------
(* Constants derived from the trace (overridden in Trace.cfg) *)

TraceStartOrder == InitRec.startOrder
TraceHsVols     == ToSet(InitRec.hsVols)
TracePoolSize   == InitRec.poolSize

TraceInitDisk(v) ==
    LET r == CHOOSE q \in ToSet(InitRec.vols) : q.vol = v IN
    IF r.ver
      THEN [ver |-> TRUE, lv |-> LVOf(r.lv), ct |-> CTOf(r.ct),
            prevTmp |-> FALSE, prev |-> r.prev]
      ELSE [FreshDisk EXCEPT !.prev = r.prev]

TraceInitDiskSet == { [v \in Vols |-> TraceInitDisk(v)] }

----------------------------------------------------------------------------
(* Per-thread traces *)

ThreadOfEv(e) == IF e.event.nid = "main" THEN MainT ELSE <<e.event.nid, e.event.msg.vol>>

ASSUME \A i \in 1..Len(Events) : ThreadOfEv(Events[i]) \in Threads

traces == [t \in Threads |-> SelectSeq(Events, LAMBDA e : ThreadOfEv(e) = t)]

VARIABLE tpc          \* per-thread cursor into traces[t]
traceVars == <<tpc>>
allVars == <<vars, tpc>>

ThreadsWithEvents == { t \in Threads : tpc[t] <= Len(traces[t]) }

Ev(t)   == traces[t][tpc[t]].event
Name(t) == Ev(t).name
M(t)    == Ev(t).msg

\* Timebox partial order (harness-generation concurrent-timebox-guide §5).
ViablePIDs ==
    { t \in ThreadsWithEvents :
        ~ \E u \in ThreadsWithEvents :
            /\ u /= t
            /\ M(u).end < M(t).start }

----------------------------------------------------------------------------
(* Event matching.  Every wrapper calls the base action and validates the  *)
(* variables that action writes against the values captured in the event. *)

DTNames == {"DTRegular", "DTRestore", "DTUpgrade", "DTThrow"}

MatchEvent(t) ==
    LET m == M(t)
        v == m.vol
    IN
    /\ VolOf(t) = v
    /\ CASE Name(t) = "HotSwapStart" ->
              HotSwapStart(t)
         [] Name(t) = "Analyze" ->
              /\ Analyze(t)
              /\ pc'[t] = IF m.state = "NORMAL" THEN "rpLV" ELSE "fmtLV"
         [] Name(t) = "FormatSetLV" ->
              /\ FormatSetLV(t)
              /\ bpLV' = LVOf(m.val)
         [] Name(t) = "FormatSetCT" ->
              /\ FormatSetCT(t)
              /\ bpCT' = CTOf(m.val)
         [] Name(t) = "WritePropsLV" ->
              /\ WritePropertiesLV(t)
              /\ loc'[t].wlv = LVOf(m.val)
         [] Name(t) = "WritePropsCT" ->
              /\ WritePropertiesCT(t)
              /\ disk'[v].lv = LVOf(m.lv)
              /\ disk'[v].ct = CTOf(m.ct)
         [] Name(t) = "ReadPropsLV" ->
              /\ ReadPropertiesLV(t)
              /\ bpLV' = LVOf(m.lv)
              /\ loc'[t].pct = CTOf(m.ct)
         [] Name(t) = "ReadPropsCT" ->
              /\ ReadPropertiesCT(t)
              /\ bpCT' = CTOf(m.val)
         [] Name(t) = "DTRegular" ->           \* BPSS:405-407 returned false
              /\ DoTransitionR406(t)
              /\ pc'[t] = "regCT"
         [] Name(t) = "DTRestore" ->           \* BPSS:409-414 taken
              /\ bpLV > DNLV
              /\ DoTransitionR409(t)
         [] Name(t) = "DTUpgrade" ->           \* BPSS:415-418 taken
              /\ \/ DoTransitionR415(t)
                 \/ TargetCheck(t)
              /\ pc'[t] = "upgrade"
              /\ ~targetFired'
         [] Name(t) = "DTThrow" ->             \* BPSS:422 (the target)
              /\ TargetCheck(t)
              /\ targetFired'
         [] Name(t) = "RegCheckCTime" ->
              /\ RegularCheckCTime(t)
              /\ m.ok = (pc'[t] = "regLV")
         [] Name(t) = "RegSetLV" ->
              /\ RegularSetLV(t)
              /\ bpLV' = LVOf(m.val)
         [] Name(t) = "UpgradeRename" ->
              /\ IF m.async THEN DoUpgradeSubmit(t) ELSE DoUpgradeSync(t)
              /\ disk'[v].prevTmp
              /\ ~disk'[v].ver
         [] Name(t) = "LinkAllBlocks" ->
              LinkAllBlocks(t)
         [] Name(t) = "UpgradeSetLV" ->
              /\ UpgradeSetLV(t)
              /\ bpLV' = LVOf(m.val)
         [] Name(t) = "UpgradeSetCT" ->
              /\ UpgradeSetCT(t)
              /\ bpCT' = CTOf(m.val)
         [] Name(t) = "UpgradeRenamePrev" ->
              /\ UpgradeRenamePrev(t)
              /\ disk'[v].prev /\ ~disk'[v].prevTmp
         [] Name(t) = "LoadBpDone" ->
              JoinUpgradeTasks(t)
         [] OTHER -> FALSE

----------------------------------------------------------------------------
(* Silent actions: the guard reads of doTransition that the instrumentation *)
(* cannot observe without editing the guard expressions (adhoc Phase 2.5:  *)
(* never modify the target check).  Their outcomes are pinned by the next  *)
(* outcome event ("DT..." names) of the same thread, which is consumed by the read   *)
(* that ends the guard chain.  Constraints: thread is viable, its next     *)
(* event is a "DT..." event for the same volume, and each silent read takes    *)
(* only the branch that does NOT emit an event.                            *)

SilentGuardRead(t) ==
    /\ t \in ViablePIDs
    /\ Name(t) \in DTNames
    /\ VolOf(t) = M(t).vol
    /\ \/ DoTransitionR405(t)                                  \* BPSS:405 (no event)
       \/ DoTransitionR406(t) /\ pc'[t] = "r409"               \* BPSS:406 false
       \/ DoTransitionR409(t) /\ ~(bpLV > DNLV)                \* BPSS:409 false
       \/ DoTransitionR415(t) /\ pc'[t] = "r416"               \* BPSS:415 false

----------------------------------------------------------------------------
(* Init / Next *)

TraceInit ==
    /\ Init
    /\ tpc = [t \in Threads |-> 1]

TraceNext ==
    \/ /\ ThreadsWithEvents /= {}
       /\ \E t \in ViablePIDs :
            /\ MatchEvent(t)
            /\ tpc' = [tpc EXCEPT ![t] = tpc[t] + 1]
    \/ /\ ThreadsWithEvents /= {}
       /\ \E t \in Threads : SilentGuardRead(t)
       /\ UNCHANGED tpc
    \/ /\ ThreadsWithEvents = {}
       /\ UNCHANGED allVars

TraceSpec == TraceInit /\ [][TraceNext]_allVars /\ WF_allVars(TraceNext)

TraceView == <<vars, tpc>>

\* The whole trace was consumed.
TraceMatched == <>(ThreadsWithEvents = {})

\* Existential acceptance check (Trace_accept.cfg): VIOLATED iff some
\* explored interleaving consumes every event.  Use it to tell a dead
\* branch (an overlapping-interval order the real run did not take) from a
\* genuine mismatch when TraceMatched fails.
TraceNotAccepted == ThreadsWithEvents /= {}

TraceAlias ==
    [ tpc       |-> tpc,
      next      |-> [t \in ThreadsWithEvents |-> Name(t)],
      viable    |-> ViablePIDs,
      pc        |-> pc,
      bpLV      |-> bpLV,
      bpCT      |-> bpCT,
      disk      |-> disk,
      curVol    |-> curVol,
      volRes    |-> volRes,
      targetFired |-> targetFired ]

=============================================================================
