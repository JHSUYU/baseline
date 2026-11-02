-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for hdfs-adhoc-33 (instrumentation-spec.md).          *)
(*                                                                         *)
(* One NDJSON log per run, written by one DataNode JVM through a           *)
(* synchronized writer, so the file order is a total order of the events.  *)
(* The brief puts the target in Category B (threads of one JVM), but its   *)
(* steps are lock-delimited, not ns-level lock-free operations: every      *)
(* event whose order matters for the guard is emitted while its thread     *)
(* holds the lock that makes the base step atomic (the DataStorage monitor *)
(* for GetBlockPoolSliceStorage, TargetCheck and ActorExit; the DataNode   *)
(* monitor for RefreshVolumesSubmit / RefreshVolumesFinish).  The other    *)
(* events are thread-local steps, which commute with every other thread.   *)
(* So the linear (cursor) pattern applies and no timebox is needed.        *)
(*                                                                         *)
(* The first event (Init) gives the pools and is checked by ASSUMEs; every *)
(* later event is one base action.  Each wrapper checks the event against  *)
(* the pre-state, calls the base action unchanged, then checks the logged  *)
(* post-state.  There are no silent actions: every base step the workload  *)
(* performs has its own event.                                             *)
(***************************************************************************)
EXTENDS base, Json, IOUtils

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

\* Lines tagged "trace" (instrumentation-spec.md section 1); other output is ignored.
TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
        sel == SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                         /\ x.tag = "trace"
                                         /\ "event" \in DOMAIN x)
    IN [i \in DOMAIN sel |-> sel[i].event])

ToSet(s) == {s[i] : i \in DOMAIN s}

\* Indices of the events named n in the log tl.  Derived definitions bind the log
\* once with LET, so that the NDJSON file is parsed once.
EvIdx(tl, n) == {i \in DOMAIN tl : tl[i].name = n}

(***************************************************************************)
(* The first event.  ASSUMEs, so that a bad first event stops TLC instead  *)
(* of leaving zero initial states (which TLC reports as "No error").       *)
(* Init describes the state after MiniDFSCluster.waitActive, which base    *)
(* Init fixes: every pool listed, initialised, running and in              *)
(* bpStorageMap, every nameservice configured, the DataNode running.       *)
(***************************************************************************)
ASSUME LET tl == TraceLog IN
    /\ Len(tl) > 0
    /\ tl[1].name = "Init"

ASSUME LET tl == TraceLog IN
    LET st == tl[1].state
        m  == tl[1].msg
    IN /\ ToSet(m.pools) # {}
       /\ ToSet(st.mapped) = ToSet(m.pools)
       /\ ToSet(m.configured) = ToSet(m.pools)
       /\ st.dnRun = TRUE
       /\ {st.bpos[i].bp : i \in DOMAIN st.bpos} = ToSet(m.pools)
       /\ \A i \in DOMAIN st.bpos : /\ st.bpos[i].listed
                                    /\ st.bpos[i].hasId
                                    /\ st.bpos[i].svcRun
                                    /\ st.bpos[i].alive

\* The base spec has one reconfiguration per behavior.
ASSUME LET tl == TraceLog IN Cardinality(EvIdx(tl, "RefreshVolumesSubmit")) <= 1

(***************************************************************************)
(* Constants derived from the log (bound with <- in Trace.cfg)             *)
(***************************************************************************)
\* Pools: the block pool IDs of the BPOfferServices at Init.
TraceNS == TLCEval(LET tl == TraceLog IN ToSet(tl[1].msg.pools))

\* New volumes: the locations RefreshVolumesSubmit hands to the workers.
TraceVols == TLCEval(LET tl == TraceLog IN
                       UNION {ToSet(tl[i].msg.vols) : i \in EvIdx(tl, "RefreshVolumesSubmit")})

(***************************************************************************)
(* Cursor and helpers                                                      *)
(***************************************************************************)
VARIABLE l

traceVars == <<vars, l>>

ev == TraceLog[l]

IsEv(n) == l <= Len(TraceLog) /\ ev.name = n

Step == l' = l + 1

\* The hooks log a null NamespaceInfo (BPOS:236-243) as the string "null".
AsNs(x) == IF x = "null" THEN Null ELSE x

\* RemoteException classes that end an actor (BPSA:793-795, BPSA:1463-1465).
RejectClasses ==
    {"org.apache.hadoop.hdfs.protocol.UnregisteredNodeException",
     "org.apache.hadoop.hdfs.server.protocol.DisallowedDatanodeException",
     "org.apache.hadoop.hdfs.server.common.IncorrectVersionException"}

\* Sites of the monitor-gated DataNode stop paths (base.tla DNStopMonitorGate).
GatedStopSites == {"rpc", "upgrade", "diskfail"}

(***************************************************************************)
(* Reconfiguration caller (DN.refreshVolumes)                              *)
(***************************************************************************)

\* DN:1287: the snapshot list, in iteration order.
RefreshVolumesSnapshotEv ==
    /\ IsEv("RefreshVolumesSnapshot")
    /\ RefreshVolumesSnapshot
    /\ snapList' = ev.msg.list
    /\ Step

\* DN:1288: the i-th NamespaceInfo read (1-based), by block pool ID.
RefreshVolumesReadNsInfoEv ==
    /\ IsEv("RefreshVolumesReadNsInfo")
    /\ ev.msg.i = Len(nsInfos) + 1
    /\ RefreshVolumesReadNsInfo
    /\ nsInfos'[ev.msg.i] = AsNs(ev.msg.bp)
    /\ Step

\* DN:1316-1317, inside the DataNode monitor: the new locations.
RefreshVolumesSubmitEv ==
    /\ IsEv("RefreshVolumesSubmit")
    /\ RefreshVolumesSubmit
    /\ ToSet(ev.msg.vols) = Vols
    /\ Step

\* DN:1370-1371, inside the DataNode monitor: which volumes were added.
RefreshVolumesFinishEv ==
    /\ IsEv("RefreshVolumesFinish")
    /\ RefreshVolumesFinish
    /\ {w \in Vols : wpc[w] = "done"} = ToSet(ev.msg.added)
    /\ {w \in Vols : wpc[w] = "failed"} = ToSet(ev.msg.failed)
    /\ Step

(***************************************************************************)
(* addVolume worker ev.nid (its StorageLocation)                           *)
(***************************************************************************)

\* DS:335-336: the builder exists; nsInfos.get(0) was used at DS:333-334.
LoadStorageDirectoryEv ==
    /\ IsEv("LoadStorageDirectory")
    /\ ev.nid \in Vols
    /\ LoadStorageDirectory(ev.nid)
    /\ wpc'[ev.nid] = "get"
    /\ nsInfos[1] = AsNs(ev.msg.bp0)
    /\ Step

\* DS:340 inside the DataStorage monitor: index, pool, whether DS:1413-1416 created
\* the entry, and the map's keys afterwards.
GetBlockPoolSliceStorageEv ==
    /\ IsEv("GetBlockPoolSliceStorage")
    /\ ev.nid \in Vols
    /\ wpc[ev.nid] = "get"
    /\ wi[ev.nid] = ev.msg.i
    /\ nsInfos[ev.msg.i] = ev.msg.bp
    /\ ev.msg.created = (ev.msg.bp \notin bpMap)
    /\ GetBlockPoolSliceStorage(ev.nid)
    /\ bpMap' = ToSet(ev.state.mapped)
    /\ Step

\* DS:343: the builder's bpStorageDirMap keys afterwards.
AddBpStorageDirectoriesEv ==
    /\ IsEv("AddBpStorageDirectories")
    /\ ev.nid \in Vols
    /\ wpc[ev.nid] = "dirs"
    /\ wi[ev.nid] = ev.msg.i
    /\ nsInfos[ev.msg.i] = ev.msg.bp
    /\ AddBpStorageDirectories(ev.nid)
    /\ wKeys'[ev.nid] = ToSet(ev.state.keys)
    /\ Step

\* FDI:540: one scan iteration.
AddBlockPoolAndScanEv ==
    /\ IsEv("AddBlockPoolAndScan")
    /\ ev.nid \in Vols
    /\ wpc[ev.nid] = "scan"
    /\ wi[ev.nid] = ev.msg.i
    /\ nsInfos[ev.msg.i] = ev.msg.bp
    /\ AddBlockPoolAndScan(ev.nid)
    /\ Step

\* DS:254-264 inside the DataStorage monitor: the map build() saw (frozen for the
\* loop), the builder's keys, and the outcome.
TargetCheckEv ==
    /\ IsEv("TargetCheck")
    /\ ev.nid \in Vols
    /\ bpMap = ToSet(ev.state.mapped)
    /\ wKeys[ev.nid] = ToSet(ev.state.keys)
    /\ TargetCheck(ev.nid)
    /\ targetFired' = ev.msg.fired
    /\ Step

\* FDI:560-561.
ActivateVolumeEv ==
    /\ IsEv("ActivateVolume")
    /\ ev.nid \in Vols
    /\ ActivateVolume(ev.nid)
    /\ Step

(***************************************************************************)
(* Block pool ev.nid (its block pool ID) and the DataNode                  *)
(***************************************************************************)

\* BPSA:796-797.
OfferServiceRejectedEv ==
    /\ IsEv("OfferServiceRejected")
    /\ ev.nid \in NS
    /\ ev.msg.cls \in RejectClasses
    /\ OfferServiceRejected(ev.nid)
    /\ Step

\* BPSA:1466-1467.
CommandProcessorRejectedEv ==
    /\ IsEv("CommandProcessorRejected")
    /\ ev.nid \in NS
    /\ ev.msg.cls \in RejectClasses
    /\ CommandProcessorRejected(ev.nid)
    /\ Step

\* BPM:247-248: the stopped pool and the pools of the new conf's nameservices.
\* One refresh may stop several pools in turn (BPM:246-251), each its own event;
\* the new conf's pools stay configured throughout and are never empty (BPM:165-168).
RefreshNamenodesRemoveEv ==
    /\ IsEv("RefreshNamenodesRemove")
    /\ ev.nid \in NS
    /\ ev.nid \notin ToSet(ev.msg.remaining)
    /\ RefreshNamenodesRemove(ev.nid)
    /\ ToSet(ev.msg.remaining) # {}
    /\ ToSet(ev.msg.remaining) \subseteq configured'
    /\ Step

\* DS:1422 inside the DataStorage monitor (or DN:2170 when hasBlockPoolId() is
\* false): whether the entry was removed, and the map's keys afterwards.
ActorExitEv ==
    /\ IsEv("ActorExit")
    /\ ev.nid \in NS
    /\ ev.msg.removed = bpos[ev.nid].hasId
    /\ ActorExit(ev.nid)
    /\ bpMap' = ToSet(ev.state.mapped)
    /\ Step

\* DN:2545-2546.
DNShutdownEv ==
    /\ IsEv("DNShutdown")
    /\ DNShutdown
    /\ dnRun' = ev.state.dnRun
    /\ Step

\* After the stop path's last DataNode-monitor acquisition.
DNStopMonitorGateEv ==
    /\ IsEv("DNStopMonitorGate")
    /\ ev.msg.site \in GatedStopSites
    /\ DNStopMonitorGate
    /\ Step

\* DN:2545 (async RPC thread), DN:2595 (upgrade) or DN:2743 (fatal disk error).
DNStopClearShouldRunEv ==
    /\ IsEv("DNStopClearShouldRun")
    /\ ev.msg.site \in GatedStopSites
    /\ DNStopClearShouldRun
    /\ dnRun' = ev.state.dnRun
    /\ Step

(***************************************************************************)
(* Specification                                                           *)
(***************************************************************************)
TraceInit ==
    /\ Init
    /\ l = 2

TraceNext ==
    \/ RefreshVolumesSnapshotEv
    \/ RefreshVolumesReadNsInfoEv
    \/ RefreshVolumesSubmitEv
    \/ RefreshVolumesFinishEv
    \/ LoadStorageDirectoryEv
    \/ GetBlockPoolSliceStorageEv
    \/ AddBpStorageDirectoriesEv
    \/ AddBlockPoolAndScanEv
    \/ TargetCheckEv
    \/ ActivateVolumeEv
    \/ OfferServiceRejectedEv
    \/ CommandProcessorRejectedEv
    \/ RefreshNamenodesRemoveEv
    \/ ActorExitEv
    \/ DNShutdownEv
    \/ DNStopMonitorGateEv
    \/ DNStopClearShouldRunEv

TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

\* Every event was consumed.
TraceMatched == <>(l > Len(TraceLog))

\* Debugging view of a behavior (Trace.cfg ALIAS).
TraceAlias ==
    [l |-> l,
     event |-> IF l <= Len(TraceLog) THEN TraceLog[l].name ELSE "<end>",
     bpMap |-> bpMap, bpos |-> bpos, configured |-> configured,
     dnRun |-> dnRun, dnStop |-> dnStop, rpc |-> rpc, snapList |-> snapList,
     nsInfos |-> nsInfos, wpc |-> wpc, wi |-> wi, wKeys |-> wKeys,
     targetFired |-> targetFired]

=============================================================================
