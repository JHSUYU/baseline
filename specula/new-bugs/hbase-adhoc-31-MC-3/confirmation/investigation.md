# MC-3 investigation record

Evidence only. Pinned tree: 1790942bb2. Line numbers are the pristine tree's unless marked.

## Step 1: code audit
- `RegionServerTracker.upgrade` (RegionServerTracker.java:128-160): records every server listed in ZK as online via
  `checkAndRecordNewServer` (:145-155 loop), then calls `findDeadServersAndProcess`, which adds servers with an unfinished SCP to the dead
  list (`ServerManager.findDeadServersAndProcess`, `deadservers::putIfAbsent`). Nothing removes a server that is in both.
- `ServerManager.checkAndRecordNewServer`: a same-address server with a higher startcode calls `expireServer(existing)`.
- `ServerManager.expireServer`: returns early if the server is in the dead list (:675-678), before `moveFromOnlineToDeadServers`.
  So a server that is online and dead stays online.
- `ServerManager.checkIsDead`: `cleanPreviousInstance` runs only when `master.isInitialized()`. A successor registering earlier does
  not clear the dead entry, so its `expireServer(P)` no-ops. A later report does clear it.
- `RegionServerTracker.processAsActiveMaster`: znode deletion calls the same `expireServer`.
- `RSProcedureDispatcher.remoteDispatch` (:153): `isServerOnline(P)` picks a real call. Address only reaches the successor.
- `RSRpcServices.throwOnWrongStartCode(long)`: the target. Single multi-line `throw` at 1878-1881. LineNumberTable `1878: 18, 1880: 34`;
  `ServiceException.<init>` is at bytecode 48, so a throw from it always reports frame 1880.
- `ServerManager.shutdownCluster` (:993-1000) and `expireServer` (:700): `master.stop` is reached only when `onlineServers` is empty.
  `HMaster.run` (:649-651) idles until stopped.
- `RegionRemoteProcedureBase.execute` (:340): a restored close in DISPATCH re-adds itself to the dispatcher.

Safeguards recorded: SCP interrupts the transition (serverCrashed); the successor's post-init report clears the dead entry; znode
deletion expires a server that is no longer dead; TRSP.confirmClosed retries a failed close.

Call chain: Admin#move -> TRSP -> CloseRegionProcedure -> RSProcedureDispatcher -> [crash, fail-fast expire, SCP stored] -> master
failover -> upgrade -> regionServerStartup(S) -> expireServer no-op -> restored close -> S.executeProcedures -> target.

Fault realization: `HRegionServer.run` calls `rpcServices.stop()` then `deleteMyEphemeralNode()`. The codebase's simulated kill-9
(`MiniHBaseClusterRegionServer.kill`) runs both, so its znode vanishes at once. The test parks between them in an `rsClass`/`createRpcServices`
subclass: port closed, ZK session alive, which is the master-visible state of a real kill -9 until session expiry. Releasing it deletes the
znode, which is the master-visible session expiry.

Reachability limit (reasoned, not run): crash T0, session ends T0+90s, fail-fast no earlier than T0+28.5s. A kill -9 of the master holds its own
active-master znode for its session too, so a new master would become active after P's znode is gone at equal timeouts. The scenario therefore
needs a prompt handoff: master self-abort or stop. The test uses abortMaster. SCP must also still be pending at the handoff.

## Step 2: developer knowledge
- Comment at ServerManager.checkIsDead: "Remove dead server with same hostname and port of newly checking in rs after master initialization.
  See HBASE-5916". Comment in checkAndRecordNewServer: "TODO: ts can theoretically collide".
- Comment at RegionServerTracker.upgrade javadoc says SCP for servers that died between masters is handled there; nothing on a server in both sets.
- TRSP.confirmClosed comment: "think the target RS crashes and restarts immediately, ... we can only recover after SCP takes care of this RS":
  a same-port restart rejecting closes is anticipated, as a transient recovered by SCP.
- HMaster.shutdown comment: "when Master is last running server, it'll stop itself": shutdown assumes onlineServers drains.
- Tests: grep of hbase-server/src/test/java finds none naming `findDeadServersAndProcess`, the `already in DeadServer` line or `.upgrade(`, and none using both
  `isDeadServer` and `isServerOnline`. So no existing test asserts this state, either way.

## Step 3: known status (run after the reproduction verdict was settled; sets Novelty only)
Queries:
- git log on RegionServerTracker.java; pickaxe `but already in DeadServer`, `deadservers::putIfAbsent` on ServerManager.java; --grep shutdown/hang/dead/online/ghost on master/.
- JIRA JQL: text ~ "already in DeadServer" (27); text ~ RegionServerTracker AND DeadServer (22); summary shutdown AND hang AND text onlineServers (0);
  text ~ throwOnWrongStartCode (1); updated>=-180d DeadServer/expireServer/RegionServerTracker (38); text ~ "intended for a different server" (33);
  expireServer AND failover (8); stop-hbase AND dead AND master shutdown (0); summary "same port" AND restart (0); onlineServers AND deadServers (11);
  created>=-120d dead/SCP/failover/online/shutdown/startcode (5); resolved>=-120d ServerManager/RegionServerTracker/expireServer (2).
- GitHub search API, apache/hbase: "already in DeadServer" (0); RegionServerTracker dead online PRs (2); expireServer DeadServer PRs (1);
  throwOnWrongStartCode PRs (0). The fifth query (merged PRs since 2026-06-01) hit the rate limit, so recent coverage used the commits API instead.
- GitHub commits API, upstream master, for ServerManager, RegionServerTracker, DeadServer, RSProcedureDispatcher: latest 6 each. Past the pinned base (2026-09-18) only
  HBASE-30335 and HBASE-30433 (flushed sequence ids) touch them.
- Web search: exact symptom not found.
- `gh` is not installed, so it was not used.

Closest, all a different mechanism:
- HBASE-20144 (resolved): master shutdown hangs when no RS is live at shutdown, so expireServer never runs. Same symptom, different cause.
- HBASE-21565 (resolved): dead list cleared too early gives concurrent SCPs. Opposite direction.
- HBASE-30463 (resolved): duplicate SCPs in the store crash master init. Adjacent (mentions cleanPreviousInstance), different consequence.
- HBASE-5916 (closed): origin of the isInitialized guard.
- HBASE-30389 (open): stale region location after failover. Different state.
- HBASE-28638, HBASE-29714: fail-fast and its limit of 10, which this scenario uses.
Result: no report of this mechanism at this site.
